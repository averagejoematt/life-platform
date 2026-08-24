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
import urllib.error
import urllib.request
from datetime import datetime, timezone

import boto3
from experiment.phase_filter import singleton_visible, with_phase_filter  # ADR-058 / #946 / #1969

from coach.persona_registry import OPERATIONAL_COACH_IDS

# Structured logger
try:
    from common.platform_logger import get_logger

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

# All coach IDs in the system — DERIVED from the canonical registry, never
# re-typed. persona_registry.OPERATIONAL_COACH_IDS is the list that MUST stay
# equal to the `operational: true` personas in config/personas.json (enforced by
# tests/test_persona_registry.py). This module's copy had already drifted in
# ORDER (nutrition/training transposed), and dispute_docket imports this name as
# its identity gate (#1797) — so a ninth operational coach added to the registry
# would have been invisible to the digest AND rejected from its own docket.
# A list() copy, not the registry object, so a caller mutating this name cannot
# corrupt every other consumer of the registry.
ALL_COACH_IDS = list(OPERATIONAL_COACH_IDS)

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

# ══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════════════════════


from common.numeric import (
    decimals_to_float as _decimal_to_float,  # noqa: E402,F401
    floats_to_decimal,  # noqa: E402  # canonical float->Decimal (#1207)
)


def _slugify(text):
    """Convert a topic string to a URL-safe slug for DynamoDB sort keys."""
    slug = text.lower().strip()
    slug = re.sub(r"[^a-z0-9]+", "_", slug)
    slug = slug.strip("_")
    return slug[:80] if slug else "unnamed"


# Canonical emitter lives in the layer — local copy removed 2026-06-12.
from common.retry_utils import _emit_token_metrics  # noqa: E402,F401

# #2419: the digest writer joins ADR-104's grounded-generation gate. The LLM-written
# disagreement `topic` is served VERBATIM as `cross_coach_reference` on
# /api/coach_analysis (site_api_coach_narrative), read by /api/coach_team's tension
# map (site_api_coach_stance._latest_cycle_digest), and rendered into the public
# Friday Panel script — with, until this gate, no grounding chokepoint anywhere in
# the module. Fails open (gate becomes a no-op) if the shared module is missing from
# the bundle — the summarizer's exact idiom; a gate must never sink the digest.
try:
    from ai.grounded_generation import allowed_dates, allowed_numbers, grounding_findings, regen_once
    from ai.grounding_gate_params import cycle_gate_params  # #1967 — the cycle anchors, one provider
except ImportError:  # pragma: no cover — environment-dependent
    allowed_dates = allowed_numbers = grounding_findings = regen_once = None

    def cycle_gate_params(generation_date_iso=None):  # type: ignore[misc]
        return {}


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


def _call_haiku(system, user_message, max_tokens=6000, temperature=0.2):
    """Call Anthropic Haiku with exponential backoff + CloudWatch metrics.

    Returns parsed JSON dict if the response is valid JSON, otherwise raw text.
    Raises on final failure after all retry attempts.
    """
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
            "anthropic-version": "2023-06-01",
            "anthropic-beta": "prompt-caching-2024-07-31",
        },
        method="POST",
    )

    # ADR-062 (2026-05-27): route through retry_utils.call_anthropic_raw, now
    # backed by Bedrock (was urllib → api.anthropic.com). Handles backoff +
    # token metrics + failure metric. `req` is still built above; the body is
    # extracted and forwarded to bedrock_client.invoke().
    from common.retry_utils import call_anthropic_raw

    resp = call_anthropic_raw(req)
    # An empty `content` list is what a max_tokens stop with no emitted text
    # looks like. Indexing [0] raised IndexError, which the handler's blanket
    # except swallowed into a fallback digest — the failure was real but
    # unnamed. Treat "no completion" as its own explicit outcome (ADR-104: a
    # failed model call must be distinguishable, never silently filed).
    content = (resp or {}).get("content") or []
    first = content[0] if content else None
    text = (first.get("text") or "").strip() if isinstance(first, dict) else ""
    if not text:
        logger.warning("ensemble model returned an empty completion — treating as no response")
        return ""
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
    """Get a single DynamoDB item. Returns None if not found, hidden, or on error.

    #1969 (#946 class): get_item bypasses the query-level phase filter, so a
    restart's tombstoned singletons (COMPRESSED#latest, ENSEMBLE#disagreements
    ACTIVE#) would keep feeding the wiped cycle's positions into fresh-cycle
    digests. singleton_visible mirrors the filter (orchestrator pattern);
    records with no phase attribute pass through unchanged."""
    try:
        resp = table.get_item(Key={"pk": pk, "sk": sk})
        item = resp.get("Item")
        if not singleton_visible(item):
            return None
        return _decimal_to_float(item)
    except Exception as e:
        logger.warning("get_item(%s, %s) failed: %s", pk, sk, e)
        return None


