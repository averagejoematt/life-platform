#!/usr/bin/env python3
"""
Life Platform — Journal Enrichment Lambda
Runs after Notion ingestion (EventBridge: 6:30 AM PT).

For each journal entry in the target date window, calls Claude Haiku to
extract structured behavioral/psychological signals from raw_text:

  enriched_mood, enriched_energy, enriched_stress, enriched_sentiment,
  enriched_emotions, enriched_themes, enriched_cognitive_patterns,
  enriched_growth_signals, enriched_avoidance_flags, enriched_ownership,
  enriched_social_quality, enriched_flow, enriched_values_lived,
  enriched_gratitude, enriched_alcohol, enriched_sleep_context,
  enriched_pain, enriched_exercise_context, enriched_notable_quote,
  enriched_at

Runs on:
  - Last 2 days by default (EventBridge daily)
  - Specific date: {"date": "YYYY-MM-DD"}
  - Date range: {"start": "...", "end": "..."}
  - Full re-enrichment: {"full_sync": true}
  - Skip already-enriched: default true, override with {"force": true}

Environment variables:
  TABLE_NAME          — DynamoDB table (default: life-platform)
  ANTHROPIC_SECRET    — Secrets Manager key for Anthropic API key
  MODEL               — Claude model (default: claude-haiku-4-5-20251001)
"""

import json
import logging
import os
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from urllib.request import Request, urlopen
from urllib.error import HTTPError

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
ANTHROPIC_SECRET = os.environ.get("ANTHROPIC_SECRET", "life-platform/ai-keys")
MODEL = os.environ.get("MODEL", "claude-haiku-4-5-20251001")
ANTHROPIC_API = "https://api.anthropic.com/v1/messages"
# ── Config (env vars with backwards-compatible defaults) ──
REGION     = os.environ.get("AWS_REGION", "us-west-2")
USER_ID    = os.environ.get("USER_ID", "matthew")

PK = f"USER#{USER_ID}#SOURCE#notion"
MIN_TEXT_LENGTH = 20  # Skip enrichment for very short entries
ENRICH_DEFENSE_PATTERNS = True  # v2.72.0: Add defense mechanism detection (#41)

# ── AWS clients ───────────────────────────────────────────────────────────────
secrets = boto3.client("secretsmanager", region_name=REGION)
dynamodb = boto3.resource("dynamodb", region_name=REGION)
table = dynamodb.Table(TABLE_NAME)

_api_key_cache = None


def get_anthropic_key():
    global _api_key_cache
    if _api_key_cache:
        return _api_key_cache
    resp = secrets.get_secret_value(SecretId=ANTHROPIC_SECRET)
    secret = json.loads(resp["SecretString"])
    _api_key_cache = secret.get("anthropic_api_key") or secret.get("api_key") or secret.get("key")
    return _api_key_cache


# ── Haiku Prompt ──────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are an expert behavioral analyst reviewing a personal journal entry. Extract structured insights from the text. Be precise — only flag what's clearly present, never infer what isn't there.

Rules:
- Be conservative. Only extract what's clearly present in the text.
- emotions: prefer precise terms. "Apprehensive" over "bad". "Content" over "fine".
- cognitive_patterns: these are clinical CBT terms. Only flag if the pattern is clearly demonstrated, not just hinted at.
- themes: max 4, ordered by prominence in the entry.
- ownership_score: only rate if there's clear attribution language (internal vs external locus).
- values_lived: infer from actions described, not stated intentions.
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
  "notable_quote": <most revealing/insightful sentence verbatim from the entry, null if too brief>
}}"""


# ── Defense Mechanism Prompt (Conti-informed) ─────────────────────────────────

DEFENSE_SYSTEM_PROMPT = """You are a clinical psychologist trained in psychodynamic therapy (Dr. Paul Conti school). Analyze this journal entry for psychological defense mechanisms.

Rules:
- Only flag defense mechanisms that are CLEARLY demonstrated in the text, not merely hinted at.
- Be conservative — most entries will have 0-2 patterns. Many entries have none.
- Intellectualization is NOT the same as being analytical. It requires AVOIDING emotional engagement through logic.
- Avoidance requires evidence of steering AWAY from something, not just not mentioning it.
- Return ONLY valid JSON. No preamble, no markdown fences."""

DEFENSE_USER_TEMPLATE = """JOURNAL ENTRY:
{raw_text}

