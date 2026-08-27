"""
coach_quality_gate.py — Coach Intelligence: Post-Generation Quality Gate

Haiku-based check that validates coach output quality after generation. This
Lambda is a pure scorer — it always returns a report and never blocks anything
itself; whether a report's `passed=False` verdict actually blocks publication
is the caller's decision.

N-06 (#390, 2026-07-05): the daily-brief caller (`ai_calls._run_coach_v2_pipeline`)
now invokes this Lambda synchronously (RequestResponse, was fire-and-forget
Event) and enforces the verdict — regenerate once, then hold rather than
publish a known-failing draft. See ADR-107 for the measured re-evaluation that
justified the promotion and `ai_calls._enforce_quality_gate` for the
regenerate-or-hold state machine. This module's own logic (scoring, thresholds,
fallback-on-LLM-failure) is unchanged — it remains advisory from its own
point of view; only the caller's handling changed.

Checks:
  1. Anti-pattern violations — output vs voice spec phrase_blacklist & structural_blacklist
  2. Decision class compliance — does the output exceed the evidence ceiling?
  3. Voice distinctiveness — does the output match the coach's structural signature?
  4. Cross-coach similarity — does this output sound too similar to other coaches?
  5. Fabricated / ungrounded numbers (#2573, ADR-104/105) — deterministic, NO LLM,
     and BLOCKING. The rubric used to have no rule about invented numbers at all,
     so the blocking gate could not fail a brief for making one up: measured
     2026-08-11, all three fabricated-number canaries scored 92/92/82 and PASSED.
     The fix does not ask the LLM to judge arithmetic in prose — it CONSUMES the
     ADR-104 deterministic verdict (`grounded_generation.grounding_findings`
     against the caller-supplied allow-list) computed BEFORE the LLM call, injects
     it into the rubric as an already-decided input, and forces `passed=False`
     when it fires. Honest absence: no allow-list on the wire ⇒ verdict None,
     advisory, never a green.
  6. Self-repetition (#2350, ADR-105) — deterministic, NO LLM: the candidate is
     scored against this coach's own trailing OUTPUT# history by
     `coach.coach_repetition_detector` (shingle Jaccard, personal-variance
     threshold) BEFORE the LLM verdict. Attached as the advisory `repetition`
     section of the report; never affects `passed` (ADR-108 promotion pattern —
     advisory until the flag rate is measured on real outputs).

Returns a quality report with pass/fail, score, and detailed findings.

DynamoDB patterns: reads only (no writes)
  PK=COACH#{coach_id}  SK=VOICE#state
  PK=COACH#{coach_id}  SK=OUTPUT#*  (recent outputs for cross-coach comparison)

S3: config/coaches/{coach_id}.json (voice spec)

v1.0.0 — 2026-04-06 (Coach Intelligence)
v1.1.0 — 2026-07-05 (N-06, #390): caller-side promotion to blocking; no change to
         this module's own scoring logic.
"""

import json
import logging
import os
import urllib.error
import urllib.request

import boto3

# #2573: the deterministic grounding context's key names — defined once, in the wire
# contract, so the caller that attaches them and the gate that reads them cannot drift.
from ai.quality_gate_contract import AUTHORITATIVE_FACTS_KEY, GROUNDING_ALLOWLIST_KEY
from experiment.phase_filter import singleton_visible, with_phase_filter  # ADR-058 / #946 / #1969

# Structured logger
try:
    from common.platform_logger import get_logger

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

# #2893 — the report did not fit in the cap it was given (the #2668 class).
# MEASURED 30d to 2026-08-23 from CloudWatch:
#   • 84 of 484 metered calls (17.4%) logged `Quality gate LLM returned non-dict
#     for … — using fallback`; the fallback is `_build_fallback_report`, which
#     returns passed=True. Chronic — it fired on 24 of the 30 days.
#   • LifePlatform/AI AnthropicOutputTokens for coach-quality-gate: Maximum ==
#     800.0 exactly (Average 632, n=484). Over the trailing 14d, ≥55 of 175 calls
#     (31.4%) ended at the cap — i.e. billed in full, then discarded.
# Truncation censors the length the report actually wants, so the new cap is sized
# by the #2668 precedent (600 → 1500 ≈ 2.5× the observed ceiling) rather than the
# next round number. The residual is no longer a hand audit: bedrock_client emits
# LifePlatform/AI TruncatedResponses whenever stop_reason == "max_tokens".
QUALITY_GATE_MAX_TOKENS = 2000

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

