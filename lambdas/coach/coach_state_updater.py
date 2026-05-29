"""
coach_state_updater.py — Coach Intelligence Phase 2: Post-Generation State Updater

Runs after a coach generates content. Uses Haiku to extract structured metadata
from the coach's output text (themes, structural fingerprint, threads, predictions,
decision classes, anti-pattern violations), then writes results to DynamoDB:

  - OUTPUT# record with full content + extracted metadata
  - VOICE#state update with latest opening type and overused pattern flags
  - New THREAD# records for threads opened
  - Updated THREAD# records for threads referenced (bump reference_count)
  - TRACE# reasoning trace record (returned to caller)

Phase 2 target: sleep_coach (Dr. Lisa Park).

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

from phase_filter import with_phase_filter  # ADR-058

# Structured logger
try:
    from platform_logger import get_logger
    logger = get_logger("coach-state-updater")
except ImportError:
    logger = logging.getLogger("coach-state-updater")
    logger.setLevel(logging.INFO)

# ══════════════════════════════════════════════════════════════════════════════
# CONFIGURATION
# ══════════════════════════════════════════════════════════════════════════════

REGION = os.environ.get("AWS_REGION", "us-west-2")
TABLE_NAME = os.environ.get("TABLE_NAME", "life-platform")
S3_BUCKET = os.environ.get("S3_BUCKET", "matthew-life-platform")

ANTHROPIC_API = "https://api.anthropic.com/v1/messages"
AI_MODEL_HAIKU = os.environ.get("AI_MODEL_HAIKU", "claude-haiku-4-5-20251001")

# CloudWatch metrics
_cw = boto3.client("cloudwatch", region_name=REGION)
_LAMBDA_NAME = os.environ.get("AWS_LAMBDA_FUNCTION_NAME", "coach-state-updater")
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
# Measurable-metric allowlist for prediction extraction
# ══════════════════════════════════════════════════════════════════════════════
# Mirrors METRIC_SOURCES in coach_prediction_evaluator.py. Predictions whose
# metric_hint does not normalize to one of these keys are stored as
# evaluation.type="qualitative" (the evaluator skips qualitative predictions
# rather than churning daily "inconclusive: no data" outcomes).
#
# Aggregate suffixes (_7day_avg, _14day_avg, _30day_avg) are valid extensions
# of any base key — the evaluator computes those on-the-fly.
#
# Keep in sync with lambdas/coach_prediction_evaluator.py:65 (METRIC_SOURCES).
MEASURABLE_METRICS = frozenset({
    # whoop
    "hrv", "hrv_7day_avg", "recovery_score", "resting_heart_rate",
    "sleep_duration_hours", "sleep_score", "deep_pct", "rem_pct",
    # withings
    "weight_lbs",
    # macrofactor
    "total_calories_kcal", "total_protein_g",
    # apple_health
    "steps", "blood_glucose_avg", "blood_glucose_std_dev",
    # dexa
    "body_fat_pct",
})

# Substring → measurable-metric mapping for normalizing prose-y metric hints.
# Checked in declared order — first match wins, so multi-word/specific patterns
# come BEFORE single-word ones to avoid wrong-match ordering bugs (e.g.
# "hours of sleep needed for optimal recovery" must hit sleep before recovery).
# Tuned for the actual coach-prediction language patterns observed in the
# LEARNING# audit (see v7.15.0 changelog: 504 predictions, 100% inconclusive,
# all due to unmapped metrics).
_METRIC_HINT_NORMALIZERS = (
    # Multi-word specific patterns first (precedence)
    ("heart rate variability",          "hrv"),
    ("resting heart rate",              "resting_heart_rate"),
    ("resting hr",                      "resting_heart_rate"),
    ("hours of sleep",                  "sleep_duration_hours"),
    ("sleep duration",                  "sleep_duration_hours"),
    ("sleep score",                     "sleep_score"),
    ("sleep quality",                   "sleep_score"),
    ("sleep efficiency",                "sleep_score"),
    ("deep sleep",                      "deep_pct"),
    ("rem sleep",                       "rem_pct"),
    ("rem percentage",                  "rem_pct"),
    ("blood glucose",                   "blood_glucose_avg"),
    ("glucose variability",             "blood_glucose_std_dev"),
    ("glucose excursion",               "blood_glucose_avg"),
    ("postprandial glucose",            "blood_glucose_avg"),
    ("post-meal glucose",               "blood_glucose_avg"),
    ("body fat",                        "body_fat_pct"),
    ("step count",                      "steps"),
    ("daily steps",                     "steps"),
    ("recovery score",                  "recovery_score"),
    ("recovery",                        "recovery_score"),
    # Single-word fallbacks (checked last)
    ("hrv",                             "hrv"),
    ("weight",                          "weight_lbs"),
    ("calorie",                         "total_calories_kcal"),
    ("kcal",                            "total_calories_kcal"),
    ("protein",                         "total_protein_g"),
    ("glucose",                         "blood_glucose_avg"),
    ("steps",                           "steps"),
)


def _parse_confidence(raw) -> float:
    """V2 P1.3 (2026-05-17): defensively parse Haiku-returned confidence.

    Haiku often returns "40%" or "0.4" or "high" / "medium" / "low". Prior code
    did naked float(raw) which crashed on "%" suffix → 17% error rate.
    Returns 0.5 on parse failure (neutral default).
    """
    if raw is None or raw == "":
        return 0.5
    s = str(raw).strip().lower()
    word_map = {"high": 0.85, "medium": 0.5, "med": 0.5, "low": 0.2,
                "very high": 0.95, "very low": 0.1, "unknown": 0.5}
    if s in word_map:
        return word_map[s]
    try:
        has_pct = s.endswith("%")
        val = float(s.rstrip("%").strip())
        if has_pct:
            val = val / 100.0
        return max(0.0, min(1.0, val))
    except (ValueError, TypeError):
        return 0.5


def _normalize_metric_hint(hint: str) -> str | None:
    """Map an LLM-produced metric_hint to a measurable key, or None.

    Used by the post-extraction normalizer in `_write_prediction_records`. If
    the hint already names an allowlisted key, returns it as-is. Otherwise
    walks the substring map. Returns None when nothing matches — caller marks
    the prediction qualitative so the evaluator skips it.
    """
    if not hint:
        return None
    h = hint.strip().lower()
    # Direct hit (covers aggregate-suffixed forms too — `hrv_7day_avg` etc.)
    if h in MEASURABLE_METRICS:
        return h
    # Substring map — try with underscores-as-spaces too so snake_case prose
    # like "sleep_efficiency" matches the "sleep efficiency" needle.
    h_spaced = h.replace("_", " ")
    for needle, target in _METRIC_HINT_NORMALIZERS:
        if needle in h or needle in h_spaced:
            return target
    return None


# Maximum opening history to keep in voice state
MAX_RECENT_OPENINGS = 10

# Staleness threshold — flag pattern if it appears in 3+ of last 5 outputs
STALENESS_WINDOW = 5
STALENESS_THRESHOLD = 3

# ══════════════════════════════════════════════════════════════════════════════
# SECRET CACHING
# ══════════════════════════════════════════════════════════════════════════════

_api_key_cache = {"key": None, "ts": 0}
_API_KEY_TTL = 900  # 15 minutes


def _get_api_key():
    """ADR-062: Bedrock IAM auth — sentinel; see task #90 for full plumbing removal."""
    return "_BEDROCK_IAM_"


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


