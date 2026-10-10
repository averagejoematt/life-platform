#!/usr/bin/env python3
"""
Life Platform — Social Post Enrichment Lambda (#1671, epic #1668 — The Social Membrane)

S3 of the inbound social spine. Ingested social posts (S1 #1669) stamped with the
provenance membrane (S2 #1670) are inert data until they become coach signal. Rather than
build a second pipeline, this Lambda makes a social post ride the SAME journal path: a
ONE-shot Haiku extraction of the same structured fields the Notion journal enricher
produces, the SAME deterministic grounding gate (ADR-104), and an in-place write of the
``enriched_*`` fields onto the post record — exactly like journal_enrichment_lambda
updates the notion record it enriches. The coach surfaces (ai_context) already read
``enriched_*``; a routed social post therefore reaches the right coach for free (the
#1572 "4th channel — no second pipeline" principle, docs/coaching/CHAT_MODES.md).

Two hard invariants:

  * **The membrane (S2).** ONLY ``origin: human`` posts enter enrichment. Platform
    echoes (the platform's own outbound posts, re-ingested) are never coach signal — they
    are filtered out BEFORE any Haiku call via ``social_provenance.is_enrichable``.
  * **Grounding (ADR-104).** Every causal hint the model proposes survives only if its
    quote is verbatim in the post text — the reused ``_ground_causal_hints`` gate. The
    LLM proposes; the code verifies.

Each enriched record is stamped with ``channel`` provenance (``enriched_channel``) and a
deterministic ``enriched_coach_route`` (training vs mind, ``social_signals``) so a
training-flavoured post reaches the training/domain coach and a reflective one reaches
journal/Mind — the routing is by enriched CONTENT, not by channel.

#1675 (extending #1574/#1756 to this channel): once a post is enriched, the routed coach
also writes ONE short grounded reaction to it, produced by coach/coach_diary_reaction.py
and served on the same lab-notes surface as the diary reactions — the SAME mechanism, not
a second one. Membrane-gated (origin:human, S5 sensitivity-cleared) and budget-gated
before any Bedrock call, idempotent per post, and fail-open — a reaction never fails
enrichment (see ``maybe_react_to_post``).

Extracted fields (schema v1): enriched_themes, enriched_behaviors, enriched_entities,
enriched_exercise_context, enriched_sentiment, enriched_causal_hints (grounded),
enriched_channel, enriched_coach_route, enriched_schema_version, enriched_at.

Runs on:
  {}                              → last 7 days (EventBridge daily default)
  {"date": "YYYY-MM-DD"}          → specific date
  {"start": "...", "end": "..."}  → date range
  {"channels": ["youtube", ...]}  → override the channel set
  {"force": true}                 → re-enrich already-enriched posts

Environment variables:
  TABLE_NAME       — DynamoDB table (default: life-platform)
  MODEL            — Claude model (default: claude-haiku-4-5-20251001)
  SOCIAL_CHANNELS  — comma-separated channel/source names (default: youtube)
  LOOKBACK_DAYS    — default daily window (default: 7)
"""

import json
import logging
import os
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import boto3
from boto3.dynamodb.conditions import Key
from common.pacific_time import pacific_now, pacific_today  # #1964: the one Pacific frame (DST-aware)
from content import social_signals  # #1671: the deterministic coach router
from privacy import social_provenance as prov  # #1670: the membrane (origin gate)

try:
    from common.platform_logger import get_logger

    logger = get_logger("social-enrichment")
except ImportError:  # pragma: no cover — layer-module fallback (local tooling)
    logger = logging.getLogger("social-enrichment")
    logger.setLevel(logging.INFO)