# ══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════════════════════


from common.numeric import decimals_to_float as _decimal_to_float  # noqa: E402,F401

# Canonical emitter lives in the layer — local copy removed 2026-06-12.
from common.retry_utils import _emit_token_metrics  # noqa: E402,F401


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


def _call_haiku(system, user_message, max_tokens=QUALITY_GATE_MAX_TOKENS, temperature=0.1):
    """Call Anthropic Haiku with exponential backoff + CloudWatch metrics.

    Returns parsed JSON dict if the response is valid JSON, otherwise raw text.
    Raises on final failure after all retry attempts.

    #2893 (2026-08-23): the cap was 800 and the report did not fit in it — see
    QUALITY_GATE_MAX_TOKENS for the measurement.
    """
    body = {
        "model": AI_MODEL_HAIKU,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "messages": [{"role": "user", "content": user_message}],
    }
    if system:
        # #3085: this `cache_control` is a NO-OP and that is the measured decision, not an
        # oversight — QUALITY_GATE_SYSTEM_PROMPT is 814 tok against Haiku 4.5's 4,096 floor,
        # and the largest legitimate prefix available (hoisting the whole shared standard in)
        # is 2,238 tok, still 55% of the way. Closing that gap means padding a quality-JUDGE
        # prompt with ~1,858 tok of filler to win $0.29/mo across both coach callers. Left on
        # deliberately: an ignored marker costs nothing and engages for free if the prompt ever
        # grows on its merits. See ai.prompt_cache.CACHING_DECISIONS; the live proof that it is
        # still a no-op is the `PromptCacheNoOp` metric (#2888), not this line.
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

    # ADR-062 (2026-05-27): route through retry_utils.call_anthropic_raw, which
    # now executes via Bedrock (was urllib → api.anthropic.com). It handles
    # backoff + token metrics + failure metric, so the old per-attempt loop +
    # urllib except handlers are gone. `req` is still built above; call_anthropic_raw
    # extracts its JSON body and forwards to bedrock_client.invoke().
    from common.retry_utils import call_anthropic_raw

    resp = call_anthropic_raw(req)
    text = resp["content"][0]["text"].strip()
    # Try to parse as JSON
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Try extracting JSON from markdown code block
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
# DYNAMODB / S3 OPERATIONS
# ══════════════════════════════════════════════════════════════════════════════


def _get_item(pk, sk):
    """Get a single DynamoDB item. Returns None if not found, hidden, or on error.

    #1969 (#946 class): no current caller, but this is the module's canonical
    singleton read path — guarded so a future read can't reintroduce the
    tombstone-blind class. singleton_visible mirrors the query-level phase
    filter (orchestrator pattern); records with no phase attribute pass
    through unchanged."""
    try:
        resp = table.get_item(Key={"pk": pk, "sk": sk})
        item = resp.get("Item")
        if not singleton_visible(item):
            return None
        return _decimal_to_float(item)
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
            resp = table.query(**with_phase_filter(kwargs))
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


def _self_repetition_report(coach_id, output_text):
    """Deterministic self-repetition detector (#2350, ADR-105).

    Scores the candidate against this coach's OWN trailing OUTPUT# history via
    plain-code shingle similarity (coach_repetition_detector) — computed before
    and independently of the LLM verdict, no AI call, so it runs identically at
    every budget tier. Advisory: the section is attached to the report and never
    flips `passed` (ADR-108 posture — measure the flag rate before promoting).

    Fail-soft: any failure returns verdict=None with status="error" — a missing
    verdict is absence, never a green "no repetition".
    """
    try:
        from common.pacific_time import pacific_today

        from coach import coach_repetition_detector as repdet

        # A candidate too short to ever earn a verdict shouldn't cost a DDB read.
        precheck = repdet.detect(output_text, [])
        if precheck.get("status") == "insufficient_text":
            return precheck

        items = _query_begins_with(
            f"COACH#{coach_id}",
            "OUTPUT#",
            scan_forward=False,
            limit=repdet.TRAILING_WINDOW + 1,
        )
        # #2815: the OUTPUT# frame, consumer side — converted atomically with every
        # writer. This ONLY excludes THIS run's own same-day draft from the
        # repetition history — it does not judge day-phase content. Every OUTPUT#
        # writer keys the sk from the SAME `common.pacific_time.pacific_today()` now
        # (ai_calls.py's coach-state-updater invoke — both the fresh-generation and
        # cache-reuse writes, coach_state_updater.py's own no-generation_date
        # fallback, inter_coach_dialogue_lambda.py's writer), so producer and
        # consumer keep sharing one frame — Pacific, not naive UTC. The old
        # `utc-exempt(#2815)` marker here is retired: the marker existed because
        # converting this ONE read in isolation would have desynced it from the sk
        # it matches against; the fix converts the whole set together instead.
        today = pacific_today()
        history = []
        for it in items:
            sk = it.get("sk", "")
            content = it.get("content") or ""
            # A same-day record with byte-identical content is this run's own
            # already-published draft (gate re-run), not an earlier output.
            if content == output_text and sk.startswith(f"OUTPUT#{today}"):
                continue
            history.append({"id": sk, "content": content})
        return repdet.detect(output_text, history)
    except Exception as e:
        logger.warning("repetition detector failed for %s (advisory, fail-soft): %s", coach_id, e)
        return {"status": "error", "verdict": None, "error": str(e), "advisory": True}


