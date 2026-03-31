"""
Journal Analyzer Lambda — Observatory V2

Extracts themes and sentiment from journal entries using Claude Haiku.
Processes last 90 days of Notion journal entries, caching results
in a dedicated journal_analysis DynamoDB partition.

Trigger: EventBridge cron — nightly at 2am PT (10:00 UTC)
First run backfills 90 days; subsequent runs process only new entries.

DynamoDB cache:
  PK = USER#matthew#SOURCE#journal_analysis
  SK = DATE#YYYY-MM-DD
  TTL = 180 days

Cost estimate: ~90 entries × ~600 tokens avg = ~54,000 tokens.
  Haiku cost ~$0.003 total per backfill. Ongoing: a few cents/month.

v1.0.0 — 2026-03-31
"""

import json
import logging
import os
import urllib.request
import urllib.error
from datetime import datetime, timezone, timedelta
from decimal import Decimal

import boto3
from boto3.dynamodb.conditions import Key, Attr

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

TABLE_NAME = os.environ.get("TABLE_NAME", "life-platform")
USER_ID = os.environ.get("USER_ID", "matthew")
USER_PREFIX = f"USER#{USER_ID}#SOURCE#"
CACHE_PK = f"{USER_PREFIX}journal_analysis"
AI_SECRET_NAME = os.environ.get("AI_SECRET_NAME", "life-platform/ai-keys")
AI_MODEL = os.environ.get("AI_MODEL", "claude-haiku-4-5-20251001")

dynamodb = boto3.resource("dynamodb", region_name="us-west-2")
table = dynamodb.Table(TABLE_NAME)

_api_key_cache = None


def _get_api_key():
    global _api_key_cache
    if _api_key_cache:
        return _api_key_cache
    sm = boto3.client("secretsmanager", region_name="us-west-2")
    resp = sm.get_secret_value(SecretId=AI_SECRET_NAME)
    secret = resp["SecretString"]
    try:
        parsed = json.loads(secret)
        _api_key_cache = parsed.get("anthropic_api_key", secret)
    except (json.JSONDecodeError, TypeError):
        _api_key_cache = secret
    return _api_key_cache


def _decimal_to_float(obj):
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, dict):
        return {k: _decimal_to_float(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_decimal_to_float(i) for i in obj]
    return obj


def lambda_handler(event, context):
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    start_date = (datetime.now(timezone.utc) - timedelta(days=90)).strftime("%Y-%m-%d")

    # Query journal entries from Notion partition
    journal_pk = f"{USER_PREFIX}notion"
    resp = table.query(
        KeyConditionExpression=Key("pk").eq(journal_pk) & Key("sk").between(
            f"DATE#{start_date}#journal", f"DATE#{today}#journal#~"
        ),
    )
    entries = _decimal_to_float(resp.get("Items", []))

    # Filter to journal entries only (SK contains #journal#)
    entries = [e for e in entries if "#journal#" in e.get("sk", "")]

    logger.info(f"Found {len(entries)} journal entries in {start_date} to {today}")

    analyzed = 0
    skipped_existing = 0
    skipped_short = 0
    errors = 0

    api_key = _get_api_key()

    for entry in entries:
        sk = entry.get("sk", "")
        # Extract date from SK: DATE#YYYY-MM-DD#journal#...
        parts = sk.split("#")
        if len(parts) < 2:
            continue
        date_str = parts[1]  # YYYY-MM-DD

        # Check if analysis already exists
        existing = table.get_item(
            Key={"pk": CACHE_PK, "sk": f"DATE#{date_str}"}
        ).get("Item")
        if existing:
            skipped_existing += 1
            continue

        # Extract journal text — Notion ingestion stores as body_text or raw_text
        content = entry.get("body_text", "") or entry.get("raw_text", "") or entry.get("content", "") or entry.get("body", "") or entry.get("text", "")
        word_count = len(content.split()) if content else 0

        if word_count < 20:
            skipped_short += 1
            continue

        # Call Claude for theme extraction
        prompt = f"""Analyze this journal entry and respond with ONLY a JSON object (no other text):

{{
  "dominant_theme": "one of: personal_growth, relationships, health_body, work_ambition, anxiety_stress, gratitude, reflection, other",
  "themes": ["list", "of", "up to 5", "theme tags"],
  "sentiment_score": 0.0,
  "sentiment_label": "one of: very_positive, positive, neutral, negative, very_negative",
  "energy_level": "one of: high, medium, low",
  "one_line_summary": "brief factual summary of main topic, max 12 words"
}}

Theme definitions:
- personal_growth: self-improvement, habits, identity, progress, goals
- relationships: family, friends, partner, social connection, love
- health_body: physical health, fitness, food, weight, body, energy
- work_ambition: career, projects, leadership, productivity, achievements
- anxiety_stress: worry, pressure, overwhelm, fear, uncertainty
- gratitude: appreciation, thankfulness, positive reflection
- reflection: philosophical, existential, processing past events
- other: doesn't fit cleanly above

Journal entry:
{content[:2000]}"""

        try:
            req_body = json.dumps({
                "model": AI_MODEL,
                "max_tokens": 300,
                "messages": [{"role": "user", "content": prompt}],
            })

            req = urllib.request.Request(
                "https://api.anthropic.com/v1/messages",
                data=req_body.encode(),
                headers={
                    "Content-Type": "application/json",
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                },
            )

            with urllib.request.urlopen(req, timeout=30) as resp_ai:
                result = json.loads(resp_ai.read())

            text = "".join(b["text"] for b in result.get("content", []) if b.get("type") == "text")
            if not text:
                logger.warning(f"Empty response from API for {date_str}, result: {json.dumps(result, default=str)[:500]}")
                errors += 1
                continue
            # Strip markdown code fences if present
            text = text.strip()
            if text.startswith("```"):
                text = text.split("\n", 1)[-1]  # remove first line
                if text.endswith("```"):
                    text = text[:-3]
                text = text.strip()
            analysis = json.loads(text)

            now = datetime.now(timezone.utc)
            ttl = int((now + timedelta(days=180)).timestamp())

            table.put_item(Item={
                "pk": CACHE_PK,
                "sk": f"DATE#{date_str}",
                "date": date_str,
                "dominant_theme": analysis.get("dominant_theme", "other"),
                "themes": analysis.get("themes", []),
                "sentiment_score": str(analysis.get("sentiment_score", 0.0)),
                "sentiment_label": analysis.get("sentiment_label", "neutral"),
                "energy_level": analysis.get("energy_level", "medium"),
                "word_count": word_count,
                "one_line_summary": analysis.get("one_line_summary", ""),
                "analyzed_at": now.isoformat(),
                "model": AI_MODEL,
                "ttl": ttl,
            })

            analyzed += 1
            logger.info(f"Analyzed {date_str}: {analysis.get('dominant_theme', 'other')}")

        except json.JSONDecodeError as e:
            logger.warning(f"JSON parse error for {date_str}: {e}")
            errors += 1
        except Exception as e:
            logger.error(f"Failed to analyze {date_str}: {e}")
            errors += 1

    result = {
        "entries_found": len(entries),
        "analyzed": analyzed,
        "skipped_existing": skipped_existing,
        "skipped_short": skipped_short,
        "errors": errors,
        "date_range": {"start": start_date, "end": today},
    }
    logger.info(f"Journal analysis complete: {json.dumps(result)}")

    return {
        "statusCode": 200,
        "body": json.dumps(result),
    }
