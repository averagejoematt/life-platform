"""
coach_history_summarizer.py — Coach Intelligence: Weekly History Compressor

QUALITY-CRITICAL — Weekly Lambda that compresses each coach's output history
into a ~500-token compressed state. The compressed state must be sufficient
for the orchestrator to maintain continuity across weeks.

For each coach:
  1. Query all OUTPUT# records (most recent first, limit 20)
  2. Query all open THREAD# records (status=open)
  3. Query active PREDICTION# records (status in pending/confirming/confirmed)
  4. Read CONFIDENCE# records for all subdomains
  5. Read current RELATIONSHIP#state
  6. Read current VOICE#state
  7. Call Haiku to compress into ~500-token summary
  8. Write to COACH#{coach_id} / COMPRESSED#latest

DynamoDB patterns:
  PK=COACH#{coach_id}  SK=OUTPUT#*
  PK=COACH#{coach_id}  SK=THREAD#*
  PK=COACH#{coach_id}  SK=PREDICTION#*
  PK=COACH#{coach_id}  SK=CONFIDENCE#*
  PK=COACH#{coach_id}  SK=RELATIONSHIP#state
  PK=COACH#{coach_id}  SK=VOICE#state
  PK=COACH#{coach_id}  SK=COMPRESSED#latest  (output)

Schedule: Weekly (Sunday 6:00 AM PT / 14:00 UTC via EventBridge)

v1.0.0 — 2026-04-06 (Coach Intelligence)
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
    logger = get_logger("coach-history-summarizer")
except ImportError:
    logger = logging.getLogger("coach-history-summarizer")
    logger.setLevel(logging.INFO)

# ══════════════════════════════════════════════════════════════════════════════
# CONFIGURATION
# ══════════════════════════════════════════════════════════════════════════════

REGION = os.environ.get("AWS_REGION", "us-west-2")
TABLE_NAME = os.environ.get("TABLE_NAME", "life-platform")
S3_BUCKET = os.environ.get("S3_BUCKET", "matthew-life-platform")

ANTHROPIC_API = "https://api.anthropic.com/v1/messages"
AI_MODEL_HAIKU = os.environ.get("AI_MODEL_HAIKU", "claude-haiku-4-5-20251001")

# All coach IDs in the system
ALL_COACH_IDS = [
    "sleep_coach", "nutrition_coach", "training_coach", "mind_coach",
    "physical_coach", "glucose_coach", "labs_coach", "explorer_coach",
]

# Coach display names and domains — used in compressed state output
COACH_META = {
    "sleep_coach":     {"display_name": "Dr. Lisa Park",       "domain": "sleep_science"},
    "nutrition_coach": {"display_name": "Elena Vasquez",        "domain": "nutrition"},
    "training_coach":  {"display_name": "Marcus Chen",          "domain": "training"},
    "mind_coach":      {"display_name": "Dr. James Okafor",    "domain": "mind_performance"},
    "physical_coach":  {"display_name": "Dr. Sarah Kim",       "domain": "physical_health"},
    "glucose_coach":   {"display_name": "Dr. Anil Mehta",      "domain": "glucose_metabolism"},
    "labs_coach":      {"display_name": "Dr. Rachel Johansson", "domain": "biomarkers"},
    "explorer_coach":  {"display_name": "Jordan Rivera",        "domain": "cross_domain"},
}

# Maximum OUTPUT# records to fetch per coach
MAX_OUTPUT_RECORDS = 20

# Prediction statuses considered "active"
ACTIVE_PREDICTION_STATUSES = {"pending", "confirming", "confirmed"}

# CloudWatch metrics
_cw = boto3.client("cloudwatch", region_name=REGION)
_LAMBDA_NAME = os.environ.get("AWS_LAMBDA_FUNCTION_NAME", "coach-history-summarizer")
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

def _call_haiku(system, user_message, max_tokens=1500, temperature=0.2):
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
            # If we have a limit and have enough items, stop paginating
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


# ══════════════════════════════════════════════════════════════════════════════
# DATA GATHERING
# ══════════════════════════════════════════════════════════════════════════════

def _gather_coach_state(coach_id):
    """Gather all state for a single coach from DynamoDB.

    Returns a dict with all the raw data needed for compression:
      - outputs: recent OUTPUT# records (most recent first, limit 20)
      - open_threads: THREAD# records with status=open
      - active_predictions: PREDICTION# with status in pending/confirming/confirmed
      - confidence_records: all CONFIDENCE# records
      - relationship_state: RELATIONSHIP#state
      - voice_state: VOICE#state
    """
    coach_pk = f"COACH#{coach_id}"

    # 1. Query OUTPUT# records — most recent first (ScanIndexForward=False)
    outputs = _query_begins_with(
        coach_pk, "OUTPUT#",
        scan_forward=False,
        limit=MAX_OUTPUT_RECORDS,
    )
    logger.info("Fetched %d OUTPUT# records for %s", len(outputs), coach_id)

    # 2. Query all THREAD# records, filter to status=open
    all_threads = _query_begins_with(coach_pk, "THREAD#")
    open_threads = [t for t in all_threads if t.get("status") == "open"]
    logger.info(
        "Fetched %d THREAD# records for %s (%d open)",
        len(all_threads), coach_id, len(open_threads),
    )

    # 3. Query all PREDICTION# records, filter to active statuses
    all_predictions = _query_begins_with(coach_pk, "PREDICTION#")
    active_predictions = [
        p for p in all_predictions
        if p.get("status") in ACTIVE_PREDICTION_STATUSES
    ]
    logger.info(
        "Fetched %d PREDICTION# records for %s (%d active)",
        len(all_predictions), coach_id, len(active_predictions),
    )

    # 4. Query all CONFIDENCE# records
    confidence_records = _query_begins_with(coach_pk, "CONFIDENCE#")
    logger.info("Fetched %d CONFIDENCE# records for %s", len(confidence_records), coach_id)

    # 5. Read RELATIONSHIP#state
    relationship_state = _get_item(coach_pk, "RELATIONSHIP#state")

    # 6. Read VOICE#state
    voice_state = _get_item(coach_pk, "VOICE#state")

    return {
        "outputs": outputs,
        "open_threads": open_threads,
        "active_predictions": active_predictions,
        "confidence_records": confidence_records,
        "relationship_state": relationship_state,
        "voice_state": voice_state,
    }


# ══════════════════════════════════════════════════════════════════════════════
# COMPRESSION PROMPT
# ══════════════════════════════════════════════════════════════════════════════

COMPRESSION_SYSTEM_PROMPT = (
    "You are a compression engine for an AI coaching system. Your job is to "
    "compress a coach's entire history into a ~500-token summary that another "
    "LLM can use to generate output consistent with everything this coach has "
    "ever said.\n\n"
    "## What to PRESERVE (critical for continuity):\n"
    "- Key analytical positions the coach has taken\n"
    "- Active threads and their current status\n"
    "- Relationship evolution — how the coach relates to Matthew specifically\n"
    "- Recent themes from the last 3-5 outputs\n"
    "- Any corrections or revisions to prior thinking\n"
    "- Prediction track record (confirmed/refuted/pending counts)\n"
    "- Voice pattern observations (overused openings, signature patterns)\n"
    "- Standing recommendations that remain active\n"
    "- Key concerns the coach is currently monitoring\n\n"
    "## What to NOT preserve (saves tokens):\n"
    "- Specific daily data values (e.g., 'HRV was 45 on Tuesday')\n"
    "- Full text of prior outputs\n"
    "- Implementation details of recommendations\n"
    "- Resolved threads or expired predictions\n"
    "- Redundant information already captured in structured fields\n\n"
    "## Output Format:\n"
    "Return ONLY valid JSON matching the schema below. No markdown, no "
    "explanation, no preamble.\n\n"
    "Schema:\n"
    "{\n"
    '  "coach_id": "string",\n'
    '  "display_name": "string",\n'
    '  "domain": "string",\n'
    '  "summary": "~500-token compressed narrative of history, positions, '
    'and relationship",\n'
    '  "key_concerns": ["current top concerns"],\n'
    '  "key_recommendations": ["standing recommendations"],\n'
    '  "active_threads": [{"id": "thread_id", "summary": "brief summary"}],\n'
    '  "active_predictions": [{"id": "pred_id", "claim": "claim text", '
    '"status": "pending|confirming|confirmed"}],\n'
    '  "confidence_state": {"subdomain": 0.5},\n'
    '  "recent_themes": ["themes from last 3-5 outputs"],\n'
    '  "positions_taken": ["key analytical positions"],\n'
    '  "corrections_made": ["any revisions to prior thinking"],\n'
    '  "relationship_notes": "how the coach relates to Matthew specifically",\n'
    '  "last_output_date": "YYYY-MM-DD",\n'
    '  "compressed_at": "ISO timestamp"\n'
    "}\n"
)


def _build_compression_message(coach_id, state):
    """Build the user message for the compression LLM call.

    Assembles all gathered state into a structured prompt that gives the
    LLM everything it needs to produce a high-quality compressed summary.
    """
    meta = COACH_META.get(coach_id, {"display_name": coach_id, "domain": "unknown"})
    parts = [
        f"## Coach: {coach_id}",
        f"## Display Name: {meta['display_name']}",
        f"## Domain: {meta['domain']}",
        "",
    ]

    # Output history — include themes, structural fingerprint, and key content signals
    outputs = state.get("outputs", [])
    if outputs:
        parts.append(f"## Recent Outputs ({len(outputs)} records, most recent first)")
        for i, output in enumerate(outputs):
            date = output.get("sk", "").replace("OUTPUT#", "").split("#")[0] if output.get("sk") else "unknown"
            themes = output.get("themes", [])
            threads_opened = output.get("threads_opened", [])
            threads_ref = output.get("threads_referenced", [])
            violations = output.get("anti_pattern_violations", [])
            decision_classes = output.get("decision_classes", [])
            word_count = output.get("word_count", 0)

            parts.append(f"\n### Output {i + 1} — {date}")
            parts.append(f"  Themes: {', '.join(themes) if themes else 'none'}")
            parts.append(f"  Decision classes: {', '.join(decision_classes) if decision_classes else 'none'}")
            parts.append(f"  Threads opened: {', '.join(threads_opened) if threads_opened else 'none'}")
            parts.append(f"  Threads referenced: {', '.join(threads_ref) if threads_ref else 'none'}")
            parts.append(f"  Word count: {word_count}")
            if violations:
                parts.append(f"  Anti-pattern violations: {', '.join(violations)}")

            # Include a truncated content preview for the most recent 5 outputs
            content = output.get("content", "")
            if i < 5 and content:
                preview = content[:300] + "..." if len(content) > 300 else content
                parts.append(f"  Content preview: {preview}")

            # Include structural fingerprint
            fingerprint = output.get("structural_fingerprint", {})
            if fingerprint:
                opening = fingerprint.get("opening_type", "unknown")
                analogy = fingerprint.get("uses_analogy", False)
                parts.append(f"  Opening type: {opening}, uses_analogy: {analogy}")

            # Include predictions made in this output
            predictions_in_output = output.get("predictions_made", [])
            if predictions_in_output:
                parts.append(f"  Predictions made: {json.dumps(predictions_in_output)}")
        parts.append("")
    else:
        parts.append("## Recent Outputs: NONE (new coach, no history)")
        parts.append("")

    # Open threads
    open_threads = state.get("open_threads", [])
    if open_threads:
        parts.append(f"## Open Threads ({len(open_threads)})")
        for thread in open_threads:
            slug = thread.get("sk", "").replace("THREAD#", "")
            summary = thread.get("summary", "no summary")
            thread_type = thread.get("type", "observation")
            ref_count = thread.get("reference_count", 0)
            last_ref = thread.get("last_referenced", "unknown")
            parts.append(
                f"  - [{thread_type}] {slug}: {summary} "
                f"(refs={ref_count}, last_ref={last_ref})"
            )
        parts.append("")
    else:
        parts.append("## Open Threads: NONE")
        parts.append("")

    # Active predictions
    active_preds = state.get("active_predictions", [])
    if active_preds:
        parts.append(f"## Active Predictions ({len(active_preds)})")
        for pred in active_preds:
            pred_id = pred.get("prediction_id", pred.get("sk", "").replace("PREDICTION#", ""))
            claim = pred.get("claim_natural", "no claim")
            status = pred.get("status", "pending")
            confidence = pred.get("confidence", 0.5)
            subdomain = pred.get("subdomain", "general")
            parts.append(
                f"  - [{status}] {pred_id}: {claim} "
                f"(confidence={confidence}, subdomain={subdomain})"
            )
        parts.append("")
    else:
        parts.append("## Active Predictions: NONE")
        parts.append("")

    # Confidence state
    confidence_records = state.get("confidence_records", [])
    if confidence_records:
        parts.append("## Confidence State (Bayesian)")
        for conf in confidence_records:
            subdomain = conf.get("subdomain", conf.get("sk", "").replace("CONFIDENCE#", ""))
            mean = conf.get("mean_confidence", 0.5)
            sample_size = conf.get("sample_size", 0)
            parts.append(f"  - {subdomain}: {mean:.3f} (n={sample_size})")
        parts.append("")
    else:
        parts.append("## Confidence State: NONE (uninformed prior)")
        parts.append("")

    # Relationship state
    relationship = state.get("relationship_state")
    if relationship:
        parts.append("## Relationship State")
        # Remove pk/sk from display
        rel_display = {k: v for k, v in relationship.items() if k not in ("pk", "sk")}
        parts.append(f"  {json.dumps(rel_display, indent=2)}")
        parts.append("")
    else:
        parts.append("## Relationship State: NONE (new relationship)")
        parts.append("")

    # Voice state
    voice = state.get("voice_state")
    if voice:
        parts.append("## Voice State")
        recent_openings = voice.get("recent_openings", [])
        overused = voice.get("overused_patterns", [])
        signature = voice.get("signature_patterns_to_reinforce", [])
        anti_patterns = voice.get("anti_patterns", [])
        last_violations = voice.get("last_violations", [])
        parts.append(f"  Recent openings: {recent_openings}")
        if overused:
            parts.append(f"  Overused patterns: {overused}")
        if signature:
            parts.append(f"  Signature patterns: {signature}")
        if anti_patterns:
            parts.append(f"  Anti-patterns: {anti_patterns}")
        if last_violations:
            parts.append(f"  Last violations: {last_violations}")
        parts.append("")
    else:
        parts.append("## Voice State: NONE")
        parts.append("")

    parts.append(
        "Compress all the above into a ~500-token summary following the JSON "
        "schema exactly. The summary field should be a dense narrative that "
        "captures the coach's analytical identity, relationship with Matthew, "
        "and continuity-critical information. Return ONLY valid JSON."
    )

    return "\n".join(parts)


# ══════════════════════════════════════════════════════════════════════════════
# COMPRESSION LOGIC
# ══════════════════════════════════════════════════════════════════════════════

def _build_fallback_compressed_state(coach_id, state):
    """Build a minimal compressed state when the LLM call fails.

    Better than nothing — preserves structural data without AI narrative.
    """
    meta = COACH_META.get(coach_id, {"display_name": coach_id, "domain": "unknown"})
    now_iso = datetime.now(timezone.utc).isoformat()

    # Derive last output date from outputs
    outputs = state.get("outputs", [])
    last_output_date = None
    if outputs:
        for output in outputs:
            sk = output.get("sk", "")
            if sk.startswith("OUTPUT#"):
                date_part = sk.replace("OUTPUT#", "").split("#")[0]
                if date_part:
                    last_output_date = date_part
                    break

    # Build confidence state from records
    confidence_state = {}
    for conf in state.get("confidence_records", []):
        subdomain = conf.get("subdomain", conf.get("sk", "").replace("CONFIDENCE#", ""))
        mean = conf.get("mean_confidence", 0.5)
        confidence_state[subdomain] = round(mean, 3)

    # Extract recent themes from last 5 outputs
    recent_themes = []
    for output in outputs[:5]:
        for theme in output.get("themes", []):
            if theme not in recent_themes:
                recent_themes.append(theme)
                if len(recent_themes) >= 10:
                    break
        if len(recent_themes) >= 10:
            break

    return {
        "coach_id": coach_id,
        "display_name": meta["display_name"],
        "domain": meta["domain"],
        "summary": f"[FALLBACK — LLM compression failed] Coach {meta['display_name']} "
                   f"has {len(outputs)} outputs, "
                   f"{len(state.get('open_threads', []))} open threads, "
                   f"{len(state.get('active_predictions', []))} active predictions. "
                   f"Manual review recommended.",
        "key_concerns": [],
        "key_recommendations": [],
        "active_threads": [
            {"id": t.get("sk", "").replace("THREAD#", ""), "summary": t.get("summary", "")}
            for t in state.get("open_threads", [])[:5]
        ],
        "active_predictions": [
            {
                "id": p.get("prediction_id", p.get("sk", "").replace("PREDICTION#", "")),
                "claim": p.get("claim_natural", ""),
                "status": p.get("status", "pending"),
            }
            for p in state.get("active_predictions", [])[:5]
        ],
        "confidence_state": confidence_state,
        "recent_themes": recent_themes[:10],
        "positions_taken": [],
        "corrections_made": [],
        "relationship_notes": "",
        "last_output_date": last_output_date,
        "compressed_at": now_iso,
        "_fallback": True,
    }


def _compress_coach(coach_id, state):
    """Compress a single coach's history via Haiku LLM call.

    Returns the compressed state dict ready for DynamoDB write.
    Falls back to structural-only compression if the LLM call fails.
    """
    meta = COACH_META.get(coach_id, {"display_name": coach_id, "domain": "unknown"})
    now_iso = datetime.now(timezone.utc).isoformat()

    # Build the compression prompt
    user_message = _build_compression_message(coach_id, state)

    try:
        result = _call_haiku(
            system=COMPRESSION_SYSTEM_PROMPT,
            user_message=user_message,
            max_tokens=1500,
            temperature=0.2,
        )

        if not isinstance(result, dict):
            logger.warning(
                "LLM returned non-dict for %s compression — using fallback", coach_id
            )
            return _build_fallback_compressed_state(coach_id, state)

        # Ensure required fields are present with defaults
        result.setdefault("coach_id", coach_id)
        result.setdefault("display_name", meta["display_name"])
        result.setdefault("domain", meta["domain"])
        result.setdefault("summary", "")
        result.setdefault("key_concerns", [])
        result.setdefault("key_recommendations", [])
        result.setdefault("active_threads", [])
        result.setdefault("active_predictions", [])
        result.setdefault("confidence_state", {})
        result.setdefault("recent_themes", [])
        result.setdefault("positions_taken", [])
        result.setdefault("corrections_made", [])
        result.setdefault("relationship_notes", "")
        result.setdefault("last_output_date", None)
        result["compressed_at"] = now_iso

        # If LLM didn't populate confidence_state, derive from records
        if not result["confidence_state"]:
            for conf in state.get("confidence_records", []):
                subdomain = conf.get("subdomain", conf.get("sk", "").replace("CONFIDENCE#", ""))
                mean = conf.get("mean_confidence", 0.5)
                result["confidence_state"][subdomain] = round(mean, 3)

        # If LLM didn't populate last_output_date, derive from outputs
        if not result["last_output_date"]:
            outputs = state.get("outputs", [])
            if outputs:
                sk = outputs[0].get("sk", "")
                if sk.startswith("OUTPUT#"):
                    result["last_output_date"] = sk.replace("OUTPUT#", "").split("#")[0]

        logger.info(
            "Compressed %s — summary=%d chars, concerns=%d, recs=%d, threads=%d, preds=%d",
            coach_id,
            len(result.get("summary", "")),
            len(result.get("key_concerns", [])),
            len(result.get("key_recommendations", [])),
            len(result.get("active_threads", [])),
            len(result.get("active_predictions", [])),
        )
        return result

    except Exception as e:
        logger.error("LLM compression failed for %s: %s — using fallback", coach_id, e)
        return _build_fallback_compressed_state(coach_id, state)


def _write_compressed_state(coach_id, compressed):
    """Write the compressed state to DynamoDB at COMPRESSED#latest."""
    item = {
        "pk": f"COACH#{coach_id}",
        "sk": "COMPRESSED#latest",
        **compressed,
    }
    success = _put_item(item)
    if success:
        logger.info("Wrote COMPRESSED#latest for %s", coach_id)
    else:
        logger.error("Failed to write COMPRESSED#latest for %s", coach_id)
    return success