def _emit_token_metrics(input_tokens, output_tokens,
                        cache_creation_tokens=0, cache_read_tokens=0):
    """Emit per-Lambda token usage to CloudWatch (non-fatal).

    V2 P0.6 (2026-05-17): added cache_creation/cache_read fields. Prior 2-arg
    signature silently dropped them, leaving AnthropicCacheReadTokens with zero
    datapoints in 30 days despite caching being wired.
    """
    try:
        metric_data = [
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
        ]
        if cache_creation_tokens or cache_read_tokens:
            metric_data.append({
                "MetricName": "AnthropicCacheWriteTokens",
                "Dimensions": [{"Name": "LambdaFunction", "Value": _LAMBDA_NAME}],
                "Value": cache_creation_tokens, "Unit": "Count",
            })
            metric_data.append({
                "MetricName": "AnthropicCacheReadTokens",
                "Dimensions": [{"Name": "LambdaFunction", "Value": _LAMBDA_NAME}],
                "Value": cache_read_tokens, "Unit": "Count",
            })
        _cw.put_metric_data(Namespace=_CW_NAMESPACE, MetricData=metric_data)
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

def _call_haiku(system, user_message, max_tokens=3000, temperature=0.1):
    """Call Anthropic Haiku with exponential backoff + CloudWatch metrics.

    Returns parsed JSON dict if the response is valid JSON, otherwise raw text.
    Raises on final failure after all retry attempts.

    2026-05-03: bumped default max_tokens 1500 → 3000. Was hitting truncation
    on 5-coach state extraction; truncation → invalid JSON → fallback to default.
    """
    api_key = _get_api_key()

    body = {
        "model": AI_MODEL_HAIKU,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "messages": [{"role": "user", "content": user_message}],
    }
    if system:
        body["system"] = [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}]

    payload = json.dumps(body).encode()
    req = urllib.request.Request(
        ANTHROPIC_API,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "anthropic-beta": "prompt-caching-2024-07-31",
        },
        method="POST",
    )

    # ADR-062 (2026-05-27): route through retry_utils.call_anthropic_raw (Bedrock).
    from retry_utils import call_anthropic_raw
    resp = call_anthropic_raw(req)
    text = resp["content"][0]["text"].strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        if "```json" in text:
            start = text.find("```json") + 7
            end = text.find("```", start)
            if end > start:
                try:
                    return json.loads(text[start:end].strip())
                except json.JSONDecodeError:
                    pass
        elif "```" in text:
            start = text.find("```") + 3
            end = text.find("```", start)
            if end > start:
                try:
                    return json.loads(text[start:end].strip())
                except json.JSONDecodeError:
                    pass
        return text


