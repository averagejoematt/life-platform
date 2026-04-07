"""
coach_ensemble_digest.py — Coach Intelligence: Post-Cycle Ensemble Digest

Runs after all coaches complete a generation cycle. Reads each coach's most
recent OUTPUT# record and COMPRESSED#latest, then calls Haiku to produce a
cross-coach ensemble digest that identifies:

  - Each coach's key concerns, recommendations, and active predictions
  - DISAGREEMENTS between coaches (conflicting recommendations on the same domain)
  - Unanimous agreement flags (suspicious per S-10 — groupthink detection)
  - Topics where coaches have requested team input

DynamoDB writes:
  1. Ensemble digest:       PK=ENSEMBLE#digest         SK=CYCLE#{date}
  2. Active disagreements:  PK=ENSEMBLE#disagreements  SK=ACTIVE#{topic_slug}
  3. Coach compressed state updates (digest_contribution field)

Coach IDs: sleep_coach, nutrition_coach, training_coach, mind_coach,
           physical_coach, glucose_coach, labs_coach, explorer_coach

v1.0.0 — 2026-04-06 (Coach Intelligence)
"""

import json
import logging
import os
import re
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from decimal import Decimal

import boto3

# Structured logger
try:
    from platform_logger import get_logger
    logger = get_logger("coach-ensemble-digest")
except ImportError:
    logger = logging.getLogger("coach-ensemble-digest")
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

# CloudWatch metrics
_cw = boto3.client("cloudwatch", region_name=REGION)
_LAMBDA_NAME = os.environ.get("AWS_LAMBDA_FUNCTION_NAME", "coach-ensemble-digest")
_CW_NAMESPACE = "LifePlatform/AI"

# Backoff delays between retry attempts (seconds)
_BACKOFF_DELAYS = [5, 15, 45]
_MAX_ATTEMPTS = len(_BACKOFF_DELAYS) + 1
_RETRYABLE_CODES = frozenset([429, 500, 502, 503, 504, 529])

# AWS clients
dynamodb = boto3.resource("dynamodb", region_name=REGION)
table = dynamodb.Table(TABLE_NAME)
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


def _slugify(text):
    """Convert a topic string to a URL-safe slug for DynamoDB sort keys."""
    slug = text.lower().strip()
    slug = re.sub(r'[^a-z0-9]+', '_', slug)
    slug = slug.strip('_')
    return slug[:80] if slug else "unnamed"


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

def _call_haiku(system, user_message, max_tokens=2000, temperature=0.2):
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
# COACH DATA GATHERING
# ══════════════════════════════════════════════════════════════════════════════

def _gather_coach_data(coach_ids):
    """Read the most recent OUTPUT# record and COMPRESSED#latest for each coach.

    Returns a dict keyed by coach_id with sub-keys 'output' and 'compressed'.
    Gracefully handles missing coaches — early phases won't have all 8 on the
    new system.
    """
    coach_data = {}

    for coach_id in coach_ids:
        coach_pk = f"COACH#{coach_id}"

        # Most recent OUTPUT# record
        output = _query_latest(coach_pk, "OUTPUT#")

        # Compressed state
        compressed = _get_item(coach_pk, "COMPRESSED#latest")

        if not output and not compressed:
            logger.info(
                "No data found for %s — coach may not be on the new system yet",
                coach_id,
            )
            continue

        coach_data[coach_id] = {
            "output": output,
            "compressed": compressed,
        }

        logger.info(
            "Gathered data for %s — output: %s, compressed: %s",
            coach_id,
            "present" if output else "missing",
            "present" if compressed else "missing",
        )

    return coach_data


# ══════════════════════════════════════════════════════════════════════════════
# ENSEMBLE SYSTEM PROMPT
# ══════════════════════════════════════════════════════════════════════════════

