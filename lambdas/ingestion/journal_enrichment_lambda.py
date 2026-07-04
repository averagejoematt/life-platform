#!/usr/bin/env python3
"""
Life Platform — Journal Enrichment Lambda
Runs after Notion ingestion (EventBridge: 6:30 AM PT).

For each journal entry in the target date window, calls Claude Haiku ONCE
(#505 schema v2 — the old second "defense" pass is folded in) to extract
structured behavioral/psychological signals from raw_text:

  enriched_mood, enriched_energy, enriched_stress, enriched_sentiment,
  enriched_emotions, enriched_themes, enriched_cognitive_patterns,
  enriched_growth_signals, enriched_avoidance_flags, enriched_ownership,
  enriched_social_quality, enriched_flow, enriched_values_lived,
  enriched_gratitude, enriched_alcohol, enriched_sleep_context,
  enriched_pain, enriched_exercise_context, enriched_notable_quote,
  enriched_defense_patterns, enriched_primary_defense,
  enriched_entities, enriched_behaviors, enriched_causal_hints (v2),
  enriched_schema_version, enriched_at

v2 (#505): entities/behaviors/causal_hints are the raw material for grounding
and hypothesis candidates; every causal hint carries the verbatim sentence that
asserts it, and hints whose quote isn't actually in the entry are dropped
deterministically (the ADR-104 pattern). Dropped as dead (J-6): the second
Haiku pass, enriched_emotional_depth, enriched_defense_context.

Runs on:
  - Last 2 days by default (EventBridge daily); Sundays widen to 30 days
    as a safety-net sweep (#502)
  - Specific date: {"date": "YYYY-MM-DD"}
  - Date range: {"start": "...", "end": "..."}
  - Full re-enrichment: {"full_sync": true}
  - Skip already-enriched: default true, override with {"force": true}
    (entries enriched under schema v1 re-enrich automatically)

Environment variables:
  TABLE_NAME          — DynamoDB table (default: life-platform)
  MODEL               — Claude model (default: claude-haiku-4-5-20251001)
"""

import json
import logging
import os
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import boto3
from boto3.dynamodb.conditions import Key

# OBS-1: Structured logger — JSON output for CloudWatch Logs Insights
try:
    from platform_logger import get_logger

    logger = get_logger("journal-enrichment")
except ImportError:
    logger = logging.getLogger("journal-enrichment")
    logger.setLevel(logging.INFO)

# ── Config ────────────────────────────────────────────────────────────────────
TABLE_NAME = os.environ.get("TABLE_NAME", "life-platform")
MODEL = os.environ.get("MODEL", "claude-haiku-4-5-20251001")
# ── Config (env vars with backwards-compatible defaults) ──
REGION = os.environ.get("AWS_REGION", "us-west-2")
USER_ID = os.environ.get("USER_ID", "matthew")

PK = f"USER#{USER_ID}#SOURCE#notion"
# J-5 (#505): the floor is WORDS, aligned with journal_analyzer_lambda — the old
# 20-CHAR floor let one-liners through that only produced junk extractions.
MIN_TEXT_WORDS = 20
SCHEMA_VERSION = 2  # #505: bump when the extraction schema changes; v1 entries re-enrich

# ── AWS clients ───────────────────────────────────────────────────────────────
dynamodb = boto3.resource("dynamodb", region_name=REGION)
table = dynamodb.Table(TABLE_NAME)


# ── Haiku Prompt ──────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are an expert behavioral analyst reviewing a personal journal entry. Extract structured insights from the text. Be precise — only flag what's clearly present, never infer what isn't there.