# ══════════════════════════════════════════════════════════════════════════════
# DYNAMODB OPERATIONS
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


def _put_item(item):
    """Write an item to DynamoDB with float-to-Decimal conversion."""
    try:
        table.put_item(Item=_float_to_decimal(item))
        return True
    except Exception as e:
        logger.error("put_item failed for %s/%s: %s", item.get("pk"), item.get("sk"), e)
        return False


def _query_begins_with(pk, sk_prefix, scan_forward=True):
    """Query DynamoDB for items with SK beginning with a prefix. ADR-058: phase-filtered."""
    from boto3.dynamodb.conditions import Key
    try:
        resp = table.query(**with_phase_filter({
            "KeyConditionExpression": Key("pk").eq(pk) & Key("sk").begins_with(sk_prefix),
            "ScanIndexForward": scan_forward,
        }))
        return _decimal_to_float(resp.get("Items", []))
    except Exception as e:
        logger.warning("query_begins_with(%s, %s) failed: %s", pk, sk_prefix, e)
        return []


# ══════════════════════════════════════════════════════════════════════════════
# VOICE SPEC LOADER
# ══════════════════════════════════════════════════════════════════════════════

def _load_voice_spec(coach_id):
    """Load the coach's voice specification from S3 for anti-pattern checking.

    Falls back to an empty spec if the file doesn't exist yet.
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


# ══════════════════════════════════════════════════════════════════════════════
# EXTRACTION PROMPT
# ══════════════════════════════════════════════════════════════════════════════

EXTRACTION_SYSTEM_PROMPT = (
    "You are a metadata extraction engine for an AI coaching system. "
    "Your job is to analyze a coach's generated output and extract "
    "structured metadata for the state management system.\n\n"
    "You are precise, exhaustive, and literal. Extract exactly what's "
    "in the text — do not infer or hallucinate.\n\n"
    "## Extraction Tasks\n\n"
    "1. **themes**: List of topic tags (lowercase, underscore-separated) "
    "that the output discusses. Be specific — 'hrv_recovery' not just "
    "'health'.\n\n"
    "2. **structural_fingerprint**: Analyze the output's structure:\n"
    "   - opening_type: One of [lead_with_data, reference_open_thread, "
    "callback_to_prediction, cross_coach_response, "
    "lead_with_environment_variable, lead_with_correction, "
    "lead_with_observation, other]\n"
    "   - paragraph_count: Integer count of distinct paragraphs\n"
    "   - uses_analogy: Boolean — does the output use an analogy?\n"
    "   - analogy_domain: If uses_analogy is true, what domain is the "
    "analogy from? (e.g., 'systems_biology'). Null if no analogy.\n\n"
    "3. **threads_opened**: New observations, concerns, or topics the "
    "coach is flagging for the first time. Each thread needs:\n"
    "   - thread_slug: short identifier (e.g., 'hrv_inflection_watch')\n"
    "   - type: one of [observation, prediction, concern, "
    "recommendation_pending]\n"
    "   - summary: 1-2 sentence description\n"
    "   - tags: relevant domain tags\n\n"
    "4. **threads_referenced**: Existing threads mentioned or built upon. "
    "Identify by topic — the system will match to existing thread records. "
    "Each needs:\n"
    "   - topic: what existing thread is being referenced\n"
    "   - context: how it was referenced (e.g., 'updated with new data')\n\n"
    "5. **predictions_made**: Any claims about future data or outcomes. "
    "Each needs:\n"
    "   - claim_natural: the prediction in natural language\n"
    "   - metric_hint: which MEASURABLE metric would confirm/refute this. "
    "MUST be one of these exact strings (or null if none fits — do NOT "
    "invent prose descriptions): hrv, recovery_score, resting_heart_rate, "
    "sleep_duration_hours, sleep_score, deep_pct, rem_pct, weight_lbs, "
    "total_calories_kcal, total_protein_g, steps, blood_glucose_avg, "
    "blood_glucose_std_dev, body_fat_pct. You may also append _7day_avg, "
    "_14day_avg, or _30day_avg to any of those (e.g. hrv_7day_avg). If "
    "the coach's claim doesn't map cleanly to one of these, return null — "
    "the system will track it as qualitative instead of pretending it can "
    "be machine-verified.\n"
    "   - timeframe_hint: when the prediction should be evaluable\n"
    "   - confidence_stated: any confidence level the coach expressed "
    "(null if not stated)\n\n"
    "6. **decision_classes_used**: Which decision classes appear?\n"
    "   - observational: 'I'm noticing...', 'watching...'\n"
    "   - directional: 'I'd suggest...', 'my recommendation would be...'\n"
    "   - interventional: 'I think it's time to change...'\n\n"
    "7. **anti_pattern_violations**: Check the output against the provided "
    "anti-pattern list. List any forbidden phrases or structural patterns "
    "found.\n\n"
    "8. **observatory_summary**: A condensed version of the coach's output "
    "optimized for a website card (2-3 short paragraphs, ~150-200 words). "
    "Preserve the coach's distinctive voice and key insight but tighten "
    "the prose. Include the most important data point and the key "
    "recommendation. This will be shown on the public observatory page.\n\n"
    "9. **key_recommendation**: Extract the single most actionable "
    "recommendation from the output as a standalone 1-2 sentence string.\n\n"
    "10. **elena_quote**: If the output contains or implies a meta-observation "
    "about what the coach is NOT seeing (cross-domain blindspot), write one "
    "sentence in Elena Voss's literary journalist voice. Third person. "
    "If no natural meta-observation exists, return null.\n\n"
    "## Output Format\n\n"
    "Return ONLY valid JSON with the above fields. No markdown, "
    "no explanation, no preamble."
)


def _build_extraction_message(coach_id, output_text, output_type, voice_spec):
    """Build the user message for the extraction LLM call."""
    parts = [
        f"## Coach: {coach_id}",
        f"## Output Type: {output_type}",
        "",
        "## Coach Output Text",
        "---",
        output_text,
        "---",
        "",
    ]

    # Include anti-pattern lists from voice spec for checking
    anti_patterns = voice_spec.get("anti_pattern_detection", {})
    if anti_patterns:
        parts.append("## Anti-Pattern Checklist")
        phrase_bl = anti_patterns.get("phrase_blacklist", [])
        if phrase_bl:
            parts.append("### Forbidden Phrases")
            for phrase in phrase_bl:
                parts.append(f"  - \"{phrase}\"")
        structural_bl = anti_patterns.get("structural_blacklist", [])
        if structural_bl:
            parts.append("### Forbidden Structural Patterns")
            for pattern in structural_bl:
                parts.append(f"  - \"{pattern}\"")
        parts.append("")

    parts.append(
        "Extract all metadata from the coach output above. "
        "Return ONLY valid JSON with fields: themes, structural_fingerprint, "
        "threads_opened, threads_referenced, predictions_made, "
        "decision_classes_used, anti_pattern_violations."
    )

    return "\n".join(parts)


# ══════════════════════════════════════════════════════════════════════════════
# STATE WRITES
# ══════════════════════════════════════════════════════════════════════════════

def _write_output_record(coach_id, date, output_type, output_text, extraction):
    """Write the OUTPUT# record with full content and extracted metadata."""
    word_count = len(output_text.split())
    now_iso = datetime.now(timezone.utc).isoformat()

    item = {
        "pk": f"COACH#{coach_id}",
        "sk": f"OUTPUT#{date}#{output_type}",
        "content": output_text,
        "themes": extraction.get("themes", []),
        "structural_fingerprint": extraction.get("structural_fingerprint", {}),
        "predictions_made": extraction.get("predictions_made", []),
        "threads_referenced": [t.get("topic", "") for t in extraction.get("threads_referenced", [])],
        "threads_opened": [t.get("thread_slug", "") for t in extraction.get("threads_opened", [])],
        "decision_classes": extraction.get("decision_classes_used", []),
        "anti_pattern_violations": extraction.get("anti_pattern_violations", []),
        "observatory_summary": extraction.get("observatory_summary"),
        "key_recommendation": extraction.get("key_recommendation"),
        "elena_quote": extraction.get("elena_quote"),
        "word_count": word_count,
        "created_at": now_iso,
    }

    success = _put_item(item)
    if success:
        logger.info(
            "Wrote OUTPUT# for %s — %d words, %d themes, %d threads opened",
            coach_id, word_count,
            len(extraction.get("themes", [])),
            len(extraction.get("threads_opened", [])),
        )
    return success


