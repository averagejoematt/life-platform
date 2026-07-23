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
import social_provenance as prov  # #1670: the membrane (origin gate)
import social_signals  # #1671: the deterministic coach router
from boto3.dynamodb.conditions import Key

try:
    from platform_logger import get_logger

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

# ── AWS clients ───────────────────────────────────────────────────────────────
dynamodb = boto3.resource("dynamodb", region_name=REGION)
table = dynamodb.Table(TABLE_NAME)


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
    ingestion transform persists, #1669). Kept small; the full raw payload is in S3."""
    parts = [str(item.get("title") or ""), str(item.get("description") or "")]
    return "\n".join(p for p in parts if p).strip()


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
    from retry_utils import call_anthropic_raw

    result = call_anthropic_raw(body, timeout=30)

    text_out = ""
    for block in result.get("content", []):
        if block.get("type") == "text":
            text_out += block["text"]
    text_out = text_out.strip()
    if text_out.startswith("```"):
        text_out = text_out.split("\n", 1)[1] if "\n" in text_out else text_out[3:]
    if text_out.endswith("```"):
        text_out = text_out[:-3]
    text_out = text_out.strip()
    try:
        return json.loads(text_out)
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse Haiku response: {e}\nRaw: {text_out[:500]}")
        return None


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


def enrich_post(item, force=False):
    """Enrich a single already-membrane-passed human post. Returns
    'enriched' | 'skipped' | 'error'. Callers MUST have filtered platform echoes first
    (select_enrichable) — this re-asserts the gate as defense in depth."""
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
        return "skipped"

    channel = item.get("channel") or item.get("source") or ""
    date = item.get("date") or str(sk).replace("DATE#", "")[:10]
    logger.info(f"Enriching {sk} (channel={channel}, {words} words)...")
    try:
        enrichment = call_haiku(text, channel, date)
        if not enrichment:
            logger.error(f"  ✗ No enrichment returned for {sk}")
            return "error"
        apply_enrichment(item, enrichment)
        logger.info(
            f"  ✓ Enriched {sk}: route={social_signals.classify_coach_route(enrichment)}, "
            f"themes={enrichment.get('themes', [])}, sentiment={enrichment.get('sentiment')}"
        )
        return "enriched"
    except Exception as e:  # noqa: BLE001 — one bad post must not fail the sweep
        logger.error(f"  ✗ Error enriching {sk}: {e}")
        return "error"


def lambda_handler(event: dict, context) -> dict:
    if isinstance(event, dict) and event.get("healthcheck"):
        return {"statusCode": 200, "body": "ok"}
    try:
        if hasattr(logger, "set_date"):
            logger.set_date(datetime.now(timezone.utc).strftime("%Y-%m-%d"))
        event = event or {}
        force = bool(event.get("force"))
        channels = tuple(event.get("channels") or DEFAULT_CHANNELS)

        if "start" in event and "end" in event:
            start_date, end_date = event["start"], event["end"]
        elif "date" in event:
            start_date = end_date = event["date"]
        else:
            pacific = timezone(timedelta(hours=-8))
            now_pacific = datetime.now(pacific)
            end_date = now_pacific.strftime("%Y-%m-%d")
            start_date = (now_pacific - timedelta(days=LOOKBACK_DAYS)).strftime("%Y-%m-%d")

        logger.info(f"Social enrichment: channels={list(channels)} {start_date} → {end_date} (force={force})")

        enriched = skipped = errors = platform_excluded = 0
        for channel in channels:
            posts = query_channel_posts(channel, start_date, end_date)
            human_posts = select_enrichable(posts)
            platform_excluded += len(posts) - len(human_posts)
            logger.info(f"  {channel}: {len(posts)} posts, {len(human_posts)} human (membrane excluded {len(posts) - len(human_posts)})")
            for item in human_posts:
                status = enrich_post(item, force=force)
                enriched += status == "enriched"
                skipped += status == "skipped"
                errors += status == "error"

        summary = {
            "channels": list(channels),
            "enriched": enriched,
            "skipped": skipped,
            "errors": errors,
            "platform_excluded": platform_excluded,
            "date_range": f"{start_date} → {end_date}",
        }
        logger.info(f"Complete: {summary}")
        return {"statusCode": 200, "body": json.dumps(summary)}
    except Exception as e:
        logger.error("lambda_handler failed: %s", e, exc_info=True)
        raise