ENSEMBLE_SYSTEM_PROMPT = (
    "You are the Ensemble Analyst for a team of 8 AI health coaches. "
    "Your job is to synthesize all coaches' outputs into a cross-coach "
    "ensemble digest.\n\n"
    "## Your Tasks\n\n"
    "1. **Summarize each coach**: For each coach with data, extract their "
    "key concerns, recommendations, active predictions, confidence state, "
    "and any topics where they want team input.\n\n"
    "2. **Identify DISAGREEMENTS**: Find cases where two or more coaches "
    "give conflicting recommendations about the same domain or issue. "
    "For each disagreement, name the topic, the coaches involved, their "
    "positions, and what data would resolve it.\n\n"
    "3. **Flag UNANIMOUS AGREEMENT**: Per S-10, when all coaches agree "
    "on something, that is SUSPICIOUS — it may indicate groupthink or "
    "a blind spot. Flag any areas of unusual consensus so the user can "
    "apply independent judgment.\n\n"
    "## Important Rules\n\n"
    "- Be precise and literal — do not infer concerns that coaches did not "
    "actually express.\n"
    "- If a coach has no data yet, omit them from coach_summaries entirely.\n"
    "- Disagreements must involve actual conflicting positions, not merely "
    "different domains (sleep_coach talking about sleep and training_coach "
    "talking about training is not a disagreement).\n"
    "- Unanimous flags require 3+ coaches agreeing on the SAME claim or "
    "recommendation.\n\n"
    "## Output Format\n\n"
    "Return ONLY valid JSON with this exact structure:\n"
    "{\n"
    '  "coach_summaries": [\n'
    "    {\n"
    '      "coach_id": "string",\n'
    '      "key_concerns": ["..."],\n'
    '      "key_recommendations": ["..."],\n'
    '      "predictions_active": ["..."],\n'
    '      "confidence_state": {},\n'
    '      "wants_team_input_on": ["..."]\n'
    "    }\n"
    "  ],\n"
    '  "active_disagreements": [\n'
    "    {\n"
    '      "topic": "string",\n'
    '      "coaches": ["coach_a", "coach_b"],\n'
    '      "positions": {"coach_a": "...", "coach_b": "..."},\n'
    '      "status": "unresolved",\n'
    '      "data_needed_to_resolve": "string"\n'
    "    }\n"
    "  ],\n"
    '  "unanimous_flags": ["..."]\n'
    "}\n\n"
    "No markdown wrapping, no explanation, no preamble. ONLY the JSON object."
)


def _build_user_message(coach_data, cycle_date):
    """Build the user message containing all coaches' data for ensemble analysis."""
    parts = [
        f"## Ensemble Digest Cycle: {cycle_date}",
        f"## Coaches with data: {len(coach_data)}/{len(ALL_COACH_IDS)}",
        "",
    ]

    for coach_id, data in coach_data.items():
        parts.append(f"### Coach: {coach_id}")
        parts.append("")

        # Output record
        output = data.get("output")
        if output:
            parts.append("#### Most Recent Output")
            # Include content, themes, decision classes, predictions
            parts.append(f"- Content excerpt: {(output.get('content', ''))[:500]}")
            parts.append(f"- Themes: {json.dumps(output.get('themes', []))}")
            parts.append(f"- Decision classes: {json.dumps(output.get('decision_classes', []))}")
            parts.append(f"- Predictions made: {json.dumps(output.get('predictions_made', []), default=str)}")
            parts.append(f"- Threads opened: {json.dumps(output.get('threads_opened', []))}")
            parts.append(f"- Threads referenced: {json.dumps(output.get('threads_referenced', []))}")
            parts.append(f"- Created at: {output.get('created_at', 'unknown')}")
        else:
            parts.append("#### Most Recent Output: None available")

        parts.append("")

        # Compressed state
        compressed = data.get("compressed")
        if compressed:
            parts.append("#### Compressed State")
            # Filter out pk/sk for cleaner prompt
            filtered = {
                k: v for k, v in compressed.items()
                if k not in ("pk", "sk")
            }
            parts.append(json.dumps(filtered, indent=2, default=str))
        else:
            parts.append("#### Compressed State: None available")

        parts.append("")
        parts.append("---")
        parts.append("")

    parts.append("## Instructions")
    parts.append(
        "Analyze all coaches' data above and produce the ensemble digest JSON. "
        "Focus on cross-coach interactions — where do coaches agree, disagree, "
        "or need input from each other? Return ONLY the JSON object."
    )

    return "\n".join(parts)


# ══════════════════════════════════════════════════════════════════════════════
# DEFAULT DIGEST (FALLBACK)
# ══════════════════════════════════════════════════════════════════════════════