def _update_voice_state(coach_id, extraction):
    """Update VOICE#state with latest opening type and flag overused patterns."""
    coach_pk = f"COACH#{coach_id}"
    current = _get_item(coach_pk, "VOICE#state")

    fingerprint = extraction.get("structural_fingerprint", {})
    opening_type = fingerprint.get("opening_type", "other")

    if current:
        recent_openings = current.get("recent_openings", [])
    else:
        recent_openings = []

    # Append latest opening and trim to max
    recent_openings.append(opening_type)
    recent_openings = recent_openings[-MAX_RECENT_OPENINGS:]

    # Detect overused patterns — check last STALENESS_WINDOW entries
    overused_patterns = []
    recent_window = recent_openings[-STALENESS_WINDOW:]
    if len(recent_window) >= STALENESS_THRESHOLD:
        from collections import Counter
        counts = Counter(recent_window)
        for pattern, count in counts.items():
            if count >= STALENESS_THRESHOLD:
                overused_patterns.append(f"opening_with_{pattern}")

    # Preserve existing signature patterns and anti-patterns
    signature_patterns = (
        current.get("signature_patterns_to_reinforce", []) if current else []
    )
    anti_patterns = (
        current.get("anti_patterns", []) if current else []
    )

    # Add any new anti-pattern violations detected
    violations = extraction.get("anti_pattern_violations", [])
    if violations:
        logger.warning(
            "Anti-pattern violations detected for %s: %s", coach_id, violations
        )

    item = {
        "pk": coach_pk,
        "sk": "VOICE#state",
        "recent_openings": recent_openings,
        "overused_patterns": overused_patterns,
        "signature_patterns_to_reinforce": signature_patterns,
        "anti_patterns": anti_patterns,
        "last_violations": violations,
        "last_updated": datetime.now(timezone.utc).isoformat(),
    }

    success = _put_item(item)
    if success:
        logger.info(
            "Updated VOICE#state for %s — opening: %s, overused: %s",
            coach_id, opening_type, overused_patterns,
        )
    return success