def _put_item(item):
    """Write an item to DynamoDB with float-to-Decimal conversion.

    ENSEMBLE#*/COACH#* rows are EXPERIMENT_SCOPED intelligence — stamp write-time
    provenance (phase + cycle, #1233). experiment_stamp() is fail-soft and cached;
    the item's own keys win, so it never clobbers or breaks the write.
    """
    from experiment.phase_taxonomy import experiment_stamp

    try:
        table.put_item(Item=floats_to_decimal({**experiment_stamp(), **item}))
        return True
    except Exception as e:
        logger.error("put_item failed for %s/%s: %s", item.get("pk"), item.get("sk"), e)
        return False


def _query_latest(pk, sk_prefix):
    """Query for the most recent item matching a SK prefix (descending, limit 1).

    ADR-058: phase-filtered (tombstoned items hidden).
    """
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
    "## Coach Absence Handling (Phase 3.7)\n\n"
    "If the user message lists coaches WITHOUT data this cycle:\n"
    "- Do NOT call any agreement 'unanimous' unless ALL expected coaches "
    "weighed in. Use 'majority' or 'partial consensus' when coaches are "
    "absent.\n"
    "- In `unanimous_flags`, only include items where every expected coach "
    "(including absent ones) is known to agree.\n"
    "- Mention the absence in the digest if it materially affects the "
    "interpretation.\n\n"
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
    '      "data_needed_to_resolve": "string",\n'
    '      "resolution_criterion": {"metric": "...", "condition": "gt|gte|lt|lte", "threshold": 0,'
    ' "resolution_days": 14, "sides": {"coach_a": true, "coach_b": false}}\n'
    "    }\n"
    "  ],\n"
    '  "unanimous_flags": ["..."]\n'
    "}\n\n"
    "## Dispute Docket criteria (#1386)\n\n"
    "If — and ONLY if — a disagreement can be settled by one of the platform's measurable "
    "metrics, attach a `resolution_criterion`: the metric key, a numeric threshold, a "
    "condition (gt/gte/lt/lte), `resolution_days` (3–90 days out), and `sides` mapping each "
    "of the two disputing coach ids to true (claims the condition WILL hold on the "
    "resolution date) or false (claims it will not). The two coaches MUST take opposite "
    "sides. Valid metric keys: {metric_keys} — each also gradable as a _7day_avg, "
    "_14day_avg, or _30day_avg aggregate. If no listed metric can grade the disagreement, "
    "set `resolution_criterion` to null: the disagreement stays narrative. Deterministic "
    "code validates and resolves every criterion — an invalid one is simply ignored, and "
    "no AI ever grades the outcome.\n\n"
    "No markdown wrapping, no explanation, no preamble. ONLY the JSON object."
)


def _ensemble_system_prompt():
    """The system prompt with the CURRENT measurable-metric vocabulary baked in —
    derived from measurable_metrics.METRIC_SOURCES (the evaluator's own source map,
    #1386) so the docket criteria the LLM may propose and the criteria code can
    grade cannot diverge."""
    try:
        from experiment.measurable_metrics import METRIC_SOURCES

        keys = ", ".join(sorted(METRIC_SOURCES))
    except Exception:
        keys = "(unavailable — propose no resolution_criterion this cycle)"
    return ENSEMBLE_SYSTEM_PROMPT.replace("{metric_keys}", keys)