def _build_default_digest(coach_data, cycle_date):
    """Build a minimal digest when the LLM call fails.

    Uses available data to produce a structural-only digest without AI analysis.
    """
    coach_summaries = []
    for coach_id, data in coach_data.items():
        output = data.get("output", {}) or {}
        compressed = data.get("compressed", {}) or {}

        summary = {
            "coach_id": coach_id,
            "key_concerns": compressed.get("key_themes", [])[:3],
            "key_recommendations": [],
            "predictions_active": [],
            "confidence_state": compressed.get("confidence_state", {}),
            "wants_team_input_on": [],
        }

        # Pull predictions from output if available
        preds = output.get("predictions_made", [])
        if isinstance(preds, list):
            summary["predictions_active"] = [
                p.get("claim_natural", str(p)) if isinstance(p, dict) else str(p)
                for p in preds[:3]
            ]

        coach_summaries.append(summary)

    return {
        "coach_summaries": coach_summaries,
        "active_disagreements": [],
        "unanimous_flags": [],
        "_fallback": True,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


# ══════════════════════════════════════════════════════════════════════════════
# WRITE OPERATIONS
# ══════════════════════════════════════════════════════════════════════════════

def _write_digest(digest, cycle_date):
    """Write the ensemble digest to DynamoDB at ENSEMBLE#digest / CYCLE#{date}."""
    item = {
        "pk": "ENSEMBLE#digest",
        "sk": f"CYCLE#{cycle_date}",
        **digest,
    }

    success = _put_item(item)
    if success:
        logger.info(
            "Wrote ensemble digest for CYCLE#%s — %d coach summaries, %d disagreements, %d unanimous flags",
            cycle_date,
            len(digest.get("coach_summaries", [])),
            len(digest.get("active_disagreements", [])),
            len(digest.get("unanimous_flags", [])),
        )
    return success


def _write_disagreements(disagreements, cycle_date):
    """Write or update active disagreement records.

    Each disagreement gets its own record at:
      PK=ENSEMBLE#disagreements  SK=ACTIVE#{topic_slug}

    Existing records are updated with the latest positions; new ones are created.
    """
    written = 0

    for disagreement in disagreements:
        topic = disagreement.get("topic", "unnamed")
        slug = _slugify(topic)
        now_iso = datetime.now(timezone.utc).isoformat()

        # Check if this disagreement already exists
        existing = _get_item("ENSEMBLE#disagreements", f"ACTIVE#{slug}")

        if existing:
            # Update — preserve first_seen, bump cycle count
            item = {
                "pk": "ENSEMBLE#disagreements",
                "sk": f"ACTIVE#{slug}",
                "topic": topic,
                "coaches": disagreement.get("coaches", []),
                "positions": disagreement.get("positions", {}),
                "status": disagreement.get("status", "unresolved"),
                "data_needed_to_resolve": disagreement.get("data_needed_to_resolve", ""),
                "first_seen": existing.get("first_seen", now_iso),
                "last_seen": now_iso,
                "cycle_count": (existing.get("cycle_count", 0) or 0) + 1,
                "last_cycle_date": cycle_date,
            }
        else:
            # New disagreement
            item = {
                "pk": "ENSEMBLE#disagreements",
                "sk": f"ACTIVE#{slug}",
                "topic": topic,
                "coaches": disagreement.get("coaches", []),
                "positions": disagreement.get("positions", {}),
                "status": disagreement.get("status", "unresolved"),
                "data_needed_to_resolve": disagreement.get("data_needed_to_resolve", ""),
                "first_seen": now_iso,
                "last_seen": now_iso,
                "cycle_count": 1,
                "last_cycle_date": cycle_date,
            }

        if _put_item(item):
            written += 1

    logger.info(
        "Wrote %d disagreement records for cycle %s", written, cycle_date
    )
    return written


def _update_coach_compressed_states(digest, coach_data, cycle_date):
    """Update each coach's COMPRESSED#latest with their digest contribution.

    Adds a 'digest_contribution' field summarizing what the ensemble digest
    captured from this coach — enabling each coach to see how they were
    perceived by the ensemble in their next generation cycle.
    """
    summaries_by_id = {}
    for summary in digest.get("coach_summaries", []):
        cid = summary.get("coach_id")
        if cid:
            summaries_by_id[cid] = summary

    updated = 0
    now_iso = datetime.now(timezone.utc).isoformat()

    for coach_id in coach_data:
        coach_pk = f"COACH#{coach_id}"
        compressed = _get_item(coach_pk, "COMPRESSED#latest")

        if not compressed:
            logger.info(
                "No COMPRESSED#latest for %s — skipping digest contribution update",
                coach_id,
            )
            continue

        # Build digest contribution
        summary = summaries_by_id.get(coach_id, {})
        contribution = {
            "cycle_date": cycle_date,
            "key_concerns_captured": summary.get("key_concerns", []),
            "key_recommendations_captured": summary.get("key_recommendations", []),
            "predictions_captured": summary.get("predictions_active", []),
            "team_input_requested": summary.get("wants_team_input_on", []),
            "updated_at": now_iso,
        }

        # Find disagreements involving this coach
        involved_disagreements = []
        for d in digest.get("active_disagreements", []):
            if coach_id in d.get("coaches", []):
                involved_disagreements.append({
                    "topic": d.get("topic", ""),
                    "with_coaches": [c for c in d.get("coaches", []) if c != coach_id],
                    "my_position": d.get("positions", {}).get(coach_id, ""),
                })
        if involved_disagreements:
            contribution["active_disagreements"] = involved_disagreements

        # Update compressed state with digest contribution
        compressed["digest_contribution"] = contribution
        compressed["pk"] = coach_pk
        compressed["sk"] = "COMPRESSED#latest"

        if _put_item(compressed):
            updated += 1

    logger.info(
        "Updated %d coach COMPRESSED#latest records with digest contributions",
        updated,
    )
    return updated


# ══════════════════════════════════════════════════════════════════════════════
# HANDLER
# ══════════════════════════════════════════════════════════════════════════════

def lambda_handler(event, context):
    """Produce the cross-coach ensemble digest for a completed generation cycle.

    Event fields (all optional):
      - cycle_date: str — YYYY-MM-DD (defaults to today UTC)
      - coach_ids: list[str] — override which coaches to include (defaults to all 8)

    Returns the ensemble digest JSON.
    """
    cycle_date = event.get("cycle_date") or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    coach_ids = event.get("coach_ids") or ALL_COACH_IDS

    # Validate coach IDs
    coach_ids = [cid for cid in coach_ids if cid in ALL_COACH_IDS]
    if not coach_ids:
        logger.error("No valid coach IDs provided — using all coaches")
        coach_ids = ALL_COACH_IDS

    logger.info(
        "Starting ensemble digest for cycle %s — %d coaches targeted",
        cycle_date, len(coach_ids),
    )

    # Step 1: Gather data from all coaches
    coach_data = _gather_coach_data(coach_ids)

    if not coach_data:
        logger.warning(
            "No coach data available for cycle %s — writing empty digest",
            cycle_date,
        )
        digest = {
            "coach_summaries": [],
            "active_disagreements": [],
            "unanimous_flags": [],
            "created_at": datetime.now(timezone.utc).isoformat(),
            "note": "No coach data available — coaches may not have generated outputs yet.",
        }
        _write_digest(digest, cycle_date)
        return _decimal_to_float(digest)

    logger.info(
        "Gathered data from %d/%d coaches: %s",
        len(coach_data), len(coach_ids),
        list(coach_data.keys()),
    )

    # Step 2: Call Haiku to produce the ensemble digest
    user_message = _build_user_message(coach_data, cycle_date)

    try:
        result = _call_haiku(
            system=ENSEMBLE_SYSTEM_PROMPT,
            user_message=user_message,
            max_tokens=2000,
            temperature=0.2,
        )

        # Validate we got a dict with the expected structure
        if isinstance(result, dict):
            # Ensure required fields exist with sensible defaults
            digest = {
                "coach_summaries": result.get("coach_summaries", []),
                "active_disagreements": result.get("active_disagreements", []),
                "unanimous_flags": result.get("unanimous_flags", []),
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            logger.info(
                "Ensemble digest produced — %d summaries, %d disagreements, %d unanimous flags",
                len(digest["coach_summaries"]),
                len(digest["active_disagreements"]),
                len(digest["unanimous_flags"]),
            )
        else:
            logger.warning(
                "LLM returned non-dict response — using fallback digest"
            )
            digest = _build_default_digest(coach_data, cycle_date)

    except Exception as e:
        logger.error("LLM call failed: %s — using fallback digest", e)
        digest = _build_default_digest(coach_data, cycle_date)

    # Step 3: Write the digest
    _write_digest(digest, cycle_date)

    # Step 4: Write/update disagreement records
    disagreements = digest.get("active_disagreements", [])
    if disagreements:
        _write_disagreements(disagreements, cycle_date)

    # Step 5: Update each coach's compressed state with digest contribution
    _update_coach_compressed_states(digest, coach_data, cycle_date)

    logger.info("Ensemble digest complete for cycle %s", cycle_date)
    return _decimal_to_float(digest)