# ── Config ────────────────────────────────────────────────────────────────────
TABLE_NAME = os.environ.get("TABLE_NAME", "life-platform")
MODEL = os.environ.get("MODEL", "claude-haiku-4-5-20251001")
REGION = os.environ.get("AWS_REGION", "us-west-2")
USER_ID = os.environ.get("USER_ID", "matthew")
# Channels this enricher sweeps. Defaults to the one inbound source that exists (#1669);
# S4+ social sources extend the set here (or via the SOCIAL_CHANNELS env / event override).
DEFAULT_CHANNELS = tuple(c.strip() for c in os.environ.get("SOCIAL_CHANNELS", "youtube").split(",") if c.strip())
LOOKBACK_DAYS = int(os.environ.get("LOOKBACK_DAYS", "7"))
# Social posts are short; the floor is words, not chars — a title + a one-line caption is
# still enough to extract a theme/sentiment. Below this the extraction is only noise.
MIN_TEXT_WORDS = 6
SCHEMA_VERSION = 1
# #4643: the budget_guard feature this Lambda's own Haiku extraction is gated on — listed in
# budget_guard._FEATURE_CUTOFF and scripts/ai_budget_ledger.py (tests/test_ingest_ai_budget_rows_4643.py).
BUDGET_FEATURE = "social_enrichment"
# #4643: the ER-01 INGEST_HEALTH#<name> sentinel every run writes (record_ingest_health).
HEALTH_SOURCE = "social_enrichment"

# ── AWS clients ───────────────────────────────────────────────────────────────
dynamodb = boto3.resource("dynamodb", region_name=REGION)
table = dynamodb.Table(TABLE_NAME)

# #4643: the ER-01 liveness sentinel, the same writer notion/dropbox/hevy use.
try:
    from ingestion.ingest_health import classify_error
    from ingestion.ingestion_framework import record_ingest_health

    _INGEST_HEALTH_AVAILABLE = True
except ImportError:  # pragma: no cover — layer-module fallback
    _INGEST_HEALTH_AVAILABLE = False


def _record_health(*, succeeded: bool, exc=None) -> None:
    """Best-effort INGEST_HEALTH write for this run (the Lambda ran = attempted). Never raises."""
    if not _INGEST_HEALTH_AVAILABLE:
        return
    error_class = "none" if succeeded else (exc if isinstance(exc, str) else classify_error(exc))
    record_ingest_health(table, HEALTH_SOURCE, logger, attempted=True, succeeded=succeeded, error_class=error_class)


def _ai_allowed() -> bool:
    """budget_guard gate for this run's Haiku extraction (#4643). Fails open if the
    module is missing — bedrock_client's own tier-3 backstop still applies."""
    try:
        from ai import budget_guard
    except ImportError:  # pragma: no cover — budget_guard always bundled in prod
        return True
    return budget_guard.allow(BUDGET_FEATURE)


# ── Haiku prompt ──────────────────────────────────────────────────────────────
SYSTEM_PROMPT = """You are a behavioral analyst reading a short PUBLIC social post the author wrote about their own life (a video caption, a status). Extract structured signals from the text. Be precise — only flag what is clearly present, never infer what isn't there.

Rules:
- Be conservative. Only extract what the text actually says.
- themes: max 4, ordered by prominence. Life themes, e.g. "physical achievement", "consistency", "work pressure", "gratitude".
- behaviors: concrete actions the author actually DID (past tense) — not plans or feelings. Max 6.
- entities: people/places/projects/things the post explicitly names. Max 8. Keep names as written.
- exercise_context: a brief subjective note ONLY if the post is about a workout/training session; otherwise null.
- sentiment: one of "positive"|"neutral"|"negative"|"mixed".
- causal_hints: ONLY cause→effect links the author EXPLICITLY asserts. NEVER infer one. The quote must be the verbatim sentence from the post that asserts the link — copy it exactly.
- Respond with ONLY valid JSON. No preamble, no markdown fences, no explanation."""

USER_PROMPT_TEMPLATE = """SOCIAL POST (channel: {channel}):
{post_text}

CONTEXT:
- Date: {date}

Extract as JSON:
{{
  "themes": [<life themes, max 4, most prominent first. Empty list if none>],
  "behaviors": [<concrete past-tense actions the author DID, max 6. Empty list if none>],
  "entities": [<people/places/projects/things explicitly named, max 8. Empty list if none>],
  "exercise_context": <brief subjective workout feel if the post is about training, else null>,
  "sentiment": <"positive"|"neutral"|"negative"|"mixed">,
  "causal_hints": [<cause->effect links the author EXPLICITLY asserts, each {{"cause": "...", "effect": "...", "quote": "<verbatim sentence from the post>"}}. Max 4. Empty list if none — most posts have none>]
}}"""