def _number_grounding_report(output_text, generation_brief, generation_date=None):
    """Deterministic fabricated-number verdict (#2573, ADR-104/105) — no LLM.

    CONSUMES the platform's existing deterministic grounder rather than re-deciding
    the number question in the judge's prose. `grounded_generation.grounding_findings`
    is the same function the generation path's ADR-104 gate and the golden-brief eval
    already run, so the quality gate and the honesty gate cannot disagree by
    construction.

    Grounding context arrives inside the brief (see
    `ai.quality_gate_contract.brief_with_grounding`): the caller's already-computed
    numeric allow-list, plus the canonical facts for the RHR/recovery/HRV
    contradiction check. The gate cannot derive the allow-list itself — it is built
    from the assembled generation prompt, which never crosses the wire.

    Fail-soft in BOTH honest directions:
      * no allow-list on the wire  -> status="no_grounding_context", verdict=None.
        Absence, not a pass. This is what an un-upgraded caller gets, and it leaves
        the gate exactly as (in)effective as it was before #2573 — never worse.
      * detector raised            -> status="error", verdict=None.
    Only status="measured" with findings blocks.
    """
    brief = generation_brief if isinstance(generation_brief, dict) else {}
    if GROUNDING_ALLOWLIST_KEY not in brief:
        return {
            "status": "no_grounding_context",
            "verdict": None,
            "advisory": True,
            "detail": (
                "caller supplied no numeric allow-list "
                f"(generation_brief.{GROUNDING_ALLOWLIST_KEY}) — the number check did not run. "
                "This is honest absence, not a clean verdict."
            ),
        }
    try:
        from ai import grounded_generation as _gg
        from ai.grounding_gate_params import cycle_gate_params

        allowed = {float(n) for n in (brief.get(GROUNDING_ALLOWLIST_KEY) or [])}
        facts = brief.get(AUTHORITATIVE_FACTS_KEY) or {}
        # #1967 policy floor: the cycle-freshness classes are framing-scoped and free,
        # and have no valid exemption. The event carries the generation date, so this
        # surface grades the draft's "Day N" framing against the same anchors the
        # generation gate used rather than against today.
        findings = _gg.grounding_findings(output_text, facts=facts or None, allowed=allowed, **cycle_gate_params(generation_date))
        return {
            "status": "measured",
            "verdict": "ungrounded" if findings else "clean",
            "findings": findings,
            "n_findings": len(findings),
            "n_allowed": len(allowed),
        }
    except Exception as e:
        logger.warning("number-grounding detector failed (fail-soft, no verdict): %s", e)
        return {"status": "error", "verdict": None, "advisory": True, "error": str(e)}


def _grounding_findings_summary(grounding, max_findings=6, detail_cap=220):
    """Render the grounding verdict's finding TYPES + DETAILS for the log line (#3202).

    Returns "" when there is nothing to say (clean, or the check did not run), so the
    COMPLETE line is byte-identical to its pre-#3202 form on a passing draft and the
    30-day CloudWatch re-eval queries that parse it keep working. On a hold it appends
    `, grounding_findings=[stale_phase: …]` — the detail the operator previously had to
    re-run the gate to see.
    """
    if not isinstance(grounding, dict):
        return ""
    if grounding.get("status") != "measured":
        # Honest absence is worth naming too — "no_grounding_context" and "clean" are
        # very different states behind the same `verdict=None`/`verdict=clean` word.
        detail = grounding.get("error") or grounding.get("detail")
        return f", grounding_status={grounding.get('status')}" + (f" ({str(detail)[:detail_cap]})" if detail else "")
    findings = grounding.get("findings") or []
    if not findings:
        return ""
    parts = []
    for f in findings[:max_findings]:
        if not isinstance(f, dict):
            continue
        parts.append(f"{f.get('type')}: {str(f.get('detail') or '')[:detail_cap]}")
    if len(findings) > max_findings:
        parts.append(f"(+{len(findings) - max_findings} more)")
    return ", grounding_findings=[" + " | ".join(parts) + "]"