# ══════════════════════════════════════════════════════════════════════════════
# HANDLER
# ══════════════════════════════════════════════════════════════════════════════

def lambda_handler(event, context):
    """Weekly history compression for coach intelligence system.

    Optional event fields:
      - coach_ids: list[str] — specific coaches to compress (defaults to all 8)

    Returns a summary of compression results per coach.
    """
    try:
        coach_ids = event.get("coach_ids", ALL_COACH_IDS)
        logger.info(
            "coach-history-summarizer START — compressing %d coaches: %s",
            len(coach_ids), coach_ids,
        )

        results = {}
        errors = []

        for coach_id in coach_ids:
            try:
                logger.info("Compressing coach: %s", coach_id)

                # Gather all state
                state = _gather_coach_state(coach_id)

                # Check if there's any data to compress
                total_records = (
                    len(state.get("outputs", []))
                    + len(state.get("open_threads", []))
                    + len(state.get("active_predictions", []))
                )
                if total_records == 0:
                    logger.info("No data for %s — skipping compression", coach_id)
                    results[coach_id] = {
                        "status": "skipped",
                        "reason": "no data",
                    }
                    continue

                # Compress via LLM
                compressed = _compress_coach(coach_id, state)

                # Write to DynamoDB
                success = _write_compressed_state(coach_id, compressed)

                results[coach_id] = {
                    "status": "success" if success else "write_failed",
                    "summary_length": len(compressed.get("summary", "")),
                    "key_concerns": len(compressed.get("key_concerns", [])),
                    "active_threads": len(compressed.get("active_threads", [])),
                    "active_predictions": len(compressed.get("active_predictions", [])),
                    "is_fallback": compressed.get("_fallback", False),
                }

            except Exception as e:
                logger.error("Failed to compress %s: %s", coach_id, e, exc_info=True)
                errors.append({"coach_id": coach_id, "error": str(e)})
                results[coach_id] = {
                    "status": "error",
                    "error": str(e),
                }

        # Summary
        success_count = sum(1 for r in results.values() if r.get("status") == "success")
        skip_count = sum(1 for r in results.values() if r.get("status") == "skipped")
        error_count = len(errors)

        logger.info(
            "coach-history-summarizer COMPLETE: %d success, %d skipped, %d errors",
            success_count, skip_count, error_count,
        )

        return {
            "statusCode": 200,
            "coaches_processed": len(coach_ids),
            "success": success_count,
            "skipped": skip_count,
            "errors": error_count,
            "results": results,
            "error_details": errors if errors else None,
        }

    except Exception as e:
        logger.error("coach-history-summarizer FAILED: %s", e, exc_info=True)
        return {"statusCode": 500, "error": str(e)}
