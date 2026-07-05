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
  7. Query newest INTERACTION# records (#531: board Q&A; #533: field-note pushback)
  8. Query newest resolved LEARNING# records (#533: prediction outcomes)
  9. Call Haiku to compress into ~500-token summary
  10. Write to COACH#{coach_id} / COMPRESSED#latest

DynamoDB patterns:
  PK=COACH#{coach_id}  SK=OUTPUT#*
  PK=COACH#{coach_id}  SK=THREAD#*
  PK=COACH#{coach_id}  SK=PREDICTION#*
  PK=COACH#{coach_id}  SK=CONFIDENCE#*
  PK=COACH#{coach_id}  SK=RELATIONSHIP#state
  PK=COACH#{coach_id}  SK=VOICE#state
  PK=COACH#{coach_id}  SK=INTERACTION#*  (#531: board Q&A; #533: field-note pushback, episodic)
  PK=COACH#{coach_id}  SK=LEARNING#*  (#533: resolved prediction outcomes, read-only fold-in)
  PK=COACH#{coach_id}  SK=COMPRESSED#latest  (output)

Schedule: Weekly (Sunday 6:00 AM PT / 14:00 UTC via EventBridge)

v1.0.0 — 2026-04-06 (Coach Intelligence)
"""

import json
import logging
import os
import re
import urllib.error
import urllib.request
from datetime import datetime, timezone
from decimal import Decimal

import boto3
from phase_filter import with_phase_filter  # ADR-058

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
    "sleep_coach",
    "nutrition_coach",
    "training_coach",
    "mind_coach",
    "physical_coach",
    "glucose_coach",
    "labs_coach",
    "explorer_coach",
]

# #531: display names/domains come from the canonical persona registry
# (config/personas.json via persona_registry) — the hand-copied dict that used
# to live here had drifted to the RETIRED cast, so every COMPRESSED#/STANCE#
# record carried the wrong byline. One registry, no local copies.
try:
    import persona_registry as _persona_registry
except ImportError:  # pragma: no cover — environment-dependent
    _persona_registry = None


def _coach_meta(coach_id):
    """{display_name, domain} for a coach from the canonical registry."""
    if _persona_registry is not None:
        try:
            p = _persona_registry.resolve(coach_id, s3, S3_BUCKET) or {}
            if p.get("name"):
                return {"display_name": p["name"], "domain": p.get("domain", "unknown")}
        except Exception as e:
            logger.warning("[persona] registry lookup failed for %s: %s", coach_id, e)
    return {"display_name": coach_id, "domain": "unknown"}


# Maximum OUTPUT# records to fetch per coach
MAX_OUTPUT_RECORDS = 20

# Prediction statuses considered "active"
ACTIVE_PREDICTION_STATUSES = {"pending", "confirming", "confirmed"}

# ── #410: bounded compression input ─────────────────────────────────────────
# The compressor used to read EVERY THREAD#/PREDICTION# record in the coach's
# partition and pour all open/active ones into one Haiku prompt — unbounded
# per-coach history flowing into a fixed-size context. It already failed once
# (a coach at 52 threads / 39 predictions truncated mid-compression and served
# a degraded context for weeks); the max_tokens bump to 4000 was the band-aid.
# These bounds supersede it: reads are page/limit-capped, the prompt carries
# the most-recent-N of each class plus an honest rollup line for the rest, and
# a deterministic char budget guards the whole message. Nothing is archived or
# deleted — older records stay in DynamoDB, queryable, and the public track
# record (which reads PREDICTION# independently) is untouched.
MAX_OPEN_THREADS_IN_PROMPT = 15  # most-recently-referenced first
MAX_ACTIVE_PREDICTIONS_IN_PROMPT = 15  # newest first (SK embeds the date)
MAX_PREDICTION_SCAN = 120  # newest PREDICTION# records scanned for active ones
MAX_QUERY_PAGES = 20  # hard stop on any partition pagination
MAX_COMPRESSION_INPUT_CHARS = 24_000  # ≈6k tokens — well inside Haiku's budget
MIN_WINDOW_FLOOR = 5  # the budget guard never shrinks a window below this
# #531: newest public-board Q&A records (INTERACTION#, written by site-api-ai)
# folded into the weekly compression so board answers enter the coach's memory.
# #533: the same SK also carries field-note pushback (broadcast by
# mcp/tools_lifestyle.tool_log_field_note_response) — one shared window covers both.
MAX_INTERACTIONS_IN_PROMPT = 10
# #533: newest resolved LEARNING# records (written by coach_prediction_evaluator)
# folded in read-only — no new write path, this just plumbs an existing record
# type into the compression the coach already sees, so it can reference specific
# calls it got right or wrong instead of only unresolved pending predictions.
MAX_LEARNING_IN_PROMPT = 10

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
    """ADR-062: Bedrock IAM auth — sentinel; see task #90 for full plumbing removal."""
    return "_BEDROCK_IAM_"