def _number_grounding_block(grounding):
    """Render the deterministic verdict for the judge prompt — as a DECIDED input,
    not a question. The judge is told the answer and told not to re-litigate it."""
    status = grounding.get("status")
    if status != "measured":
        return (
            "## Number Grounding (deterministic verdict)\n"
            "  UNAVAILABLE — the deterministic number check did not run for this draft.\n"
            "  Do not guess. Say nothing about invented numbers; report only what criteria 1-4 support.\n"
        )
    findings = grounding.get("findings") or []
    if not findings:
        return (
            "## Number Grounding (deterministic verdict)\n"
            f"  CLEAN — every number in the output was matched against the {grounding.get('n_allowed', 0)} "
            "numbers the coach was actually given. Do NOT raise number complaints of your own.\n"
        )
    lines = [
        "## Number Grounding (deterministic verdict — ALREADY DECIDED)",
        f"  FAILED — {len(findings)} finding(s). This output states figures that are not in its evidence:",
    ]
    for f in findings[:8]:
        if isinstance(f, dict):
            lines.append(f"    - [{f.get('type', 'finding')}] {f.get('detail', '')}")
    lines.append("  This verdict is computed by deterministic code, not by you. Do not re-derive it and do not")
    lines.append('  argue with it: set "passed": false and score the output no higher than 40.')
    return "\n".join(lines) + "\n"


def _fetch_other_coaches_recent_outputs(coach_id, other_coach_ids=None):
    """Fetch the most recent output from other coaches for cross-coach comparison.

    Returns a dict of {coach_id: output_content_preview}.
    """
    # Derived from the canonical persona registry, never re-typed (#2334; guard:
    # tests/test_coach_roster_set_guard_2334.py).
    from coach.persona_registry import OPERATIONAL_COACH_IDS

    all_coach_ids = list(OPERATIONAL_COACH_IDS)

    if other_coach_ids:
        compare_ids = other_coach_ids
    else:
        compare_ids = [c for c in all_coach_ids if c != coach_id]

    other_outputs = {}
    for other_id in compare_ids:
        outputs = _query_begins_with(
            f"COACH#{other_id}",
            "OUTPUT#",
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
    "### 5. Fabricated / Ungrounded Numbers (BLOCKING — deterministic input)\n"
    "The single failure class this platform cares most about (ADR-104: honest "
    "numbers): the output states a figure — a vital, a weight, a trend endpoint, a "
    "range — that appears nowhere in the evidence the coach was given, or that "
    "contradicts the authoritative reading.\n"
    "This criterion is NOT yours to decide in prose. Deterministic code has already "
    "resolved it and its verdict is supplied under 'Number Grounding' in the message "
    "below (ADR-105: deterministic computation before any LLM verdict). Your job is "
    "to REPORT that verdict, never to re-derive or override it:\n"
    '  - Verdict FAILED -> return "passed": false and a score no higher than 40, '
    "and list each finding under number_grounding_violations. A fabricated number is "
    "disqualifying on its own, however good the voice is.\n"
    "  - Verdict CLEAN -> the numbers are grounded. Do not invent a number complaint.\n"
    "  - Verdict UNAVAILABLE -> the check did not run. Say nothing about numbers; "
    "do not guess, and do not treat silence as clean.\n\n"
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
    '  "number_grounding_violations": [\n'
    '    {"detail": "restate the deterministic finding verbatim"}\n'
    "  ],\n"
    '  "suggestions": ["actionable suggestions for improvement"]\n'
    "}\n"
)