Rules:
- Be conservative. Only extract what's clearly present in the text.
- emotions: prefer precise terms. "Apprehensive" over "bad". "Content" over "fine".
- cognitive_patterns: these are clinical CBT terms. Only flag if the pattern is clearly demonstrated, not just hinted at.
- themes: max 4, ordered by prominence in the entry.
- ownership_score: only rate if there's clear attribution language (internal vs external locus).
- values_lived: infer from actions described, not stated intentions.
- defense_patterns: psychodynamic defense mechanisms (Dr. Paul Conti school). Only flag what is CLEARLY demonstrated — most entries have 0-2, many have none. Intellectualization is NOT the same as being analytical; it requires AVOIDING emotional engagement through logic. Avoidance requires evidence of steering AWAY from something, not just not mentioning it.
- entities: only things the text explicitly names. Normalize casing, keep names as written.
- behaviors: concrete actions the author actually DID (past tense), not feelings, plans, or intentions.
- causal_hints: ONLY links the author explicitly asserts ("X because Y", "Y so X", "X after Y — every time"). NEVER infer a link yourself. The quote must be the verbatim sentence from the entry that asserts the link — copy it exactly, character for character.
- Respond with ONLY valid JSON. No preamble, no markdown fences, no explanation."""

USER_PROMPT_TEMPLATE = """JOURNAL ENTRY:
{raw_text}

CONTEXT:
- Date: {date}
- Template: {template}
- Structured scores: {structured_scores}