def _create_thread_records(coach_id, date, threads_opened):
    """Create new THREAD# records for threads the coach opened."""
    now_iso = datetime.now(timezone.utc).isoformat()
    created = 0

    for thread in threads_opened:
        slug = thread.get("thread_slug", "unnamed")
        # Sanitize slug — lowercase, underscores only
        slug = slug.lower().replace(" ", "_").replace("-", "_")

        item = {
            "pk": f"COACH#{coach_id}",
            "sk": f"THREAD#{date}#{slug}",
            "status": "open",
            "type": thread.get("type", "observation"),
            "summary": thread.get("summary", ""),
            "opened_date": date,
            "last_referenced": date,
            "reference_count": 1,
            "related_predictions": [],
            "expected_resolution": "Data-dependent",
            "tags": thread.get("tags", []),
            "created_at": now_iso,
        }

        if _put_item(item):
            created += 1

    logger.info("Created %d new THREAD# records for %s", created, coach_id)
    return created


def _update_referenced_threads(coach_id, date, threads_referenced):
    """Update existing THREAD# records for threads the coach referenced.

    Bumps reference_count and updates last_referenced. Uses a best-effort
    topic match — queries all threads and matches by topic keyword.
    """
    if not threads_referenced:
        return 0

    coach_pk = f"COACH#{coach_id}"
    all_threads = _query_begins_with(coach_pk, "THREAD#")
    updated = 0

    for ref in threads_referenced:
        topic = ref.get("topic", "").lower()
        if not topic:
            continue

        # Find matching thread by keyword overlap
        for thread in all_threads:
            thread_summary = thread.get("summary", "").lower()
            thread_slug = thread.get("sk", "").lower()
            thread_tags = [t.lower() for t in thread.get("tags", [])]

            # Match if topic keywords appear in the thread's summary, slug, or tags
            topic_words = set(topic.split())
            match = False
            for word in topic_words:
                if len(word) < 3:
                    continue
                if word in thread_summary or word in thread_slug:
                    match = True
                    break
                if any(word in tag for tag in thread_tags):
                    match = True
                    break

            if match:
                # Update via DynamoDB update expression
                try:
                    table.update_item(
                        Key={"pk": coach_pk, "sk": thread["sk"]},
                        UpdateExpression=(
                            "SET last_referenced = :lr, "
                            "reference_count = if_not_exists(reference_count, :zero) + :one"
                        ),
                        ExpressionAttributeValues=_float_to_decimal({
                            ":lr": date,
                            ":zero": 0,
                            ":one": 1,
                        }),
                    )
                    updated += 1
                    logger.debug(
                        "Updated thread %s for reference to '%s'", thread["sk"], topic
                    )
                except Exception as e:
                    logger.warning("Failed to update thread %s: %s", thread.get("sk"), e)
                break  # Only update the first matching thread per reference

    logger.info("Updated %d existing THREAD# records for %s", updated, coach_id)
    return updated