def _shared_blacklists():
    """The substrate's banned phrases/structures (config/coaches/_shared_standard.json).

    Fail-soft ([], []) — a coach whose own blacklist loads must never lose its
    gate because the shared file is unreadable.
    """
    try:
        from coach.persona_core import load_voice_spec

        std = load_voice_spec("_shared_standard") or {}
        return (
            [str(p) for p in std.get("shared_phrase_blacklist") or []],
            [str(s) for s in std.get("shared_structural_blacklist") or []],
        )
    except Exception:
        return [], []


def _build_quality_gate_message(coach_id, output_text, voice_spec, generation_brief, other_outputs=None, grounding=None):
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

    # #2573: the deterministic number verdict goes in FIRST, before the stylistic
    # material, because it is the one criterion the judge must not reason its way
    # out of. Always rendered — including UNAVAILABLE — so silence is never mistaken
    # for a clean bill.
    parts.append(_number_grounding_block(grounding or {}))

    # Voice spec anti-patterns + the MOS shared avoid-list (every coach inherits
    # the substrate's banned clichés on top of their own list — the shared
    # standard's "communication avoid" made concrete and enforceable).
    anti_patterns = voice_spec.get("anti_pattern_detection", {})
    shared_phrases, shared_structural = _shared_blacklists()
    phrase_bl = list(anti_patterns.get("phrase_blacklist", [])) + [
        p for p in shared_phrases if p not in anti_patterns.get("phrase_blacklist", [])
    ]
    structural_bl = list(anti_patterns.get("structural_blacklist", [])) + [
        s for s in shared_structural if s not in anti_patterns.get("structural_blacklist", [])
    ]
    if phrase_bl or structural_bl:
        parts.append("## Anti-Pattern Checklist")
        if phrase_bl:
            parts.append("### Forbidden Phrases")
            for phrase in phrase_bl:
                parts.append(f'  - "{phrase}"')
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

    parts.append("Evaluate the output above against all four criteria. " "Return ONLY valid JSON with the quality report.")

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


# #3202: the finding types that really are about a digit. Everything else the
# deterministic grounder emits is a framing/behaviour class riding the same report.
_NUMERIC_FINDING_TYPES = frozenset({"fabricated_number", "contradiction", "band_contradiction", "night_value_mismatch"})


def _apply_number_grounding_verdict(result, grounding):
    """Consume the deterministic verdict (#2573) — the LLM cannot overrule it.

    The prompt asks the judge to report the verdict; this makes it structural. A
    judge that ignores criterion 5 (or a future prompt edit that drops it) still
    cannot ship a draft the deterministic grounder failed. Mirrors #1973's
    cycle-boundary rule: one report, one regenerate-or-hold path, no parallel
    enforcement mechanism.
    """
    if grounding.get("status") != "measured":
        return result
    findings = grounding.get("findings") or []
    if not findings:
        return result
    result["passed"] = False
    result["number_grounding_violations"] = [{"type": f.get("type"), "detail": f.get("detail")} for f in findings if isinstance(f, dict)]
    for f in result["number_grounding_violations"]:
        # Rendered into the corrective-rewrite note by ai_calls._quality_gate_correction_note,
        # which already walks `suggestions` — so the regeneration loop gets the specific
        # number complaint without ai_calls learning a new field.
        # #3202: only the digit classes are "ungrounded numbers". The freshness
        # classes (stale_phase / stale_baseline / experiment_span) and the behavioural
        # ones are framing errors, and telling a coach its phase framing was an
        # ungrounded NUMBER sent every corrective rewrite hunting a figure that was
        # never wrong — measured on the 2026-08-26 nutrition/mind holds.
        label = "Ungrounded number" if f.get("type") in _NUMERIC_FINDING_TYPES else "Grounding violation"
        msg = f"{label} ({f.get('type')}): {f.get('detail')}"
        if msg not in result.get("suggestions", []):
            result.setdefault("suggestions", []).append(msg)
    return result