CONTEXT:
- Date: {date}
- Template: {template}
- Mood: {mood}, Stress: {stress}
- Themes: {themes}

Extract as JSON:
{{
  "defense_patterns": [<ONLY if clearly demonstrated. Valid patterns: "intellectualization", "avoidance", "displacement", "rationalization", "isolation_of_affect", "minimization", "projection", "denial", "sublimation", "humor_as_deflection", "compartmentalization". Empty list if none detected — this is the most common correct answer>],
  "primary_defense": <string or null — the single most prominent defense if any>,
  "defense_context": <brief 1-sentence description of what's being defended against, null if no defenses detected>,
  "emotional_depth_rating": <1-5: 1=very surface/avoidant, 3=moderate engagement, 5=deep emotional processing>
}}"""


def call_haiku_defense(raw_text, date, template, mood, stress, themes):
    """Second Haiku call for defense mechanism detection."""
    api_key = get_anthropic_key()

    user_content = DEFENSE_USER_TEMPLATE.format(
        raw_text=raw_text,
        date=date,
        template=template,
        mood=mood or "unknown",
        stress=stress or "unknown",
        themes=", ".join(themes) if themes else "none",
    )

    body = {
        "model": MODEL,
        "max_tokens": 500,
        "system": DEFENSE_SYSTEM_PROMPT,
        "messages": [{"role": "user", "content": user_content}],
    }

    req = Request(ANTHROPIC_API, data=json.dumps(body).encode("utf-8"), method="POST", headers={
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    })

    try:
        with urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read().decode())
    except HTTPError as e:
        error_body = e.read().decode() if e.fp else ""
        logger.error(f"Defense Haiku API {e.code}: {error_body}")
        return None

    text = ""
    for block in result.get("content", []):
        if block.get("type") == "text":
            text += block["text"]

    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
    if text.endswith("```"):
        text = text[:-3]
    text = text.strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse defense response: {e}\nRaw: {text[:300]}")
        return None


def apply_defense_enrichment(item, defense_data):
    """Write defense mechanism fields to the DynamoDB item."""
    update_parts = []
    attr_names = {}
    attr_values = {}

    patterns = defense_data.get("defense_patterns", [])
    if patterns and isinstance(patterns, list) and len(patterns) > 0:
        attr_names["#edp"] = "enriched_defense_patterns"
        attr_values[":edp"] = patterns
        update_parts.append("#edp = :edp")

    primary = defense_data.get("primary_defense")
    if primary:
        attr_names["#epd"] = "enriched_primary_defense"
        attr_values[":epd"] = str(primary)
        update_parts.append("#epd = :epd")

    context = defense_data.get("defense_context")
    if context:
        attr_names["#edc"] = "enriched_defense_context"
        attr_values[":edc"] = str(context)
        update_parts.append("#edc = :edc")

    depth = defense_data.get("emotional_depth_rating")
    if depth is not None:
        attr_names["#eed"] = "enriched_emotional_depth"
        attr_values[":eed"] = Decimal(str(depth))
        update_parts.append("#eed = :eed")

    # Always set defense_enriched_at
    attr_names["#dea"] = "defense_enriched_at"
    attr_values[":dea"] = datetime.now(timezone.utc).isoformat()
    update_parts.append("#dea = :dea")

    if not update_parts:
        return False

    update_expr = "SET " + ", ".join(update_parts)
    # DATA-2 note: journal enrichment updates existing notion records — validator runs at notion ingestion time
    table.update_item(
        Key={"pk": item["pk"], "sk": item["sk"]},
        UpdateExpression=update_expr,
        ExpressionAttributeNames=attr_names,
        ExpressionAttributeValues=attr_values,
    )
    return True


def build_structured_scores(item):
    """Build a summary of structured scores already captured in the entry."""
    scores = []
    field_map = {
        "morning_mood": "mood", "day_rating": "day_rating",
        "morning_energy": "energy", "energy_eod": "energy_eod",
        "stress_level": "stress", "subjective_sleep_quality": "sleep_quality",
        "workout_rpe": "rpe", "social_connection": "social",
        "week_rating": "week_rating", "stress_intensity": "stress_intensity",
    }
    for field, label in field_map.items():
        val = item.get(field)
        if val is not None:
            scores.append(f"{label}={val}")
    return ", ".join(scores) if scores else "none captured"


def call_haiku(raw_text, date, template, structured_scores):
    """Call Claude Haiku API and return parsed JSON."""
    api_key = get_anthropic_key()

    user_content = USER_PROMPT_TEMPLATE.format(
        raw_text=raw_text,
        date=date,
        template=template,
        structured_scores=structured_scores,
    )

    body = {
        "model": MODEL,
        "max_tokens": 1000,
        "system": SYSTEM_PROMPT,
        "messages": [{"role": "user", "content": user_content}],
    }

    req = Request(ANTHROPIC_API, data=json.dumps(body).encode("utf-8"), method="POST", headers={
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    })

    try:
        with urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read().decode())
    except HTTPError as e:
        error_body = e.read().decode() if e.fp else ""
        logger.error(f"Anthropic API {e.code}: {error_body}")
        raise

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


def apply_enrichment(item, enrichment):
    """Write enrichment fields back to the DynamoDB item."""
    update_parts = []
    attr_names = {}
    attr_values = {}

    field_mapping = {
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
    }

    for haiku_key, (dynamo_key, dtype) in field_mapping.items():
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
            attr_values[placeholder] = val  # list of strings

        update_parts.append(f"{alias} = {placeholder}")

    # Always set enriched_at
    attr_names["#enriched_at"] = "enriched_at"
    attr_values[":enriched_at"] = datetime.now(timezone.utc).isoformat()
    update_parts.append("#enriched_at = :enriched_at")

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


def query_journal_entries(start_date, end_date, full_sync=False):
    """Query all Notion journal entries in date range."""
    kwargs = {
        "KeyConditionExpression": Key("pk").eq(PK),
        "ScanIndexForward": True,
    }

    if not full_sync:
        kwargs["KeyConditionExpression"] &= Key("sk").between(
            f"DATE#{start_date}#journal",
            f"DATE#{end_date}#journal#~"  # ~ sorts after all suffixes
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
        if hasattr(logger, "set_date"): logger.set_date(datetime.now(timezone.utc).strftime("%Y-%m-%d"))  # OBS-1
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
            start_date = (now_pacific - timedelta(days=1)).strftime("%Y-%m-%d")

        logger.info(f"Enriching journal entries: {start_date} → {end_date} "
                    f"(force={force}, full_sync={full_sync})")

        entries = query_journal_entries(start_date, end_date, full_sync)
        logger.info(f"Found {len(entries)} journal entries")

        enriched = 0
        skipped = 0
        errors = 0

        for item in entries:
            sk = item.get("sk", "")
            raw_text = item.get("raw_text", "")

            # Skip if too short
            if len(raw_text) < MIN_TEXT_LENGTH:
                logger.info(f"Skipping {sk}: raw_text too short ({len(raw_text)} chars)")
                skipped += 1
                continue

            # Skip if already enriched (unless force)
            if not force and item.get("enriched_at"):
                logger.info(f"Skipping {sk}: already enriched at {item['enriched_at']}")
                skipped += 1
                continue

            template = item.get("template", "Unknown")
            date = item.get("date", "")
            structured_scores = build_structured_scores(item)

            logger.info(f"Enriching {sk} ({template}, {len(raw_text)} chars)...")

            try:
                enrichment = call_haiku(raw_text, date, template, structured_scores)
                if enrichment:
                    applied = apply_enrichment(item, enrichment)
                    if applied:
                        enriched += 1
                        logger.info(f"  ✓ Enriched {sk}: "
                                    f"mood={enrichment.get('mood_score')}, "
                                    f"stress={enrichment.get('stress_score')}, "
                                    f"themes={enrichment.get('themes', [])}")

                        # Defense mechanism detection (second Haiku call) — v2.72.0 #41
                        if ENRICH_DEFENSE_PATTERNS and (force or not item.get("defense_enriched_at")):
                            try:
                                defense = call_haiku_defense(
                                    raw_text, date, template,
                                    enrichment.get("mood_score"),
                                    enrichment.get("stress_score"),
                                    enrichment.get("themes", []),
                                )
                                if defense:
                                    apply_defense_enrichment(item, defense)
                                    logger.info(f"    ✓ Defense: {defense.get('defense_patterns', [])}")
                            except Exception as de:
                                logger.warning(f"    Defense enrichment failed for {sk}: {de}")
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
