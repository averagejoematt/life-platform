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
import urllib.error
import urllib.request
from datetime import datetime, timezone
from decimal import Decimal

import boto3
from constants import EXPERIMENT_START_DATE  # ADR-058
from phase_filter import with_phase_filter  # ADR-058

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
    "sleep_coach",
    "training_coach",
    "nutrition_coach",
    "mind_coach",
    "physical_coach",
    "glucose_coach",
    "labs_coach",
    "explorer_coach",
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


def _track_record_block(coach_id: str) -> str:
    """Summarize this coach's resolved LEARNING# verdicts for prompt injection.

    Counts by outcome + the two most recent resolved calls verbatim. Returns a
    plain statement when nothing has resolved yet (post-reset normal). Failure
    here must never block the narrative run.
    """
    try:
        from datetime import timedelta as _td

        from boto3.dynamodb.conditions import Key as _Key

        cutoff = (datetime.now(timezone.utc) - _td(days=60)).strftime("%Y-%m-%d")
        r = table.query(
            KeyConditionExpression=_Key("pk").eq(f"COACH#{coach_id}") & _Key("sk").gt(f"LEARNING#{cutoff}"),
        )
        recs = [x for x in r.get("Items", []) if not x.get("tombstone")]
        if not recs:
            return "Nothing resolved yet this cycle. Make calls; they will be scored."
        counts = {}
        for x in recs:
            st = str(x.get("status", "unknown"))
            counts[st] = counts.get(st, 0) + 1
        lines = [", ".join(f"{k}: {v}" for k, v in sorted(counts.items()))]
        resolved = [x for x in recs if x.get("status") in ("confirmed", "refuted")]
        resolved.sort(key=lambda x: str(x.get("date", "")), reverse=True)
        for x in resolved[:2]:
            lines.append(f"- {x.get('date', '?')}: {x.get('status')} — {str(x.get('condition') or x.get('reason') or '')[:160]}")
        lines.append(
            "When relevant, reference your own past calls in your narrative — "
            "own the misses plainly; credibility here comes from being scored, not from being right."
        )
        return "\n".join(lines)
    except Exception as _e:
        return "Track record unavailable this run."


def _call_haiku(system, user_message, max_tokens=6000, temperature=0.3):
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


def _query_begins_with(pk, sk_prefix, scan_forward=True, limit=None):
    """Query DynamoDB for items with SK beginning with a prefix. ADR-058: phase-filtered.

    D-03 follow-up (2026-06-06): callers pass `limit` to bound prompt growth —
    THREAD#/PREDICTION# accumulate daily forever, and unbounded reads fed an
    ever-growing orchestrator prompt (input creep). Pair with
    scan_forward=False to keep the most RECENT N.
    """
    from boto3.dynamodb.conditions import Key

    try:
        params = {
            "KeyConditionExpression": Key("pk").eq(pk) & Key("sk").begins_with(sk_prefix),
            "ScanIndexForward": scan_forward,
        }
        if limit:
            params["Limit"] = limit
        resp = table.query(**with_phase_filter(params))
        return _decimal_to_float(resp.get("Items", []))
    except Exception as e:
        logger.warning("query_begins_with(%s, %s) failed: %s", pk, sk_prefix, e)
        return []


def _query_latest(pk, sk_prefix):
    """Query for the most recent item matching a SK prefix. ADR-058: phase-filtered."""
    from boto3.dynamodb.conditions import Key

    try:
        resp = table.query(
            **with_phase_filter(
                {
                    "KeyConditionExpression": Key("pk").eq(pk) & Key("sk").begins_with(sk_prefix),
                    "ScanIndexForward": False,
                    "Limit": 1,
                }
            )
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
            "phase_started": EXPERIMENT_START_DATE,
            "journey_day": 1,
            "arc_history": [],
            "note": "Early baseline phase — experiment just begun.",
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

    # 8. Open threads (filter status=open; most recent 50 — D-03 input-creep bound)
    all_threads = _query_begins_with(coach_pk, "THREAD#", scan_forward=False, limit=50)
    open_threads = [t for t in all_threads if t.get("status") == "open"]
    if not open_threads:
        logger.info("No open threads for %s", coach_id)

    # 9. Active predictions (filter status in pending/confirming; most recent 50)
    all_predictions = _query_begins_with(coach_pk, "PREDICTION#", scan_forward=False, limit=50)
    active_predictions = [p for p in all_predictions if p.get("status") in ("pending", "confirming")]
    if not active_predictions:
        logger.info("No active predictions for %s", coach_id)

    # 10. Current stance — the coach-opinion engine's evolving read of Matthew
    # (coach_history_summarizer writes STANCE#latest). Absent pre-data; when
    # present it leads the generation framing over the static goal block.
    current_stance = _get_item(coach_pk, "STANCE#latest")
    if not current_stance:
        logger.info("No stance yet for %s — first cycles", coach_id)

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
        "current_stance": current_stance,
    }