def _build_reasoning_trace(coach_id, date, output_type, extraction):
    """Build a reasoning trace record from the extraction results."""
    now_iso = datetime.now(timezone.utc).isoformat()

    # Build recommendations from threads opened + predictions
    recommendations = []
    for thread in extraction.get("threads_opened", []):
        if thread.get("type") in ("recommendation_pending", "concern"):
            recommendations.append(thread.get("summary", ""))

    # Primary drivers from themes
    themes = extraction.get("themes", [])

    # Predictions
    predictions = [
        p.get("claim_natural", "") for p in extraction.get("predictions_made", [])
    ]

    # Cross-coach inputs — extracted from threads_referenced that mention other coaches
    cross_coach_inputs = []
    for ref in extraction.get("threads_referenced", []):
        topic = ref.get("topic", "")
        context = ref.get("context", "")
        if any(
            kw in topic.lower() or kw in context.lower()
            for kw in ["coach", "training", "nutrition", "mind", "glucose", "labs"]
        ):
            cross_coach_inputs.append(f"{topic}: {context}")

    # Thread status summary
    threads_status = []
    for t in extraction.get("threads_opened", []):
        threads_status.append({
            "thread": t.get("thread_slug", ""),
            "action": "opened",
            "type": t.get("type", "observation"),
        })
    for t in extraction.get("threads_referenced", []):
        threads_status.append({
            "thread": t.get("topic", ""),
            "action": "referenced",
        })

    trace = {
        "pk": f"COACH#{coach_id}",
        "sk": f"TRACE#{date}#{output_type}",
        "recommendations_made": recommendations,
        "primary_drivers": themes[:5],  # Top 5 themes as primary drivers
        "counterfactuals_considered": [],  # Populated if extraction detects them
        "decision_classes_used": extraction.get("decision_classes_used", []),
        "cross_coach_inputs_used": cross_coach_inputs,
        "predictions_made": predictions,
        "threads_status": threads_status,
        "anti_pattern_violations": extraction.get("anti_pattern_violations", []),
        "created_at": now_iso,
    }

    return trace