Extract as JSON:
{{
  "mood_score": <1-5 synthesized from all mood signals, null if unclear>,
  "energy_score": <1-5 synthesized from all energy signals, null if unclear>,
  "stress_score": <1-5 synthesized from all stress signals (1=calm, 5=overwhelmed), null if unclear>,
  "sentiment": <"positive"|"neutral"|"negative"|"mixed">,
  "emotions": [<precise emotional vocabulary, e.g. "anxious", "grateful", "frustrated", "hopeful", "content", "overwhelmed", "proud", "lonely", "energized", "resigned". Empty list if text too brief>],
  "themes": [<life themes, e.g. "work pressure", "family connection", "physical achievement", "creative expression", "financial stress", "health anxiety", "social isolation", "personal growth", "relationship tension". Max 4>],
  "cognitive_patterns": [<ONLY if clearly evident. Clinical terms: "catastrophizing", "black-and-white thinking", "should statements", "rumination", "overgeneralization", "personalization", "mind-reading", "fortune-telling", "discounting positives", "emotional reasoning". Positive: "reframing", "growth mindset", "self-compassion", "perspective-taking". Empty list if none>],
  "growth_signals": [<evidence of learning/growth, e.g. "recognized pattern", "tried new approach", "accepted uncertainty", "showed self-compassion". Empty list if none>],
  "avoidance_flags": [<things being avoided/procrastinated/feared. Empty list if none>],
  "ownership_score": <1-5 (1=external "they made me", 5=internal "I chose"), null if no attribution language>,
  "social_quality": <"alone"|"surface"|"meaningful"|"deep"|null>,
  "flow_indicators": <true if evidence of deep engagement/losing track of time, false otherwise>,
  "values_lived": [<core values evidenced in actions: "discipline", "family", "health", "creativity", "courage", "kindness", "growth", "integrity". Max 3. Empty list if none>],
  "gratitude_items": [<specific concrete gratitude. Not abstract. Empty list if none>],
  "alcohol_mention": <true|false>,
  "sleep_disruption_context": <brief reason if poor sleep mentioned, null otherwise>,
  "pain_mentions": [<body areas or pain types. Empty list if none>],
  "exercise_context": <brief subjective workout feel if mentioned, null otherwise>,
  "notable_quote": <most revealing/insightful sentence verbatim from the entry, null if too brief>,
  "defense_patterns": [<ONLY if clearly demonstrated. Valid patterns: "intellectualization", "avoidance", "displacement", "rationalization", "isolation_of_affect", "minimization", "projection", "denial", "sublimation", "humor_as_deflection", "compartmentalization". Empty list if none detected — this is the most common correct answer>],
  "primary_defense": <string or null — the single most prominent defense if any>,
  "entities": [<people/places/projects/things the entry explicitly names, e.g. "Sarah", "the Denver trip", "the platform". Max 8. Empty list if none>],
  "behaviors": [<concrete actions the author DID, e.g. "skipped the evening walk", "meal-prepped for the week", "stayed up late scrolling". Max 6. Empty list if none>],
  "causal_hints": [<cause→effect links the author EXPLICITLY asserts, each as {{"cause": "...", "effect": "...", "quote": "<the verbatim sentence from the entry that asserts the link>"}}. Max 4. Empty list if none — most entries have none>]
}}"""


def _ground_causal_hints(hints, raw_text):
    """#505: deterministic grounding — a causal hint survives only if its quote is
    actually a substring of the entry (whitespace-normalized). The ADR-104 pattern:
    the LLM proposes, the code verifies. Returns (kept, dropped_count)."""
    if not isinstance(hints, list):
        return [], 0
    norm_text = " ".join(str(raw_text).split()).lower()
    kept, dropped = [], 0
    for h in hints:
        if not isinstance(h, dict):
            dropped += 1
            continue
        quote = " ".join(str(h.get("quote") or "").split()).lower()
        if quote and h.get("cause") and h.get("effect") and quote in norm_text:
            kept.append({"cause": str(h["cause"]), "effect": str(h["effect"]), "quote": str(h["quote"])})
        else:
            dropped += 1
    return kept, dropped


def build_structured_scores(item):
    """Build a summary of structured scores already captured in the entry."""
    scores = []
    field_map = {
        "morning_mood": "mood",
        "day_rating": "day_rating",
        "morning_energy": "energy",
        "energy_eod": "energy_eod",
        "stress_level": "stress",
        "subjective_sleep_quality": "sleep_quality",
        "workout_rpe": "rpe",
        "social_connection": "social",
        "week_rating": "week_rating",
        "stress_intensity": "stress_intensity",
    }
    for field, label in field_map.items():
        val = item.get(field)
        if val is not None:
            scores.append(f"{label}={val}")
    return ", ".join(scores) if scores else "none captured"


def call_haiku(raw_text, date, template, structured_scores):
    """One Haiku call for the full v2 extraction (#505 — J-2: the urllib Request
    scaffolding and the dead api-key fetch are gone; retry_utils routes the plain
    Messages body to Bedrock)."""
    user_content = USER_PROMPT_TEMPLATE.format(
        raw_text=raw_text,
        date=date,
        template=template,
        structured_scores=structured_scores,
    )

    body = {
        "model": MODEL,
        # 1400, not 1000: schema v2 added entities/behaviors/causal_hints — a
        # truncated ```json fence fails silently (see the max_tokens gotcha).
        "max_tokens": 1400,
        "system": [{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
        "messages": [{"role": "user", "content": user_content}],
    }

    # Phase 3.4 (2026-05-16): retry via retry_utils (4 attempts, 5/15/45s).
    from retry_utils import call_anthropic_raw

    result = call_anthropic_raw(body, timeout=30)

    # Extract text content
    text = ""
    for block in result.get("content", []):
        if block.get("type") == "text":
            text += block["text"]

    # Clean and parse JSON
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
    if text.endswith("```"):
        text = text[:-3]
    text = text.strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse Haiku response: {e}\nRaw: {text[:500]}")
        return None


FIELD_MAPPING = {
    "mood_score": ("enriched_mood", "N"),
    "energy_score": ("enriched_energy", "N"),
    "stress_score": ("enriched_stress", "N"),
    "sentiment": ("enriched_sentiment", "S"),
    "emotions": ("enriched_emotions", "L"),
    "themes": ("enriched_themes", "L"),
    "cognitive_patterns": ("enriched_cognitive_patterns", "L"),
    "growth_signals": ("enriched_growth_signals", "L"),
    "avoidance_flags": ("enriched_avoidance_flags", "L"),
    "ownership_score": ("enriched_ownership", "N"),
    "social_quality": ("enriched_social_quality", "S"),
    "flow_indicators": ("enriched_flow", "BOOL"),
    "values_lived": ("enriched_values_lived", "L"),
    "gratitude_items": ("enriched_gratitude", "L"),
    "alcohol_mention": ("enriched_alcohol", "BOOL"),
    "sleep_disruption_context": ("enriched_sleep_context", "S"),
    "pain_mentions": ("enriched_pain", "L"),
    "exercise_context": ("enriched_exercise_context", "S"),
    "notable_quote": ("enriched_notable_quote", "S"),
    # v2 (#505): the defense pass folded in + the extraction trio
    "defense_patterns": ("enriched_defense_patterns", "L"),
    "primary_defense": ("enriched_primary_defense", "S"),
    "entities": ("enriched_entities", "L"),
    "behaviors": ("enriched_behaviors", "L"),
    "causal_hints": ("enriched_causal_hints", "L"),  # list of {cause, effect, quote} maps
}


def apply_enrichment(item, enrichment):
    """Write enrichment fields back to the DynamoDB item."""
    update_parts = []
    attr_names = {}
    attr_values = {}

    # #505: grounding gate — causal hints whose quote isn't verbatim in the entry
    # are dropped before anything is written.
    if enrichment.get("causal_hints"):
        kept, dropped = _ground_causal_hints(enrichment["causal_hints"], item.get("raw_text", ""))
        enrichment["causal_hints"] = kept
        if dropped:
            logger.info(f"  Grounding gate dropped {dropped} ungrounded causal hint(s) for {item.get('sk')}")

    for haiku_key, (dynamo_key, dtype) in FIELD_MAPPING.items():
        val = enrichment.get(haiku_key)
        if val is None:
            continue

        # Skip empty lists
        if isinstance(val, list) and len(val) == 0:
            continue

        alias = f"#{dynamo_key}"
        placeholder = f":{dynamo_key}"
        attr_names[alias] = dynamo_key

        if dtype == "N":
            attr_values[placeholder] = Decimal(str(val))
        elif dtype == "S":
            attr_values[placeholder] = str(val)
        elif dtype == "BOOL":
            attr_values[placeholder] = bool(val)
        elif dtype == "L":
            attr_values[placeholder] = val  # list of strings (or maps for causal_hints)

        update_parts.append(f"{alias} = {placeholder}")

    # Always set enriched_at + the schema version that produced this record
    attr_names["#enriched_at"] = "enriched_at"
    attr_values[":enriched_at"] = datetime.now(timezone.utc).isoformat()
    update_parts.append("#enriched_at = :enriched_at")
    attr_names["#esv"] = "enriched_schema_version"
    attr_values[":esv"] = Decimal(SCHEMA_VERSION)
    update_parts.append("#esv = :esv")

    if not update_parts:
        logger.info(f"No enrichment to apply for {item['sk']}")
        return False

    update_expr = "SET " + ", ".join(update_parts)

    table.update_item(
        Key={"pk": item["pk"], "sk": item["sk"]},
        UpdateExpression=update_expr,
        ExpressionAttributeNames=attr_names,
        ExpressionAttributeValues=attr_values,
    )

    return True


def _parse_ts(value):
    """Parse an ISO timestamp (Notion 'Z' suffix or stdlib '+00:00') to an aware datetime; None on failure."""
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def edited_since_enrichment(item):
    """True when the Notion entry was edited after its last enrichment (#502)."""
    enriched_ts = _parse_ts(item.get("enriched_at"))
    edited_ts = _parse_ts(item.get("notion_last_edited"))
    return bool(enriched_ts and edited_ts and edited_ts > enriched_ts)


def query_journal_entries(start_date, end_date, full_sync=False):
    """Query all Notion journal entries in date range."""
    kwargs = {
        "KeyConditionExpression": Key("pk").eq(PK),
        "ScanIndexForward": True,
    }

    if not full_sync:
        kwargs["KeyConditionExpression"] &= Key("sk").between(
            f"DATE#{start_date}#journal", f"DATE#{end_date}#journal#~"  # ~ sorts after all suffixes
        )

    items = []
    while True:
        resp = table.query(**kwargs)
        items.extend(resp.get("Items", []))
        if "LastEvaluatedKey" not in resp:
            break
        kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]

    # Filter to only journal items (SK contains #journal#)
    return [i for i in items if "#journal#" in i.get("sk", "")]