def _build_user_message(coach_data, cycle_date, expected_coach_ids=None):
    """Build the user message containing all coaches' data for ensemble analysis.

    Phase 3.7 (2026-05-16): explicitly lists absent coaches so the synthesizer
    doesn't claim "unanimous agreement" when several coaches simply couldn't
    report. Previously the prompt listed only present coaches; LLM had no
    visibility into who was missing.
    """
    if expected_coach_ids is None:
        expected_coach_ids = ALL_COACH_IDS
    present_ids = list(coach_data.keys())
    absent_ids = [cid for cid in expected_coach_ids if cid not in present_ids]

    parts = [
        f"## Ensemble Digest Cycle: {cycle_date}",
        f"## Coaches with data: {len(coach_data)}/{len(expected_coach_ids)}",
    ]
    if absent_ids:
        parts.append(f"## Coaches WITHOUT data this cycle: {', '.join(absent_ids)}")
        parts.append(
            "## IMPORTANT: Do NOT claim 'unanimous agreement' on topics where "
            "these absent coaches would have weighed in. Adjust confidence and "
            "synthesis to reflect missing voices."
        )
    parts.append("")

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
            filtered = {k: v for k, v in compressed.items() if k not in ("pk", "sk")}
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

        # Reader/writer agreement: the ONLY writer of COACH#*/COMPRESSED#latest is
        # coach_history_summarizer, whose schema stores `key_concerns`,
        # `key_recommendations` and `recent_themes` — it has never written
        # `key_themes` (that name is an in-memory default the narrative
        # orchestrator synthesises for a coach with NO compressed state; it is
        # never persisted). Reading `key_themes` here made the fallback's
        # key_concerns permanently [] while the data it wanted sat unread in the
        # record it had just fetched — and `ensemble` is a band-1 budget feature,
        # so the fallback is the common path, not the rare one.
        summary = {
            "coach_id": coach_id,
            "key_concerns": (compressed.get("key_concerns") or [])[:3],
            "key_recommendations": (compressed.get("key_recommendations") or [])[:3],
            "predictions_active": [],
            "confidence_state": compressed.get("confidence_state", {}),
            "wants_team_input_on": [],
        }

        # Pull predictions from output if available
        preds = output.get("predictions_made", [])
        if isinstance(preds, list):
            summary["predictions_active"] = [p.get("claim_natural", str(p)) if isinstance(p, dict) else str(p) for p in preds[:3]]

        coach_summaries.append(summary)

    return {
        "coach_summaries": coach_summaries,
        "active_disagreements": [],
        "unanimous_flags": [],
        "_fallback": True,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


# ══════════════════════════════════════════════════════════════════════════════
# GROUNDING GATE (#2419 / ADR-104)
# ══════════════════════════════════════════════════════════════════════════════


def _digest_prose_blob(digest):
    """JSON blob of only the digest's reader-bound PROSE fields, for the ADR-104 gate.

    Deliberately excluded:
      * `resolution_criterion` — a model-PROPOSED docket criterion whose numeric
        threshold is validated (and discarded when invalid) by dispute_docket's
        deterministic gate (#1386); its threshold is a proposal by design, not a
        data claim, so the numbers gate would false-flag every honest criterion.
      * `confidence_state` — structure echoed from the coaches' own stored records,
        not free prose.
      * bookkeeping (`created_at`, `docket`, `_fallback`) — timestamps and counters
        the gate must never grade (the summarizer's `_stance_prose_blob` rule).
    """
    disagreements = [
        {
            "topic": d.get("topic", ""),
            "positions": d.get("positions", {}),
            "data_needed_to_resolve": d.get("data_needed_to_resolve", ""),
        }
        for d in digest.get("active_disagreements", [])
        if isinstance(d, dict)
    ]
    summaries = [
        {
            "key_concerns": s.get("key_concerns", []),
            "key_recommendations": s.get("key_recommendations", []),
            "predictions_active": s.get("predictions_active", []),
            "wants_team_input_on": s.get("wants_team_input_on", []),
        }
        for s in digest.get("coach_summaries", [])
        if isinstance(s, dict)
    ]
    return json.dumps(
        {
            "coach_summaries": summaries,
            "active_disagreements": disagreements,
            "unanimous_flags": digest.get("unanimous_flags", []),
        },
        default=str,
    )


def _apply_grounding_gate(digest, user_message):
    """#2419: the ADR-104 grounded-generation gate joins the digest writer.

    grounding_findings() runs the shared allow-list number + fabricated-date +
    cycle-freshness checks over the digest's reader-bound prose fields, with the
    digest's OWN inputs (`user_message` — exactly what the model saw) as the
    allow-list. One corrective regen via the shared regen_once harness — the
    summarizer/analyzer pattern, reused rather than reinvented. Findings that
    survive the one regen are returned to the caller, which HOLDS: the handler
    replaces the model digest with the deterministic `_build_default_digest`
    fallback, so text that failed the gate is never persisted and
    site_api_coach_stance / the Friday Panel never serve it.

    Returns (digest, findings). Fail-open when the shared module is unavailable —
    matches the module's own design and the summarizer's idiom.
    """
    if grounding_findings is None or regen_once is None or allowed_numbers is None:
        return digest, []  # shared module unavailable — fail-open, matches its own design

    allowed = allowed_numbers(user_message)
    # The digest's allow-list source (`user_message`) is exactly what the model saw,
    # so the date gate is built from the same material; the cycle anchors arm the
    # phase-aware classes (#1691/#1897) — a digest topic narrating a stale "Day N"
    # is the same failure class as a fabricated number.
    _dates = allowed_dates(user_message) if allowed_dates is not None else None
    holder = {"latest": digest}

    def _findings_fn(text):
        return grounding_findings(
            text,
            facts=None,
            allowed=allowed,
            allowed_dates=_dates,
            **cycle_gate_params(),
        )

    def _regen_fn(correction):
        strict_message = user_message + "\n\n" + correction
        retry = _call_haiku(
            system=_ensemble_system_prompt(),
            user_message=strict_message,
            max_tokens=6000,
            temperature=0.2,
        )
        if not isinstance(retry, dict):
            return ""
        candidate = {
            "coach_summaries": retry.get("coach_summaries", []),
            "active_disagreements": retry.get("active_disagreements", []),
            "unanimous_flags": retry.get("unanimous_flags", []),
            "created_at": digest.get("created_at"),
        }
        holder["latest"] = candidate
        return _digest_prose_blob(candidate)

    text = _digest_prose_blob(digest)
    _best_text, findings, corrected = regen_once(text, _findings_fn, _regen_fn, surface="coach_ensemble_digest")
    best = holder["latest"] if corrected else digest
    return best, findings


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


def _next_cycle_count(existing, cycle_date):
    """How many distinct cycles this disagreement has persisted for.

    Idempotent in `cycle_date`: writing the same cycle again — a retry, a
    duplicate EventBridge delivery, or a second topic in the same run whose
    slug collides — re-states the count rather than advancing it.
    """
    stored = existing.get("cycle_count") or 0
    try:
        stored = int(stored)
    except (TypeError, ValueError):
        stored = 0
    if existing.get("last_cycle_date") == cycle_date:
        return max(stored, 1)
    return stored + 1


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

        # #1797's identity gate, on THIS writer too. dispute_docket got it; the
        # sibling writer on the same LLM input did not — and this partition is
        # the one emails/podcast_script_v2 renders into the public Friday Panel
        # script, so an invented coach id or a display name written where a
        # canonical id belongs reaches a reader surface (ADR-104). Same rule as
        # open_from_disagreements: two coaches minimum, every one of them a
        # member of the house roster, checked before anything is stored.
        coaches = [c for c in (disagreement.get("coaches") or []) if c]
        non_members = [c for c in coaches if c not in ALL_COACH_IDS]
        if len(coaches) < 2 or non_members:
            logger.warning(
                "Dropping disagreement %r — %s",
                topic,
                f"non-member coach id(s) {non_members!r}" if non_members else "fewer than two coaches named",
            )
            continue

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
                # `cycle_count` is published verbatim by the Friday Panel as
                # "OPEN ARGUMENT (cycle_count N)" — a claim about how many
                # cycles the coaches have been arguing. It must count CYCLES,
                # not writes. `last_cycle_date` was stored one line below and
                # never read, so a retry, a manual re-invoke, an EventBridge
                # duplicate delivery — or two topics in ONE run that slugify
                # alike — each inflated a public number (ADR-104).
                "cycle_count": _next_cycle_count(existing, cycle_date),
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

        # #1386: carry the PROPOSED docket criterion through — dispute_docket's
        # deterministic gate (not this writer) decides whether it opens a docket.
        if isinstance(disagreement.get("resolution_criterion"), dict):
            item["resolution_criterion"] = disagreement["resolution_criterion"]

        if _put_item(item):
            written += 1

    logger.info("Wrote %d disagreement records for cycle %s", written, cycle_date)
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

        # ADR-104: COMPRESSED#latest is dumped verbatim into the NEXT cycle's
        # ensemble prompt (_build_user_message) and into the coach's own memory
        # block on the website (site_api_ai_lambda). On a budget-paused or
        # LLM-failed cycle the digest marks itself `_fallback` but this write-back
        # did not, so a stub was replayed as the ensemble's genuine finding —
        # and since `ensemble` is band-1, that is the common path. Carry the
        # marker with the contribution, the same way the digest carries it.
        if digest.get("_fallback"):
            contribution["_fallback"] = True

        # Find disagreements involving this coach
        involved_disagreements = []
        for d in digest.get("active_disagreements", []):
            if coach_id in d.get("coaches", []):
                involved_disagreements.append(
                    {
                        "topic": d.get("topic", ""),
                        "with_coaches": [c for c in d.get("coaches", []) if c != coach_id],
                        "my_position": d.get("positions", {}).get(coach_id, ""),
                    }
                )
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
        cycle_date,
        len(coach_ids),
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
            # Every other empty-digest path in this module marks itself; this one
            # was the outlier, carrying only a prose `note` no consumer parses.
            # site_api_coach_stance._latest_cycle_digest and
            # coach_observatory_renderer both take the NEWEST CYCLE# row, so an
            # empty digest shadows the previous cycle's real cross-coach content.
            # The marker is what lets a reader (or a future renderer) tell the
            # two apart — see the PR note: the renderers do not check it YET.
            "_fallback": True,
        }
        _write_digest(digest, cycle_date)
        return _decimal_to_float(digest)

    logger.info(
        "Gathered data from %d/%d coaches: %s",
        len(coach_data),
        len(coach_ids),
        list(coach_data.keys()),
    )

    # Step 2: Call Haiku to produce the ensemble digest
    # Phase 3.7: pass expected coach_ids so the synthesizer knows who's absent.
    user_message = _build_user_message(coach_data, cycle_date, expected_coach_ids=coach_ids)

    try:
        # Budget guardrail: at Tier ≥ 1 skip the LLM and use the default digest.
        from ai.budget_guard import allow as _budget_allow

        if not _budget_allow("ensemble"):
            raise RuntimeError("ensemble digest AI paused by budget tier — using fallback")
        result = _call_haiku(
            system=_ensemble_system_prompt(),
            user_message=user_message,
            # 2026-05-28: was 2000 — occasionally truncated the digest JSON
            # (7 parse-fails/48h) → fell back. Same bug class as the orchestrator.
            max_tokens=6000,
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

            # #2419 / ADR-104: gate the reader-bound prose against the digest's own
            # inputs. Regenerate ONCE; findings that survive HOLD the model digest —
            # the deterministic fallback (built from the coaches' stored, already-
            # gated records) is what persists, never text that failed the gate.
            digest, adr104_findings = _apply_grounding_gate(digest, user_message)
            if adr104_findings:
                logger.warning(
                    "Ensemble digest failed the ADR-104 grounding gate after one regen "
                    "(%d findings: %s) — holding; writing the deterministic fallback digest",
                    len(adr104_findings),
                    [f.get("type") for f in adr104_findings],
                )
                digest = _build_default_digest(coach_data, cycle_date)
                # Distinguish a grounding HOLD from a budget/LLM-failure fallback so
                # an operator reading the stored digest can tell which path ran.
                digest["_grounding_hold"] = True
        else:
            logger.warning("LLM returned non-dict response — using fallback digest")
            digest = _build_default_digest(coach_data, cycle_date)

    except Exception as e:
        logger.error("LLM call failed: %s — using fallback digest", e)
        digest = _build_default_digest(coach_data, cycle_date)

    # Step 3: Write/update disagreement records
    #
    # This runs BEFORE the digest write on purpose. The docket pass below mutates
    # `digest["docket"]`, and while it ran after _write_digest that field existed
    # only in the Lambda's return value — an operator reading the stored digest
    # could not tell whether the docket pass had run at all. Both writers are
    # fail-soft, so nothing here can stop the digest from being stored.
    disagreements = digest.get("active_disagreements", [])
    if disagreements:
        _write_disagreements(disagreements, cycle_date)

        # Step 3b (#1386): open Dispute Docket entries for machine-checkable
        # divergences. dispute_docket.validate_criterion is the deterministic
        # gate; non-resolvable disagreements stay narrative. Fail-soft — a
        # docket error must never sink the digest.
        try:
            from coach import dispute_docket

            docket_stats = dispute_docket.open_from_disagreements(disagreements, cycle_date)
            digest["docket"] = {
                "opened": len(docket_stats.get("opened", [])),
                "skipped": len(docket_stats.get("skipped", [])),
            }
        except Exception as e:
            logger.warning("dispute-docket open pass failed (non-fatal): %s", e)

    # Step 4: Write the digest — with the docket outcome, when there was one
    _write_digest(digest, cycle_date)

    # Step 5: Update each coach's compressed state with digest contribution
    _update_coach_compressed_states(digest, coach_data, cycle_date)

    logger.info("Ensemble digest complete for cycle %s", cycle_date)
    return _decimal_to_float(digest)