def _stance_for_brief(stance):
    """Trim a STANCE#latest record to the fields that steer generation (drop the
    internal bookkeeping — grounding_flag, generated_at, evidence_basis)."""
    if not isinstance(stance, dict):
        return None
    return {
        "headline_read": stance.get("headline_read", ""),
        "focused_on_now": stance.get("focused_on_now", []),
        "set_aside_for_now": stance.get("set_aside_for_now", []),
        "stage": stance.get("stage", {}),
        "how_my_read_changed": stance.get("how_my_read_changed", ""),
        "as_of": stance.get("as_of"),
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
    """Build the orchestrator user message as two content blocks for prompt caching.

    ADR-062 follow-up (2026-05-28): the orchestrator runs once per coach (8/day),
    and the GLOBAL context blocks — `ensemble_digest`, `influence_graph`,
    `computation_results`, `narrative_arc` — are byte-identical across all 8
    invocations in a run, so they go in a `cache_control: ephemeral` block
    (serialized deterministically with sort_keys so the cached prefix matches
    exactly). Call 1 writes the cache, calls 2-8 read it at ~0.1x. The shared
    block is also what pushes the cached prefix over Haiku's minimum cacheable
    length (the old system-only block was too small to cache at all).

    D-03 follow-up (2026-06-06): ALL 8 coaches' compressed states now live in
    the shared block too. Previously the target's state + the 7 others were in
    the per-coach (uncached) suffix; because the 7-of-8 subset differs per
    target, those bytes never matched the cache and were billed full price on
    every call (~31K uncached in/call measured June 1-6, the platform's largest
    AI input line). The full 8-state set IS byte-identical across calls, so it
    caches; the suffix just names the target. Same information, ~50% less
    billed input.

    Returns a list of Anthropic content blocks (not a string).
    """
    # ── Shared prefix (identical across all coaches this run → cacheable) ──
    shared_parts = [
        "## Ensemble Digest (Most Recent Cycle)",
        json.dumps(state["ensemble_digest"], indent=2, sort_keys=True, default=str),
        "",
        "## Cross-Coach Influence Graph",
        json.dumps(state["influence_graph"], indent=2, sort_keys=True, default=str),
        "",
        "## Computation Results Package",
        json.dumps(state["computation_results"], indent=2, sort_keys=True, default=str),
        "",
        "## Narrative Arc State",
        json.dumps(state["narrative_arc"], indent=2, sort_keys=True, default=str),
        "",
        "## All Coach Compressed States",
        "(One entry per coach. The per-call instructions below name the target "
        "coach — read its state here; the rest provide cross-coach context.)",
    ]
    all_compressed = dict(state["other_compressed"])
    all_compressed[coach_id] = state["target_compressed"]
    for cid in sorted(all_compressed):  # sorted → byte-identical across all 8 calls
        shared_parts.append(f"### {cid}")
        shared_parts.append(json.dumps(all_compressed[cid], indent=2, sort_keys=True, default=str))

    # ── Per-coach suffix (varies per invocation → not cached) ──
    parts = [
        f"## Target Coach: {coach_id}",
        f"## Date: {today}",
        "",
        f"(The target coach's compressed state is the `{coach_id}` entry in " "'All Coach Compressed States' above.)",
        "",
    ]

    parts.append("## Coach Voice State")
    parts.append(json.dumps(state["voice_state"], indent=2, default=str))
    parts.append("")

    parts.append("## Open Threads")
    if state["open_threads"]:
        parts.append(json.dumps(state["open_threads"], indent=2, default=str))
    else:
        parts.append("No open threads — this is the coach's first cycle or all threads are resolved.")
    parts.append("")

    parts.append("## Active Predictions")
    if state["active_predictions"]:
        parts.append(json.dumps(state["active_predictions"], indent=2, default=str))
    else:
        parts.append("No active predictions — coach has not yet made formal predictions.")
    parts.append("")

    # Coach memory (2026-06-13): the coach's own resolved track record, so it
    # can reference past calls — and acknowledge misses — in its own voice.
    # Empty right after a reset; fills as the evaluator resolves predictions.
    parts.append("## Your Track Record (resolved predictions, last 60 days)")
    parts.append(_track_record_block(coach_id))
    parts.append("")

    # Current stance (2026-06-29): the coach's evolving, evidence-derived read of
    # Matthew. Steers the narrative beat/focus so generation follows the opinion
    # the coach has actually formed — not a static weight goal. Injected into the
    # brief deterministically downstream; surfaced here so PLANNING is stance-aware.
    parts.append("## Current Stance (your evolving read of Matthew)")
    if state.get("current_stance"):
        parts.append(json.dumps(_stance_for_brief(state["current_stance"]), indent=2, default=str))
        parts.append("Align the narrative beat and focus with this stance. If the data now contradicts it, that tension is the story.")
    else:
        parts.append("No stance yet — first cycles. Establish the read.")
    parts.append("")

    parts.append("## Instructions")
    parts.append(
        f"Produce a generation brief for {coach_id}. Return ONLY the JSON object "
        "with the schema: {coach_id, generation_brief: {open_threads, cross_coach_context, "
        "predictions_to_address, narrative_beat, journey_phase, periodization_note, "
        "voice_guidance: {avoid_openings, suggested_opening, structural_note}, "
        "decision_class_ceiling, evidence_note, seasonal_flags, computation_outputs}}.\n"
        # D-03 (2026-06-06): output tokens are the orchestrator's largest cost
        # line; un-tightened briefs ran 1800-3000 tokens of repeated prose.
        "Be CONCISE — this brief is machine-consumed planning, not coaching "
        "prose: every free-text field at most 2 sentences; do not restate data "
        "already in the context (reference it); include only the most relevant "
        "items — at most 5 open_threads, 5 cross_coach_context entries, and 5 "
        "predictions_to_address (drop the rest, lowest-priority first)."
    )

    return [
        {"type": "text", "text": "\n".join(shared_parts), "cache_control": {"type": "ephemeral"}},
        {"type": "text", "text": "\n".join(parts)},
    ]


# ══════════════════════════════════════════════════════════════════════════════
# BRIEF CACHING
# ══════════════════════════════════════════════════════════════════════════════


def _cache_brief(coach_id, brief, today):
    """Cache the generation brief to DynamoDB for fallback use."""
    try:
        item = _float_to_decimal(
            {
                "pk": f"COACH#{coach_id}",
                "sk": f"BRIEF#{today}",
                "brief": brief,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
        )
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
                "structural_note": ("First generation — establish voice and begin observing. " "No prior outputs to callback to."),
            },
            "decision_class_ceiling": "observational",
            "evidence_note": (
                "Very early in data collection (<14 days). " "All observations are preliminary. No directional claims warranted."
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
        # Budget guardrail: at Tier ≥ 1 skip the LLM and fall back to the cached/
        # default brief, so the coach pipeline keeps running with zero Bedrock spend.
        from budget_guard import allow as _budget_allow

        if not _budget_allow("coach_narrative"):
            raise RuntimeError("coach narrative AI paused by budget tier — using fallback")
        result = _call_haiku(
            system=SYSTEM_PROMPT,
            user_message=user_message,
            # 2026-05-28: was 2000 — too small. A full generation brief is
            # ~1800-3000 output tokens, so it truncated mid-JSON (stop_reason
            # max_tokens), failed to parse, and EVERY coach silently fell back
            # to the canned default brief while still paying for the wasted call.
            # 6000 gives headroom; you only pay for tokens actually generated.
            max_tokens=6000,
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
            logger.warning("LLM returned non-dict response for %s — attempting fallback", coach_id)
            brief = _load_fallback_brief(coach_id)
            if not brief:
                brief = _build_default_brief(coach_id, today)

    except Exception as e:
        logger.error("LLM call failed for %s: %s — attempting fallback", coach_id, e)
        brief = _load_fallback_brief(coach_id)
        if not brief:
            logger.warning("No fallback brief available — using default for %s", coach_id)
            brief = _build_default_brief(coach_id, today)

    # Inject the coach's current stance into the brief DETERMINISTICALLY (not via
    # the LLM) so its evolving read of Matthew reaches generation verbatim, on every
    # path including fallback/default. Absent pre-data — the coach then leans on its
    # goal framing as before (ai_calls.py). The brief flows verbatim into the coach
    # prompt, so this is the seam that closes the stance→generation loop.
    stance = state.get("current_stance")
    if stance and isinstance(brief.get("generation_brief"), dict):
        brief["generation_brief"]["current_stance"] = _stance_for_brief(stance)

    # Cache the brief for fallback use
    _cache_brief(coach_id, brief, today)

    logger.info("Narrative orchestrator complete for %s", coach_id)
    return brief