def lambda_handler(event, context):
    try:
        """
        Lambda entry point.

        Event formats:
          {}                              → last 2 days
          {"date": "YYYY-MM-DD"}          → specific date
          {"start": "...", "end": "..."}  → date range
          {"full_sync": true}             → all entries
          {"force": true}                 → re-enrich already-enriched entries
        """
        if hasattr(logger, "set_date"):
            logger.set_date(datetime.now(timezone.utc).strftime("%Y-%m-%d"))  # OBS-1
        force = event.get("force", False)
        full_sync = event.get("full_sync", False)

        if full_sync:
            start_date = "2020-01-01"
            end_date = "2099-12-31"
            logger.info("Full sync mode")
        elif "start" in event and "end" in event:
            start_date = event["start"]
            end_date = event["end"]
        elif "date" in event:
            start_date = event["date"]
            end_date = event["date"]
        else:
            pacific = timezone(timedelta(hours=-8))
            now_pacific = datetime.now(pacific)
            end_date = now_pacific.strftime("%Y-%m-%d")
            # Weekly safety net (#502): on Sundays sweep 30 days so anything the
            # 2-day window missed (late edits, outages, clobbered records) self-heals.
            lookback_days = 30 if now_pacific.weekday() == 6 else 1
            start_date = (now_pacific - timedelta(days=lookback_days)).strftime("%Y-%m-%d")

        logger.info(f"Enriching journal entries: {start_date} → {end_date} " f"(force={force}, full_sync={full_sync})")

        entries = query_journal_entries(start_date, end_date, full_sync)
        logger.info(f"Found {len(entries)} journal entries")

        enriched = 0
        skipped = 0
        errors = 0

        for item in entries:
            sk = item.get("sk", "")
            raw_text = item.get("raw_text", "")

            # Skip if too short — WORD floor, aligned with journal_analyzer (J-5/#505)
            word_count = len(raw_text.split())
            if word_count < MIN_TEXT_WORDS:
                logger.info(f"Skipping {sk}: raw_text too short ({word_count} words)")
                skipped += 1
                continue

            # Skip if already enriched (unless force) — but an entry edited in
            # Notion after enrichment (#502) or enriched under an older schema
            # (#505) is stale and re-enriches. The Sunday 30-day sweep therefore
            # self-heals v1 entries without a manual backfill.
            edited = edited_since_enrichment(item)
            stale_schema = int(item.get("enriched_schema_version") or 1) < SCHEMA_VERSION
            if not force and item.get("enriched_at") and not edited and not stale_schema:
                logger.info(f"Skipping {sk}: already enriched at {item['enriched_at']}")
                skipped += 1
                continue
            if edited:
                logger.info(f"Re-enriching {sk}: edited {item.get('notion_last_edited')} after enrichment {item.get('enriched_at')}")
            elif stale_schema and item.get("enriched_at"):
                logger.info(f"Re-enriching {sk}: schema v{item.get('enriched_schema_version') or 1} < v{SCHEMA_VERSION}")

            template = item.get("template", "Unknown")
            date = item.get("date", "")
            structured_scores = build_structured_scores(item)

            logger.info(f"Enriching {sk} ({template}, {word_count} words)...")

            try:
                enrichment = call_haiku(raw_text, date, template, structured_scores)
                if enrichment:
                    applied = apply_enrichment(item, enrichment)
                    if applied:
                        enriched += 1
                        logger.info(
                            f"  ✓ Enriched {sk}: "
                            f"mood={enrichment.get('mood_score')}, "
                            f"stress={enrichment.get('stress_score')}, "
                            f"themes={enrichment.get('themes', [])}, "
                            f"causal_hints={len(enrichment.get('causal_hints') or [])}"
                        )
                    else:
                        skipped += 1
                else:
                    errors += 1
                    logger.error(f"  ✗ No enrichment returned for {sk}")
            except Exception as e:
                errors += 1
                logger.error(f"  ✗ Error enriching {sk}: {e}")

        summary = {
            "entries_found": len(entries),
            "enriched": enriched,
            "skipped": skipped,
            "errors": errors,
            "date_range": f"{start_date} → {end_date}",
        }
        logger.info(f"Complete: {summary}")

        return {"statusCode": 200, "body": json.dumps(summary)}
    except Exception as e:
        logger.error("lambda_handler failed: %s", e, exc_info=True)
        raise