def _run_quality_gate(coach_id, output_text, voice_spec, generation_brief, other_outputs=None, grounding=None):
    """Run the quality gate check via Haiku.

    Returns the quality report dict.
    """
    grounding = grounding or {}
    user_message = _build_quality_gate_message(
        coach_id,
        output_text,
        voice_spec,
        generation_brief,
        other_outputs,
        grounding=grounding,
    )

    try:
        result = _call_haiku(
            system=QUALITY_GATE_SYSTEM_PROMPT,
            user_message=user_message,
            max_tokens=QUALITY_GATE_MAX_TOKENS,
            temperature=0.1,
        )

        if not isinstance(result, dict):
            logger.warning("Quality gate LLM returned non-dict for %s — using fallback", coach_id)
            return _apply_number_grounding_verdict(_build_fallback_report(coach_id, "LLM returned non-JSON"), grounding)

        # Ensure required fields with defaults
        result.setdefault("passed", True)
        result.setdefault("score", 50)
        result.setdefault("anti_pattern_violations", [])
        result.setdefault("decision_class_violations", [])
        result.setdefault("voice_distinctiveness_score", 50)
        result.setdefault("cross_coach_similarity_flags", [])
        result.setdefault("suggestions", [])

        # #2573: the deterministic verdict is applied to the report structurally,
        # BEFORE the score threshold — a fabricated number blocks whatever the model
        # scored (measured: 92/92/82 with passed=true on the three canaries).
        _apply_number_grounding_verdict(result, grounding)

        # Apply pass/fail logic based on score and violations
        # Even if LLM said "passed", override based on thresholds
        if isinstance(result["score"], (int, float)):
            if result["score"] < PASS_SCORE_THRESHOLD:
                result["passed"] = False
        if result.get("voice_distinctiveness_score", 100) < VOICE_DISTINCTIVENESS_MINIMUM:
            if "Voice distinctiveness below minimum threshold" not in result.get("suggestions", []):
                result["suggestions"].append("Voice distinctiveness below minimum threshold")

        logger.info(
            "Quality gate for %s: passed=%s, score=%s, violations=%d, " "voice_score=%s, similarity_flags=%d",
            coach_id,
            result["passed"],
            result["score"],
            len(result.get("anti_pattern_violations", [])) + len(result.get("decision_class_violations", [])),
            result["voice_distinctiveness_score"],
            len(result.get("cross_coach_similarity_flags", [])),
        )

        return result

    except Exception as e:
        logger.error("Quality gate LLM call failed for %s: %s", coach_id, e)
        # Deterministic-first (ADR-105): a fabricated number the grounder already
        # caught still blocks even when the judge is unreachable. The permissive
        # fallback exists for the LLM's opinion, not for the arithmetic.
        return _apply_number_grounding_verdict(_build_fallback_report(coach_id, str(e)), grounding)


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

    Returns the quality report dict. This Lambda itself never blocks output —
    it only scores and flags issues. As of N-06 (#390), the daily-brief caller
    (`ai_calls._enforce_quality_gate`) DOES act on `passed=false`: it retries
    generation once, and only publishes a passing draft (holds otherwise).
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
            coach_id,
            len(output_text),
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

        # #2350 — deterministic self-repetition check FIRST (ADR-105: computed
        # before any LLM verdict). Advisory section; never affects `passed`.
        repetition = _self_repetition_report(coach_id, output_text)

        # #2573 — deterministic number grounding, also BEFORE the LLM. Unlike
        # repetition this one is BLOCKING: it is the ADR-104 verdict, and the LLM
        # is handed it as a decided input rather than asked to re-decide it.
        grounding = _number_grounding_report(output_text, generation_brief, event.get("generation_date"))

        # Run the quality gate
        report = _run_quality_gate(
            coach_id,
            output_text,
            voice_spec,
            generation_brief,
            other_outputs,
            grounding=grounding,
        )
        report["repetition"] = repetition
        report["number_grounding"] = grounding

        logger.info(
            "coach-quality-gate COMPLETE — coach=%s, passed=%s, score=%s, repetition=%s, number_grounding=%s%s",
            coach_id,
            report.get("passed"),
            report.get("score"),
            repetition.get("verdict"),
            grounding.get("verdict"),
            # #3202: the verdict word alone made a hold undiagnosable — three cycles of
            # `number_grounding=ungrounded` with no way to tell WHICH number (or, as it
            # turned out, that it was not a number at all) without a re-run. This is
            # the single line the whole root-cause dig would have been. It rides the
            # COMPLETE line because that line is the ONE exit every path reaches: both
            # `_run_quality_gate` fallbacks (non-dict payload, LLM call failed) RETURN
            # into this function and log here. The handler's own `except` below is the
            # only exit that skips it, and there the grounding report is an error dict
            # with no findings to name.
            _grounding_findings_summary(grounding),
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
            # #2350 — honest absence: the detector did not run, so no verdict.
            "repetition": {"status": "error", "verdict": None, "error": str(e), "advisory": True},
            # #2573 — same honest-absence contract for the number check.
            "number_grounding": {"status": "error", "verdict": None, "error": str(e), "advisory": True},
        }