# ══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════════════════════


from numeric import decimals_to_float as _decimal_to_float  # noqa: E402,F401


def _float_to_decimal(obj):
    """Recursively convert floats to Decimal for DynamoDB writes."""
    if isinstance(obj, float):
        return Decimal(str(obj))
    if isinstance(obj, dict):
        return {k: _float_to_decimal(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_float_to_decimal(v) for v in obj]
    return obj


# Canonical emitter lives in the layer — local copy removed 2026-06-12.
from retry_utils import _emit_token_metrics  # noqa: E402,F401


def _emit_failure_metric():
    """Emit API failure metric to CloudWatch (non-fatal)."""
    try:
        _cw.put_metric_data(
            Namespace=_CW_NAMESPACE,
            MetricData=[
                {
                    "MetricName": "AnthropicAPIFailure",
                    "Dimensions": [{"Name": "LambdaFunction", "Value": _LAMBDA_NAME}],
                    "Value": 1,
                    "Unit": "Count",
                }
            ],
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


def _query_begins_with(pk, sk_prefix, scan_forward=True, limit=None, include_pilot=False, max_pages=MAX_QUERY_PAGES):
    """Query DynamoDB for items with SK beginning with a prefix.

    ADR-058: applies the default-deny phase filter so tombstoned coach records
    (phase=pilot) are hidden. Pass include_pilot=True to see them.
    #410: pagination is hard-capped at max_pages so no partition read is ever
    unbounded — a coach partition growing for years can't balloon this scan.
    """
    from boto3.dynamodb.conditions import Key

    try:
        kwargs = with_phase_filter(
            {
                "KeyConditionExpression": Key("pk").eq(pk) & Key("sk").begins_with(sk_prefix),
                "ScanIndexForward": scan_forward,
            },
            include_pilot=include_pilot,
        )
        if limit:
            kwargs["Limit"] = limit

        items = []
        pages = 0
        while True:
            resp = table.query(**kwargs)
            items.extend(resp.get("Items", []))
            pages += 1
            # If we have a limit and have enough items, stop paginating
            if limit and len(items) >= limit:
                items = items[:limit]
                break
            if "LastEvaluatedKey" not in resp:
                break
            if max_pages and pages >= max_pages:
                logger.warning("query_begins_with(%s, %s): page cap %d hit — bounded read (#410)", pk, sk_prefix, max_pages)
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
        coach_pk,
        "OUTPUT#",
        scan_forward=False,
        limit=MAX_OUTPUT_RECORDS,
    )
    logger.info("Fetched %d OUTPUT# records for %s", len(outputs), coach_id)

    # 2. Query THREAD# records (page-capped), filter to status=open, then
    # window to the most-recently-referenced N (#410). Older open threads are
    # counted for the prompt's rollup line, never silently dropped.
    all_threads = _query_begins_with(coach_pk, "THREAD#")
    open_threads = [t for t in all_threads if t.get("status") == "open"]
    open_threads.sort(key=lambda t: str(t.get("last_referenced", "")), reverse=True)
    open_threads_total = len(open_threads)
    open_threads = open_threads[:MAX_OPEN_THREADS_IN_PROMPT]
    logger.info(
        "Fetched %d THREAD# records for %s (%d open, %d in prompt window)",
        len(all_threads),
        coach_id,
        open_threads_total,
        len(open_threads),
    )

    # 3. Query the NEWEST PREDICTION# records only (#410) — the SK embeds the
    # creation date (PREDICTION#pred_YYYYMMDD_slug) so a reverse bounded query
    # is a true recency window; decided/expired records age out of it naturally
    # while staying in DynamoDB for the track record. Active ones are windowed
    # to the newest N for the prompt.
    scanned_predictions = _query_begins_with(coach_pk, "PREDICTION#", scan_forward=False, limit=MAX_PREDICTION_SCAN)
    active_predictions = [p for p in scanned_predictions if p.get("status") in ACTIVE_PREDICTION_STATUSES]
    active_predictions_total = len(active_predictions)
    active_predictions = active_predictions[:MAX_ACTIVE_PREDICTIONS_IN_PROMPT]
    logger.info(
        "Scanned %d newest PREDICTION# records for %s (%d active, %d in prompt window)",
        len(scanned_predictions),
        coach_id,
        active_predictions_total,
        len(active_predictions),
    )

    # 4. Query all CONFIDENCE# records
    confidence_records = _query_begins_with(coach_pk, "CONFIDENCE#")
    logger.info("Fetched %d CONFIDENCE# records for %s", len(confidence_records), coach_id)

    # 5. Read RELATIONSHIP#state
    relationship_state = _get_item(coach_pk, "RELATIONSHIP#state")

    # 6. Read VOICE#state
    voice_state = _get_item(coach_pk, "VOICE#state")

    # 7. #531: newest public-board interactions (episodic Q&A written back by
    # site-api-ai) — the SK embeds the date, so a reverse bounded query is a
    # true recency window.
    interactions = _query_begins_with(coach_pk, "INTERACTION#", scan_forward=False, limit=MAX_INTERACTIONS_IN_PROMPT)
    logger.info("Fetched %d INTERACTION# records for %s (window %d)", len(interactions), coach_id, MAX_INTERACTIONS_IN_PROMPT)

    # 8. #533: newest resolved prediction outcomes (LEARNING#, written by
    # coach_prediction_evaluator) — read-only fold-in, no new write path. The SK
    # embeds the evaluation date, so a reverse bounded query is a true recency
    # window; the public track record (which reads LEARNING# independently) is
    # untouched.
    learning_outcomes = _gather_learning(coach_id, limit=MAX_LEARNING_IN_PROMPT)
    logger.info("Fetched %d LEARNING# records for %s (window %d)", len(learning_outcomes), coach_id, MAX_LEARNING_IN_PROMPT)

    return {
        "outputs": outputs,
        "open_threads": open_threads,
        "open_threads_total": open_threads_total,
        "active_predictions": active_predictions,
        "active_predictions_total": active_predictions_total,
        "confidence_records": confidence_records,
        "relationship_state": relationship_state,
        "voice_state": voice_state,
        "interactions": interactions,
        "learning_outcomes": learning_outcomes,
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
    "- Key concerns the coach is currently monitoring\n"
    "- Notable public reader interactions (board Q&A) — positions the coach took "
    "publicly, so future outputs can reference and never contradict them\n"
    "- Matthew's own pushback on the weekly field notes (agreement/disagreement, disputes) — "
    "so future outputs can acknowledge where he pushed back\n"
    "- Resolved prediction outcomes — specific calls confirmed or refuted, so future outputs "
    "can say 'I was right about X' or 'I was wrong about Y' rather than only listing pending calls\n\n"
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
    meta = _coach_meta(coach_id)
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

    # Open threads — windowed (#410): the rollup line keeps the omitted count
    # honest so the compressor knows the window isn't the whole history.
    open_threads = state.get("open_threads", [])
    open_total = state.get("open_threads_total", len(open_threads))
    if open_threads:
        if open_total > len(open_threads):
            parts.append(
                f"## Open Threads (showing the {len(open_threads)} most-recently-referenced "
                f"of {open_total} open; {open_total - len(open_threads)} older open threads "
                f"omitted from this compression — they remain stored and may resurface)"
            )
        else:
            parts.append(f"## Open Threads ({len(open_threads)})")
        for thread in open_threads:
            slug = thread.get("sk", "").replace("THREAD#", "")
            summary = thread.get("summary", "no summary")
            thread_type = thread.get("type", "observation")
            ref_count = thread.get("reference_count", 0)
            last_ref = thread.get("last_referenced", "unknown")
            parts.append(f"  - [{thread_type}] {slug}: {summary} " f"(refs={ref_count}, last_ref={last_ref})")
        parts.append("")
    else:
        parts.append("## Open Threads: NONE")
        parts.append("")

    # Active predictions — windowed (#410), newest first.
    active_preds = state.get("active_predictions", [])
    active_total = state.get("active_predictions_total", len(active_preds))
    if active_preds:
        if active_total > len(active_preds):
            parts.append(
                f"## Active Predictions (showing the {len(active_preds)} newest of "
                f"{active_total} active; {active_total - len(active_preds)} older active "
                f"predictions omitted from this compression — the evaluator still grades them)"
            )
        else:
            parts.append(f"## Active Predictions ({len(active_preds)})")
        for pred in active_preds:
            pred_id = pred.get("prediction_id", pred.get("sk", "").replace("PREDICTION#", ""))
            claim = pred.get("claim_natural", "no claim")
            status = pred.get("status", "pending")
            confidence = pred.get("confidence", 0.5)
            subdomain = pred.get("subdomain", "general")
            parts.append(f"  - [{status}] {pred_id}: {claim} " f"(confidence={confidence}, subdomain={subdomain})")
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

    # #531: public-board Q&A (episodic) — what the coach told READERS. Folding
    # these in means a board answer becomes part of the coach's one memory.
    # #533: the same SK/window also carries field-note pushback (Matthew's
    # agreement/disagreement with the weekly field notes, broadcast to every
    # coach since a field note isn't attributable to one domain) — branch on
    # interaction_type so each renders in its own voice.
    interactions = state.get("interactions", [])
    if interactions:
        parts.append(f"## Reader Interactions & Field-Note Pushback ({len(interactions)} newest)")
        for it in interactions:
            sk_parts = str(it.get("sk", "")).split("#")
            date = sk_parts[1] if len(sk_parts) > 1 else "unknown"
            itype = it.get("interaction_type", "board_qa")
            if itype == "field_note_pushback":
                agreement = it.get("agreement") or "unspecified"
                notes = str(it.get("notes", ""))[:300]
                disputed = it.get("disputed") or []
                parts.append(f"  - [{date}] Matthew's field-note response ({it.get('week', '?')}, agreement={agreement}): {notes}")
                if disputed:
                    parts.append(f"    Disputed: {'; '.join(str(d) for d in disputed[:3])}")
            else:
                q = str(it.get("question", ""))[:200]
                a = str(it.get("answer", ""))[:300]
                flag = "" if it.get("grounded", True) else " [answered with a grounding refusal]"
                parts.append(f"  - [{date}]{flag} A reader asked: {q}")
                parts.append(f"    You answered: {a}")
        parts.append("")
    else:
        parts.append("## Reader Interactions & Field-Note Pushback: NONE")
        parts.append("")

    # #533: resolved prediction outcomes (LEARNING# records) — so the coach can
    # reference a specific call it got right or wrong, not just list pending
    # predictions. Read-only fold-in of an already-written record type.
    learning_outcomes = state.get("learning_outcomes", [])
    if learning_outcomes:
        parts.append(f"## Prediction Outcomes ({len(learning_outcomes)} newest resolved)")
        for rec in learning_outcomes:
            date = rec.get("date") or str(rec.get("sk", "")).replace("LEARNING#", "").split("#")[0]
            status = str(rec.get("status", "unknown")).upper()
            subdomain = rec.get("subdomain", "general")
            metric = rec.get("metric", "")
            reason = str(rec.get("reason", ""))[:200]
            metric_bit = f", {metric}" if metric else ""
            parts.append(f"  - [{date}] {status} ({subdomain}{metric_bit}): {reason}")
        parts.append("")
    else:
        parts.append("## Prediction Outcomes: NONE")
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
    meta = _coach_meta(coach_id)
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
            {"id": t.get("sk", "").replace("THREAD#", ""), "summary": t.get("summary", "")} for t in state.get("open_threads", [])[:5]
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


def _build_bounded_compression_message(coach_id, state):
    """#410: build the compression message inside MAX_COMPRESSION_INPUT_CHARS.

    The windows in _gather_coach_state already bound the normal case; this is
    the deterministic backstop for pathological record sizes (a thread with a
    huge summary, oversized voice state). If the message exceeds the budget,
    the thread/prediction windows are halved (never below MIN_WINDOW_FLOOR)
    and the message rebuilt — each shrink is logged, and the rollup lines keep
    the omitted counts honest. Guaranteed to terminate at the floors."""
    working = dict(state)
    message = _build_compression_message(coach_id, working)
    while len(message) > MAX_COMPRESSION_INPUT_CHARS:
        threads = working.get("open_threads", [])
        preds = working.get("active_predictions", [])
        if len(threads) <= MIN_WINDOW_FLOOR and len(preds) <= MIN_WINDOW_FLOOR:
            logger.warning(
                "compression input for %s still %d chars at window floor — sending as-is (output budget still holds)",
                coach_id,
                len(message),
            )
            break
        working["open_threads"] = threads[: max(MIN_WINDOW_FLOOR, len(threads) // 2)]
        working["active_predictions"] = preds[: max(MIN_WINDOW_FLOOR, len(preds) // 2)]
        logger.warning(
            "compression input for %s over budget (%d > %d chars) — shrinking windows to %d threads / %d predictions (#410)",
            coach_id,
            len(message),
            MAX_COMPRESSION_INPUT_CHARS,
            len(working["open_threads"]),
            len(working["active_predictions"]),
        )
        message = _build_compression_message(coach_id, working)
    return message


def _compress_coach(coach_id, state):
    """Compress a single coach's history via Haiku LLM call.

    Returns the compressed state dict ready for DynamoDB write.
    Falls back to structural-only compression if the LLM call fails.
    """
    meta = _coach_meta(coach_id)
    now_iso = datetime.now(timezone.utc).isoformat()

    # Build the compression prompt inside the deterministic input budget (#410)
    user_message = _build_bounded_compression_message(coach_id, state)

    try:
        result = _call_haiku(
            system=COMPRESSION_SYSTEM_PROMPT,
            user_message=user_message,
            # 2026-06-29: was 1500 — too small once threads/predictions accrued.
            # A rich coach (50+ threads, 40+ predictions) produces a compressed
            # JSON that exceeded 1500 tokens, truncated mid-object, never emitted
            # the closing ```json fence, failed to parse, and EVERY coach silently
            # fell back to a structural-only stub — degrading the orchestrator's
            # context AND blocking the stance engine (which won't ground on a
            # fallback). 4000 gives headroom; you only pay for tokens generated.
            # (Same failure mode + fix as the orchestrator's 2000→6000 bump.)
            # #410 superseded the growth side of this band-aid: the INPUT is now
            # bounded (windowed threads/predictions + the char budget above), so
            # the summary size no longer scales with experiment tenure.
            max_tokens=4000,
            temperature=0.2,
        )

        if not isinstance(result, dict):
            logger.warning("LLM returned non-dict for %s compression — using fallback", coach_id)
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
# STANCE ENGINE — the coach-opinion: an evolving, evidence-derived read of Matthew
# ══════════════════════════════════════════════════════════════════════════════
#
# A stance is the coach's CURRENT read of Matthew in this coach's domain — what it
# is focused on now, what it has set aside, and how that read has CHANGED as
# evidence accrued. It is grounded ONLY in the coach's own already-validated
# artifacts (the compressed history's positions/corrections, the scored track
# record, the prior stance) — never in raw physiological values — so it sidesteps
# the daily-narrative fabrication frontier by construction. It REPLACES the
# hand-authored weight-band ladder as the public "read of him" (the ladder stays a
# silent fallback in site_api_coach._stance_block).

# Patterns the stance must NEVER fabricate — it speaks to *thinking*, not
# measurements. A hit drives a single strict regeneration; a residual hit sets a
# grounding flag the render/Sentinel can see.
_RAW_VITAL_RE = re.compile(
    r"\b\d{2,3}\s?(?:bpm|ms|mg/?dl|lbs?|kg|kcal|cal)\b"
    r"|\b(?:rhr|hrv|recovery|resting heart rate|resting hr|deep|rem)\b[^.\n]{0,14}?\b\d"
    r"|\b\d{1,3}(?:\.\d+)?\s?%",
    re.IGNORECASE,
)

# Language that asserts the read has evolved — only allowed when a real signal of
# change exists (a logged correction or a stage shift vs the prior stance).
_CHANGE_RE = re.compile(
    r"\b(?:chang|shift|revis|reconsider|no longer|used to|previously|earlier I|"
    r"moved (?:on |from )|updated my|come around|changed my mind|where I once)",
    re.IGNORECASE,
)

STANCE_SYSTEM_PROMPT = (
    "You maintain the evolving STANCE of one AI health coach toward the person they coach "
    "(Matthew). A stance is the coach's current *read* of him IN THIS COACH'S DOMAIN — what the "
    "coach is focused on now, what it has set aside for now, where it thinks he is in this "
    "domain's progression, and HOW that read has changed as evidence accrued.\n\n"
    "## Ground truth (your stance must FOLLOW from these — provided in the user message):\n"
    "- The coach's compressed history: positions taken, key concerns, corrections made, "
    "relationship notes, recent themes.\n"
    "- The coach's scored track record: predictions confirmed/refuted, an overall hit-rate, "
    "per-subdomain confidence.\n"
    "- The coach's PREVIOUS stance (may be absent on the first run).\n\n"
    "## ABSOLUTE RULES:\n"
    "- Speak to the coach's THINKING — positions, focus, what changed and why. This is an "
    "OPINION, not a data readout.\n"
    "- NEVER invent or cite raw physiological numbers — no HRV in ms, no RHR/recovery/sleep "
    "values, no weights, no calorie counts, no percentages. Name the PATTERN or the PREDICTION, "
    "never a number.\n"
    "- This includes TARGETS and GAPS-TO-TARGET, even accurate ones: say 'running well short of the "
    "protein target I want to see', NOT '26% short of 190g'. Express every quantity as a qualitative "
    "pattern (short / on-track / climbing / stalled) — a stance is an opinion, never a readout.\n"
    "- 'how_my_read_changed' must describe a REAL change grounded in 'corrections_made' or a "
    "genuine shift versus the previous stance. If nothing genuinely changed — or there is no "
    "previous stance — return an empty string.\n"
    "- 'stage' is a domain-appropriate sense of where he is in THIS domain's progression, derived "
    "from your read — NOT from his bodyweight.\n"
    "- Write in the FIRST PERSON ('I'). Address him as 'you'. You ARE this coach.\n\n"
    "## Output — return ONLY valid JSON, no markdown, no preamble:\n"
    "{\n"
    '  "headline_read": "one tight paragraph: my current read of you, in my domain",\n'
    '  "focused_on_now": ["what I care most about right now (evidence-derived)"],\n'
    '  "set_aside_for_now": ["what I am deliberately not chasing yet"],\n'
    '  "stage": {"label": "short domain-appropriate stage name", "rationale": "why this stage, from my read"},\n'
    '  "how_my_read_changed": "the genuine evolution vs my prior stance, or \\"\\" if nothing changed",\n'
    '  "confidence_note": "how sure I am, grounded in my track record",\n'
    '  "evidence_basis": ["the positions/predictions/threads this read rests on"]\n'
    "}\n"
)

_STANCE_FIELDS = {
    "headline_read": "",
    "focused_on_now": [],
    "set_aside_for_now": [],
    "stage": {},
    "how_my_read_changed": "",
    "confidence_note": "",
    "evidence_basis": [],
}


def _contains_raw_vitals(text):
    """True if the text cites a raw physiological number the stance must not invent."""
    return bool(_RAW_VITAL_RE.search(text or ""))


def _vital_hits(stance):
    """Count raw-vital citations across the prose fields of a stance dict."""
    if not isinstance(stance, dict):
        return 0
    prose = " ".join(
        [
            str(stance.get("headline_read", "")),
            str(stance.get("how_my_read_changed", "")),
            str(stance.get("confidence_note", "")),
            " ".join(str(x) for x in stance.get("focused_on_now", []) or []),
            " ".join(str(x) for x in stance.get("set_aside_for_now", []) or []),
        ]
    )
    return len(_RAW_VITAL_RE.findall(prose))


def _claims_change(text):
    """True if the prose asserts the read has evolved (needs a real change signal)."""
    return bool(_CHANGE_RE.search(text or ""))


def _gather_learning(coach_id, limit=40):
    """Most-recent resolved LEARNING# verdicts (the coach's scored track record).

    Shared by the stance engine's grounding (below) and, since #533, the main
    compression gather (_gather_coach_state) — same records, two callers.
    """
    return _query_begins_with(f"COACH#{coach_id}", "LEARNING#", scan_forward=False, limit=limit)


def _summarize_track_record(learning, confidence_records):
    """Reduce LEARNING#/CONFIDENCE# into the grounding block the stance reasons from.

    Mirrors the hit/miss accounting site_api_coach._track_record surfaces publicly,
    so the stance's self-assessment agrees with the coach page's headline stat.
    """
    _hit = {"confirmed", "correct", "hit", "true"}
    _miss = {"refuted", "incorrect", "miss", "false"}
    confirmed = refuted = 0
    recent = []
    for rec in learning or []:
        verdict = (rec.get("verdict") or rec.get("outcome") or rec.get("result") or "").lower()
        if verdict in _hit:
            confirmed += 1
        elif verdict in _miss:
            refuted += 1
        if len(recent) < 8:
            recent.append(
                {
                    "date": rec.get("sk", "").replace("LEARNING#", "").split("#")[0],
                    "verdict": verdict or "pending",
                    "claim": (rec.get("claim_natural") or rec.get("claim") or "")[:160],
                }
            )
    decided = confirmed + refuted
    confidence = {}
    for conf in confidence_records or []:
        sub = conf.get("subdomain", conf.get("sk", "").replace("CONFIDENCE#", ""))
        confidence[sub] = round(conf.get("mean_confidence", 0.5), 3)
    return {
        "confirmed": confirmed,
        "refuted": refuted,
        "decided": decided,
        "hit_rate_pct": round(100 * confirmed / decided) if decided else None,
        "recent": recent,
        "confidence": confidence,
    }


def _build_stance_message(coach_id, compressed, track, prior_stance):
    """Assemble the grounding the stance LLM call reasons from."""
    meta = _coach_meta(coach_id)
    grounding = {
        "coach": meta["display_name"],
        "domain": meta["domain"],
        "compressed_history": {
            "summary": compressed.get("summary", ""),
            "positions_taken": compressed.get("positions_taken", []),
            "key_concerns": compressed.get("key_concerns", []),
            "corrections_made": compressed.get("corrections_made", []),
            "relationship_notes": compressed.get("relationship_notes", ""),
            "recent_themes": compressed.get("recent_themes", []),
        },
        "track_record": track,
        "previous_stance": (
            {
                "headline_read": prior_stance.get("headline_read", ""),
                "stage": prior_stance.get("stage", {}),
                "focused_on_now": prior_stance.get("focused_on_now", []),
                "as_of": prior_stance.get("as_of"),
            }
            if prior_stance
            else None
        ),
    }
    return (
        f"## Coach: {meta['display_name']} ({meta['domain']})\n\n"
        "Form your CURRENT stance toward Matthew from this grounding. If there is no previous "
        'stance, "how_my_read_changed" MUST be an empty string.\n\n'
        f"{json.dumps(grounding, indent=2, default=str)}"
    )


def _sanitize_stance(stance, compressed, prior_stance):
    """Blank an ungrounded evolution claim. First run => no change is possible.

    A change claim is grounded only when the coach logged a correction or its stage
    actually shifted versus the prior stance — otherwise it's narrative invention.
    """
    if prior_stance is None:
        stance["how_my_read_changed"] = ""
        return stance
    changed = stance.get("how_my_read_changed") or ""
    if changed and _claims_change(changed):
        stage_now = (stance.get("stage") or {}).get("label")
        stage_prior = (prior_stance.get("stage") or {}).get("label")
        grounded = bool(compressed.get("corrections_made")) or (stage_now and stage_now != stage_prior)
        if not grounded:
            logger.info("[stance] dropping ungrounded change claim for %s", stance.get("coach_id"))
            stance["how_my_read_changed"] = ""
    return stance


def _generate_stance(coach_id, compressed, track, prior_stance):
    """Generate one coach's evolving stance via a grounded Haiku call.

    Self-corrects ONCE if raw vitals leak (mirrors ai_expert_analyzer). Returns the
    stance dict, or None on a hard failure (caller treats a missing stance as
    fail-soft — the public render keeps the ladder fallback).
    """
    meta = _coach_meta(coach_id)
    now_iso = datetime.now(timezone.utc).isoformat()
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    user_message = _build_stance_message(coach_id, compressed, track, prior_stance)
    result = _call_haiku(system=STANCE_SYSTEM_PROMPT, user_message=user_message, max_tokens=1400, temperature=0.3)
    if not isinstance(result, dict):
        logger.warning("[stance] LLM returned non-dict for %s — skipping stance this run", coach_id)
        return None

    # Self-correct once if the read leaked raw numbers.
    if _vital_hits(result) > 0:
        strict = user_message + (
            "\n\nSTRICT CORRECTION: your previous attempt cited raw numeric values (HRV/RHR/"
            "weights/percentages). Rewrite with ZERO numbers — describe patterns and positions only."
        )
        retry = _call_haiku(system=STANCE_SYSTEM_PROMPT, user_message=strict, max_tokens=1400, temperature=0.2)
        if isinstance(retry, dict) and _vital_hits(retry) < _vital_hits(result):
            result = retry

    for field, default in _STANCE_FIELDS.items():
        result.setdefault(field, default() if callable(default) else default)
    result["coach_id"] = coach_id
    result["display_name"] = meta["display_name"]
    result["domain"] = meta["domain"]
    result["as_of"] = today
    result["generated_at"] = now_iso

    _sanitize_stance(result, compressed, prior_stance)
    result["grounding_flag"] = _vital_hits(result) > 0
    if result["grounding_flag"]:
        logger.warning("[stance] %s retains raw-vital citations after correction — flagged", coach_id)
    return result


def _write_stance(coach_id, stance):
    """Persist STANCE#{date} (immutable history) + STANCE#latest (the live pointer)."""
    date = stance.get("as_of")
    ok_hist = _put_item({"pk": f"COACH#{coach_id}", "sk": f"STANCE#{date}", **stance})
    ok_latest = _put_item({"pk": f"COACH#{coach_id}", "sk": "STANCE#latest", **stance})
    if ok_hist and ok_latest:
        logger.info("Wrote STANCE#%s + STANCE#latest for %s", date, coach_id)
    return ok_hist and ok_latest


def _run_stance(coach_id, compressed, state):
    """Gather track record + prior stance, generate, and persist. Returns a result
    dict for the handler summary. Fail-soft — never raises into the compression loop."""
    if compressed.get("_fallback"):
        return {"written": False, "reason": "compression_fallback"}
    try:
        track = _summarize_track_record(_gather_learning(coach_id), state.get("confidence_records", []))
        prior_stance = _get_item(f"COACH#{coach_id}", "STANCE#latest")
        stance = _generate_stance(coach_id, compressed, track, prior_stance)
        if not stance:
            return {"written": False, "reason": "generation_failed"}
        written = _write_stance(coach_id, stance)
        return {
            "written": written,
            "stage": (stance.get("stage") or {}).get("label"),
            "evolved": bool(stance.get("how_my_read_changed")),
            "grounding_flag": stance.get("grounding_flag", False),
        }
    except Exception as e:
        logger.error("[stance] generation failed for %s (non-fatal): %s", coach_id, e)
        return {"written": False, "error": str(e)}


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
            len(coach_ids),
            coach_ids,
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
                    len(state.get("outputs", [])) + len(state.get("open_threads", [])) + len(state.get("active_predictions", []))
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

                # Stance engine (coach-opinion) — evolving evidence-derived read of
                # Matthew. Fail-soft: a stance error never aborts the compression run.
                results[coach_id]["stance"] = _run_stance(coach_id, compressed, state)

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
            success_count,
            skip_count,
            error_count,
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