# ══════════════════════════════════════════════════════════════════════════════
# DEFAULT EXTRACTION
# ══════════════════════════════════════════════════════════════════════════════

def _build_default_extraction(output_text):
    """Build a minimal extraction when the LLM call fails.

    Better than nothing — captures basic structural info without AI analysis.
    """
    paragraphs = [p.strip() for p in output_text.split("\n\n") if p.strip()]

    return {
        "themes": [],
        "structural_fingerprint": {
            "opening_type": "other",
            "paragraph_count": len(paragraphs),
            "uses_analogy": False,
            "analogy_domain": None,
        },
        "threads_opened": [],
        "threads_referenced": [],
        "predictions_made": [],
        "decision_classes_used": ["observational"],
        "anti_pattern_violations": [],
        "_fallback": True,
    }


# ══════════════════════════════════════════════════════════════════════════════
# HANDLER
# ══════════════════════════════════════════════════════════════════════════════

def lambda_handler(event, context):
    """Extract metadata from a coach's generated output and update state.

    Required event fields:
      - coach_id: str — e.g. "sleep_coach"
      - output_text: str — the full generated output text
      - output_type: str — e.g. "weekly_email", "daily_brief_section"
      - generation_date: str — YYYY-MM-DD format

    Returns the reasoning trace record.
    """
    # Validate required fields
    coach_id = event.get("coach_id")
    output_text = event.get("output_text")
    output_type = event.get("output_type", "weekly_email")
    generation_date = event.get("generation_date")

    if not coach_id:
        raise ValueError("Missing required field: coach_id")
    if not output_text:
        raise ValueError("Missing required field: output_text")
    if not generation_date:
        generation_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        logger.warning("No generation_date provided — defaulting to %s", generation_date)

    logger.info(
        "Starting state update for %s — output_type: %s, date: %s, text_length: %d",
        coach_id, output_type, generation_date, len(output_text),
    )

    # Load voice spec from S3 for anti-pattern checking
    voice_spec = _load_voice_spec(coach_id)

    # Call Haiku to extract metadata
    user_message = _build_extraction_message(coach_id, output_text, output_type, voice_spec)

    try:
        extraction = _call_haiku(
            system=EXTRACTION_SYSTEM_PROMPT,
            user_message=user_message,
            max_tokens=1500,
            temperature=0.1,
        )

        # Validate we got a dict
        if not isinstance(extraction, dict):
            logger.warning(
                "LLM returned non-dict extraction for %s — using default", coach_id
            )
            extraction = _build_default_extraction(output_text)
    except Exception as e:
        logger.error("LLM extraction failed for %s: %s — using default", coach_id, e)
        extraction = _build_default_extraction(output_text)

    logger.info(
        "Extraction complete for %s — %d themes, %d threads opened, %d predictions",
        coach_id,
        len(extraction.get("themes", [])),
        len(extraction.get("threads_opened", [])),
        len(extraction.get("predictions_made", [])),
    )

    # Write state updates
    # 1. OUTPUT# record
    _write_output_record(coach_id, generation_date, output_type, output_text, extraction)

    # 2. VOICE#state update
    _update_voice_state(coach_id, extraction)

    # 3. New THREAD# records
    threads_opened = extraction.get("threads_opened", [])
    if threads_opened:
        _create_thread_records(coach_id, generation_date, threads_opened)

    # 4. Update referenced THREAD# records
    threads_referenced = extraction.get("threads_referenced", [])
    if threads_referenced:
        _update_referenced_threads(coach_id, generation_date, threads_referenced)

    # 5. Build and write reasoning trace
    trace = _build_reasoning_trace(coach_id, generation_date, output_type, extraction)
    _put_item(trace)
    logger.info("Wrote TRACE# record for %s/%s/%s", coach_id, generation_date, output_type)

    # 6. Create formal PREDICTION# records (Phase 4B)
    predictions_made = extraction.get("predictions_made", [])
    for pred in predictions_made:
        claim = pred.get("claim_natural", "")
        if not claim:
            continue
        raw_metric_hint = pred.get("metric_hint", "") or ""
        # P5.7 part 2 (v7.16.0): normalize against MEASURABLE_METRICS. The
        # extractor's updated system prompt asks for allowlisted keys, but
        # prior coach outputs + LLM drift still produce prose. Normalize once
        # at the write boundary so the evaluator can resolve them — or fall
        # back to qualitative to avoid daily "no data" inconclusive churn.
        metric_hint = _normalize_metric_hint(raw_metric_hint) or ""
        if raw_metric_hint and not metric_hint:
            logger.info(
                "Prediction metric_hint %r did not normalize to MEASURABLE_METRICS — "
                "marking qualitative for coach=%s", raw_metric_hint, coach_id,
            )
        timeframe_hint = pred.get("timeframe_hint", "")
        confidence_stated = pred.get("confidence_stated")

        # Build a slug-based prediction ID
        import re
        slug = re.sub(r"[^a-z0-9]+", "_", claim.lower()[:40]).strip("_")
        pred_id = f"pred_{generation_date.replace('-', '')}_{slug}"

        # Map timeframe hint to evaluation window days
        window_days = 14  # default
        if timeframe_hint:
            tf = timeframe_hint.lower()
            if "week" in tf:
                try:
                    n = int(re.search(r"(\d+)", tf).group(1))
                    window_days = n * 7
                except (AttributeError, ValueError):
                    window_days = 14
            elif "month" in tf:
                window_days = 30
            elif "day" in tf:
                try:
                    n = int(re.search(r"(\d+)", tf).group(1))
                    window_days = n
                except (AttributeError, ValueError):
                    window_days = 14

        # Determine subdomain from metric hint
        subdomain = "general"
        if metric_hint:
            mh = metric_hint.lower()
            for sd_key in ["sleep", "hrv", "recovery", "weight", "calories", "protein",
                           "glucose", "training", "mood", "stress"]:
                if sd_key in mh:
                    subdomain = sd_key
                    break

        pred_record = {
            "pk": f"COACH#{coach_id}",
            "sk": f"PREDICTION#{pred_id}",
            "prediction_id": pred_id,
            "coach_id": coach_id,
            "created_date": generation_date,
            "claim_natural": claim,
            "evaluation": {
                "type": "machine" if metric_hint else "qualitative",
                "metric": metric_hint or None,
                "condition": "gt",  # default — may need refinement
                "threshold": None,  # extracted from claim if possible
                "evaluation_window_days": window_days,
                "null_hypothesis": None,
                "beats_null_if": None,
            },
            "confidence": _parse_confidence(confidence_stated),
            "subdomain": subdomain,
            "confounders_noted": [],
            "status": "pending",
            "outcome": None,
            "outcome_date": None,
            "outcome_notes": None,
            "decision_class": extraction.get("decision_classes_used", ["observational"])[0] if extraction.get("decision_classes_used") else "observational",
            "surfaced_to_subject": True,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        _put_item(pred_record)
        logger.info("Created PREDICTION# %s for %s", pred_id, coach_id)

    # Return the trace (with Decimals converted for JSON serialization)
    return _decimal_to_float(trace)