# USER_PROMPT_TEMPLATE's shape, constrained at the model (#4276): Bedrock structured outputs via
# ai.structured_json.call_json. Every key required; exercise_context is anyOf [string, null].
_S_STRS = {"type": "array", "items": {"type": "string"}}
EXTRACTION_SCHEMA = {
    "type": "object",
    "properties": {
        "themes": _S_STRS,
        "behaviors": _S_STRS,
        "entities": _S_STRS,
        "exercise_context": {"anyOf": [{"type": "string"}, {"type": "null"}]},
        "sentiment": {"type": "string", "enum": ["positive", "neutral", "negative", "mixed"]},
        "causal_hints": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"cause": {"type": "string"}, "effect": {"type": "string"}, "quote": {"type": "string"}},
                "required": ["cause", "effect", "quote"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["themes", "behaviors", "entities", "exercise_context", "sentiment", "causal_hints"],
    "additionalProperties": False,
}


def _ground_causal_hints(hints, post_text):
    """Reuse the journal enricher's ADR-104 grounding gate verbatim — a causal hint
    survives only if its quote is actually a (whitespace-normalized) substring of the
    post. The LLM proposes; the code verifies. Lazy import so this module doesn't build
    the journal Lambda's DDB clients at import time (and there is exactly ONE grounding
    gate — no second implementation to drift)."""
    from ingestion.journal_enrichment_lambda import _ground_causal_hints as _gch

    return _gch(hints, post_text)


def post_text(item):
    """The enrichable text for a social post: its title + description (the fields the
    ingestion transform persists, #1669). Kept small; the full raw payload is in S3.

    #1675: the definition moved to ``social_signals`` (pure, AWS-free) so the coach
    reaction's ADR-104 quote-grounding checks against exactly the same text this
    enricher grounds its causal hints against. Delegating call, not a re-export — a
    test that patches this name still intercepts every in-module use."""
    return social_signals.post_text(item)


def select_enrichable(posts):
    """THE MEMBRANE (S2 / #1670): only ``origin: human`` posts enter enrichment.

    A pure filter — platform echoes (the platform's own re-ingested outbound posts) are
    excluded here, BEFORE any Haiku call, so a platform post can never become coach
    signal. Missing/legacy ``origin`` is treated as human (every ingested post is stamped
    from day one, #1669; only an explicit ``platform`` stamp is excluded)."""
    return [p for p in (posts or []) if prov.is_enrichable(p)]


def call_haiku(text, channel, date):
    """One Haiku call for the full v1 social extraction. Routes through retry_utils →
    bedrock_client.invoke() (ADR-062) — IAM auth, no API key, no raw HTTP."""
    user_content = USER_PROMPT_TEMPLATE.format(post_text=text, channel=channel, date=date)
    body = {
        "model": MODEL,
        "max_tokens": 900,
        "system": [{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
        "messages": [{"role": "user", "content": user_content}],
    }
    # #4276: the reply is constrained to EXTRACTION_SCHEMA at the model and parsed in the one door.
    from ai.structured_json import call_json
    from common.retry_utils import call_anthropic_raw

    parsed = call_json(lambda b: call_anthropic_raw(b, timeout=30), body, schema=EXTRACTION_SCHEMA, label="social_enrichment")
    if not isinstance(parsed, dict):
        logger.error(f"Failed to parse Haiku response as a JSON object: {str(parsed)[:500]}")
        return None
    return parsed


FIELD_MAPPING = {
    "themes": ("enriched_themes", "L"),
    "behaviors": ("enriched_behaviors", "L"),
    "entities": ("enriched_entities", "L"),
    "exercise_context": ("enriched_exercise_context", "S"),
    "sentiment": ("enriched_sentiment", "S"),
    "causal_hints": ("enriched_causal_hints", "L"),  # list of {cause, effect, quote} maps
}


def apply_enrichment(item, enrichment):
    """Write the enriched_* fields back onto the SAME social post record (in place, like
    the journal enricher) — no new partition, no second pipeline. Stamps ``channel``
    provenance and the deterministic coach route. Returns True if anything was written."""
    # ADR-104 grounding gate — drop ungrounded causal hints before anything is written.
    if enrichment.get("causal_hints"):
        kept, dropped = _ground_causal_hints(enrichment["causal_hints"], post_text(item))
        enrichment["causal_hints"] = kept
        if dropped:
            logger.info(f"  Grounding gate dropped {dropped} ungrounded causal hint(s) for {item.get('sk')}")

    update_parts, attr_names, attr_values = [], {}, {}

    for haiku_key, (dynamo_key, dtype) in FIELD_MAPPING.items():
        val = enrichment.get(haiku_key)
        if val is None:
            continue
        if isinstance(val, list) and len(val) == 0:
            continue
        alias, placeholder = f"#{dynamo_key}", f":{dynamo_key}"
        attr_names[alias] = dynamo_key
        if dtype == "S":
            attr_values[placeholder] = str(val)
        elif dtype == "L":
            attr_values[placeholder] = val
        update_parts.append(f"{alias} = {placeholder}")

    # Channel provenance stamped on the enriched output (#1670/#1671), and the
    # deterministic coach route computed from the enriched CONTENT (#1671).
    channel = item.get("channel") or item.get("source") or ""
    attr_names["#ec"] = "enriched_channel"
    attr_values[":ec"] = str(channel)
    update_parts.append("#ec = :ec")

    route = social_signals.classify_coach_route(enrichment)
    attr_names["#ecr"] = "enriched_coach_route"
    attr_values[":ecr"] = route
    update_parts.append("#ecr = :ecr")

    attr_names["#enriched_at"] = "enriched_at"
    attr_values[":enriched_at"] = datetime.now(timezone.utc).isoformat()
    update_parts.append("#enriched_at = :enriched_at")
    attr_names["#esv"] = "enriched_schema_version"
    attr_values[":esv"] = Decimal(SCHEMA_VERSION)
    update_parts.append("#esv = :esv")

    table.update_item(
        Key={"pk": item["pk"], "sk": item["sk"]},
        UpdateExpression="SET " + ", ".join(update_parts),
        ExpressionAttributeNames=attr_names,
        ExpressionAttributeValues=attr_values,
    )
    return True


def post_with_enrichment(item, enrichment):
    """The stored post as it will look AFTER this run's enrichment lands (#1675).

    ``apply_enrichment`` writes with update_item; it does not mutate the in-memory item.
    The coach reaction routes on the enriched signals this pass just produced (the
    persisted ``enriched_coach_route``, and the enriched themes behind the laundered
    public theme), so it is handed this merged view rather than the stale record.
    Derived from FIELD_MAPPING — never a second hand-maintained key list.

    Called with ``enrichment=None`` on the already-enriched path, where the stored
    record IS the current view: the persisted ``enriched_coach_route`` is then left
    exactly as it is rather than recomputed from an empty dict (which would silently
    re-route every re-swept post to the Mind coach).
    """
    view = dict(item or {})
    view["enriched_channel"] = str(view.get("channel") or view.get("source") or "")
    if not enrichment:
        return view
    for haiku_key, (dynamo_key, _dtype) in FIELD_MAPPING.items():
        val = enrichment.get(haiku_key)
        if val is not None:
            view[dynamo_key] = val
    view["enriched_coach_route"] = social_signals.classify_coach_route(enrichment)
    return view


def _tally(counter, result):
    """Fold one trigger result into the run summary's reaction counter (#1675)."""
    if counter is None:
        return result
    counter["stored" if (result or {}).get("reacted") else "skipped"] += 1
    return result


def maybe_react_to_post(item, enrichment=None):
    """#1675 (epic #1668, extending #1574/#1756 to the social channel): a coach reacts
    to a just-enriched PUBLIC social post.

    Option A, exactly as #1756 wired the diary side — inline in the record-enrichment
    pipeline. No second pipeline, no new Lambda, no new schedule, no lambda_count churn
    (the "4th channel" principle), and this pass is the only place the enriched route
    the reaction uses exists. The reaction machinery itself is #1574's, unchanged; only
    the permission gate and the routing signal are the social channel's.

    Cost posture — every gate is BEFORE any Bedrock call:
      not a reaction surface        -> free, no I/O
      platform-origin echo (S2)     -> free, no I/O
      not sensitivity-cleared (S5)  -> free, no I/O   (the fail-closed default)
      already has a reaction        -> one GetItem
      budget tier >= 2              -> the producer's own budget_guard gate, no call
    So a held or platform post costs exactly nothing; a cleared human post costs one
    Haiku/Sonnet call, once, ever.

    Fail-OPEN by contract: any failure here is logged and swallowed — a reaction must
    never fail social enrichment. Returns the trigger's result dict.
    """
    try:
        from coach.coach_diary_reaction import maybe_react

        result = maybe_react(post_with_enrichment(item, enrichment), table_=table)
    except Exception as e:  # noqa: BLE001 — belt-and-braces around the import itself
        logger.error(f"  social coach reaction failed (non-fatal) for {(item or {}).get('sk')}: {e}")
        return {"reacted": False, "reason": "error", "error": str(e)}
    if result.get("reacted"):
        logger.info(f"  ✓ coach reaction stored for {item.get('sk')}: {result.get('coach_id')} → {result.get('sk')}")
    elif result.get("reason") not in ("not_diary", "platform_origin", "held", "exists"):
        logger.info(f"  coach reaction not produced for {item.get('sk')}: {result.get('reason')}")
    return result


def query_channel_posts(channel, start_date, end_date):
    """All ingested posts for one channel in [start_date, end_date] (inclusive of the end
    day's suffixed keys). sk=DATE#{date}#{post_id}; the ``#~`` upper bound sorts after
    every post-id suffix on the end day."""
    kwargs = {
        "KeyConditionExpression": Key("pk").eq(f"USER#{USER_ID}#SOURCE#{channel}")
        & Key("sk").between(f"DATE#{start_date}", f"DATE#{end_date}#~"),
        "ScanIndexForward": True,
    }
    items = []
    while True:
        resp = table.query(**kwargs)
        items.extend(resp.get("Items", []))
        if "LastEvaluatedKey" not in resp:
            break
        kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
    # Only per-post records (a suffixed sk), never a per-day feed snapshot.
    return [i for i in items if i.get("post_id") or i.get("sk", "").count("#") >= 2]


def enrich_post(item, force=False, reactions=None, ai_allowed=True, error_sink=None):
    """Enrich a single already-membrane-passed human post. Returns
    'enriched' | 'skipped' | 'paused' | 'error'. Callers MUST have filtered platform echoes
    first (select_enrichable) — this re-asserts the gate as defense in depth.

    ``reactions`` (optional) is a mutable counter dict the #1675 coach-reaction trigger
    tallies into, so the run summary reports what the trigger actually did rather than
    leaving it invisible in the logs.

    #4643: ``ai_allowed`` is the run's one budget_guard read for BUDGET_FEATURE — False
    leaves a post that needs the model un-enriched for the next sweep (``'paused'``) — and
    ``error_sink`` (optional list) collects the failure behind each ``'error'`` so the
    run's health record can carry its class."""
    sk = item.get("sk", "")
    if not prov.is_enrichable(item):
        logger.info(f"Skipping {sk}: platform-origin echo (membrane) — never enriched")
        return "skipped"

    text = post_text(item)
    words = len(text.split())
    if words < MIN_TEXT_WORDS:
        logger.info(f"Skipping {sk}: text too short ({words} words)")
        return "skipped"

    stale_schema = int(item.get("enriched_schema_version") or 0) < SCHEMA_VERSION
    if not force and item.get("enriched_at") and not stale_schema:
        logger.info(f"Skipping {sk}: already enriched at {item['enriched_at']}")
        # #1675: an already-enriched post still gets its chance at a reaction — the S5
        # sensitivity verdict can flip to cleared after enrichment, and a budget-paused
        # or quality-gate-held reaction should be retried on the next sweep. Idempotent
        # (one GetItem, then nothing) once a reaction exists.
        _tally(reactions, maybe_react_to_post(item))
        return "skipped"

    if not ai_allowed:
        return "paused"

    channel = item.get("channel") or item.get("source") or ""
    date = item.get("date") or str(sk).replace("DATE#", "")[:10]
    logger.info(f"Enriching {sk} (channel={channel}, {words} words)...")
    try:
        enrichment = call_haiku(text, channel, date)
        if not enrichment:
            logger.error(f"  ✗ No enrichment returned for {sk}")
            if error_sink is not None:
                error_sink.append("parse")
            return "error"
        apply_enrichment(item, enrichment)
        logger.info(
            f"  ✓ Enriched {sk}: route={social_signals.classify_coach_route(enrichment)}, "
            f"themes={enrichment.get('themes', [])}, sentiment={enrichment.get('sentiment')}"
        )
        # #1675: the coaches react to Matthew's public voice — inline, fail-open, gated.
        _tally(reactions, maybe_react_to_post(item, enrichment))
        return "enriched"
    except Exception as e:  # noqa: BLE001 — one bad post must not fail the sweep
        logger.error(f"  ✗ Error enriching {sk}: {e}")
        if error_sink is not None:
            error_sink.append(e)
        return "error"


def lambda_handler(event: dict, context) -> dict:
    if isinstance(event, dict) and event.get("healthcheck"):
        return {"statusCode": 200, "body": "ok"}
    try:
        if hasattr(logger, "set_date"):
            logger.set_date(pacific_today())
        event = event or {}
        force = bool(event.get("force"))
        channels = tuple(event.get("channels") or DEFAULT_CHANNELS)

        if "start" in event and "end" in event:
            start_date, end_date = event["start"], event["end"]
        elif "date" in event:
            start_date = end_date = event["date"]
        else:
            # #1964: was `timezone(timedelta(hours=-8))` — PST pinned year-round, so
            # for the ~8 months of PDT this derived a Pacific "now" an hour behind
            # reality and rolled `end_date` over an hour late. DST-aware now.
            now_pacific = pacific_now()
            end_date = now_pacific.strftime("%Y-%m-%d")
            start_date = (now_pacific - timedelta(days=LOOKBACK_DAYS)).strftime("%Y-%m-%d")

        logger.info(f"Social enrichment: channels={list(channels)} {start_date} → {end_date} (force={force})")

        enriched = skipped = errors = platform_excluded = paused_by_budget = 0
        reactions = {"stored": 0, "skipped": 0}  # #1675: what the coach-reaction trigger did
        error_sink: list = []  # #4643: the failures behind `errors`, for the health record's class
        ai_allowed = _ai_allowed()  # #4643: one tier read per run, not per post
        if not ai_allowed:
            logger.warning(f"budget tier pauses {BUDGET_FEATURE}: no Haiku extraction this run (posts stay queued)")
        for channel in channels:
            posts = query_channel_posts(channel, start_date, end_date)
            human_posts = select_enrichable(posts)
            platform_excluded += len(posts) - len(human_posts)
            logger.info(f"  {channel}: {len(posts)} posts, {len(human_posts)} human (membrane excluded {len(posts) - len(human_posts)})")
            for item in human_posts:
                status = enrich_post(item, force=force, reactions=reactions, ai_allowed=ai_allowed, error_sink=error_sink)
                enriched += status == "enriched"
                skipped += status == "skipped"
                errors += status == "error"
                paused_by_budget += status == "paused"

        summary = {
            "channels": list(channels),
            "enriched": enriched,
            "skipped": skipped,
            "errors": errors,
            "paused_by_budget": paused_by_budget,  # #4643
            "platform_excluded": platform_excluded,
            "reactions": reactions,
            "date_range": f"{start_date} → {end_date}",
        }
        logger.info(f"Complete: {summary}")
        # #4643: any post that failed to enrich makes this a FAILED run for liveness; a budget
        # pause is a healthy run that sanction-skipped.
        _record_health(succeeded=errors == 0, exc=error_sink[-1] if error_sink else None)
        return {"statusCode": 200, "body": json.dumps(summary)}
    except Exception as e:
        logger.error("lambda_handler failed: %s", e, exc_info=True)
        _record_health(succeeded=False, exc=e)  # #4643
        raise
