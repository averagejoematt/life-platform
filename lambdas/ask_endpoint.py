"""
ask_endpoint.py — /api/ask endpoint for site_api_lambda.py

INTEGRATION STEPS:
  1. Copy handle_ask() function into site_api_lambda.py
  2. Add route to ROUTES dict: "/api/ask": handle_ask
  3. Add Anthropic API key to Secrets Manager: life-platform/anthropic-api-key
  4. Add IAM permission: secretsmanager:GetSecretValue on the above secret
  5. pip install anthropic into Lambda layer (or bundle the SDK)
  6. Deploy site_api Lambda

COST ESTIMATE:
  Claude Haiku at ~$0.25/M input, $1.25/M output tokens
  Average question: ~800 input tokens, ~400 output tokens = ~$0.0007/question
  At 100 questions/day = ~$2.10/month
  At 10 questions/day  = ~$0.21/month

RATE LIMITING:
  - 5 questions per IP per hour (stored in DynamoDB TTL table)
  - If exceeded, returns 429 with retry-after header

SECURITY:
  - Only pre-fetched aggregate data is exposed to the prompt
  - No raw DynamoDB records reach Claude
  - Question is sanitized (max 500 chars, no HTML)
  - CORS restricted to averagejoematt.com
"""

import json
import time
import logging
import os
import re
import hashlib
from datetime import datetime, timezone, timedelta
from decimal import Decimal

logger = logging.getLogger(__name__)

# Anthropic API key — fetched from Secrets Manager on cold start
_anthropic_key = None

def _get_anthropic_key():
    global _anthropic_key
    if _anthropic_key:
        return _anthropic_key
    import boto3
    sm = boto3.client("secretsmanager", region_name="us-west-2")
    resp = sm.get_secret_value(SecretId="life-platform/anthropic-api-key")
    _anthropic_key = resp["SecretString"]
    return _anthropic_key


def _rate_check(ip_hash: str, table) -> tuple[bool, int]:
    """
    Check rate limit: 5 questions per IP-hash per hour.
    Uses DynamoDB with TTL for automatic cleanup.
    Returns (allowed: bool, remaining: int).
    """
    pk = f"RATELIMIT#ask#{ip_hash}"
    now = int(time.time())
    hour_ago = now - 3600
    ttl_expiry = now + 7200  # Clean up after 2 hours

    # Query recent requests
    from boto3.dynamodb.conditions import Key
    resp = table.query(
        KeyConditionExpression=Key("pk").eq(pk) & Key("sk").gte(f"TS#{hour_ago}"),
    )
    count = len(resp.get("Items", []))

    if count >= 5:
        return False, 0

    # Log this request
    table.put_item(Item={
        "pk": pk,
        "sk": f"TS#{now}",
        "ttl": ttl_expiry,
    })

    return True, 5 - count - 1


def _sanitize_question(q: str) -> str:
    """Sanitize user question."""
    q = q.strip()[:500]  # Max 500 chars
    q = re.sub(r'<[^>]+>', '', q)  # Strip HTML
    q = re.sub(r'[^\w\s\?\.\,\!\'\"\-\(\)\/\%\#\@]', '', q)  # Allow safe chars
    return q


def _fetch_context(table, user_prefix: str) -> dict:
    """
    Fetch sanitized aggregate data for the AI prompt.
    Only pre-computed aggregates — never raw records.
    """
    from boto3.dynamodb.conditions import Key

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")

    context = {}

    # Latest Withings (weight)
    pk = f"{user_prefix}withings"
    resp = table.query(KeyConditionExpression=Key("pk").eq(pk), ScanIndexForward=False, Limit=1)
    items = resp.get("Items", [])
    if items:
        context["weight_lbs"] = float(items[0].get("weight_lbs", 0))

    # Latest Whoop (recovery, HRV, sleep)
    pk = f"{user_prefix}whoop"
    resp = table.query(KeyConditionExpression=Key("pk").eq(pk), ScanIndexForward=False, Limit=1)
    items = resp.get("Items", [])
    if items:
        w = items[0]
        context["hrv_ms"] = float(w.get("hrv", 0))
        context["rhr_bpm"] = float(w.get("resting_heart_rate", 0))
        context["recovery_pct"] = float(w.get("recovery_score", 0))
        context["sleep_hours"] = float(w.get("sleep_duration_hours", 0))

    # Character sheet
    pk = f"{user_prefix}character_sheet"
    for d in [today, yesterday]:
        resp = table.get_item(Key={"pk": pk, "sk": f"DATE#{d}"})
        record = resp.get("Item")
        if record:
            context["character_level"] = float(record.get("character_level", 1))
            context["character_tier"] = record.get("character_tier", "Foundation")
            pillars = {}
            for p in ["sleep", "movement", "nutrition", "metabolic", "mind", "relationships", "consistency"]:
                pd = record.get(f"pillar_{p}", {})
                pillars[p] = {
                    "level": float(pd.get("level", 1)),
                    "raw_score": float(pd.get("raw_score", 0)),
                    "tier": pd.get("tier", "Foundation"),
                }
            context["pillars"] = pillars
            break

    # Habit streaks
    pk = f"{user_prefix}habit_scores"
    resp = table.query(KeyConditionExpression=Key("pk").eq(pk), ScanIndexForward=False, Limit=1)
    items = resp.get("Items", [])
    if items:
        context["tier0_streak"] = int(items[0].get("t0_perfect_streak", 0) or 0)
        context["tier0_pct"] = round(
            float(items[0].get("tier0_done", 0)) / max(float(items[0].get("tier0_total", 1)), 1) * 100
        )

    return context


def _build_system_prompt(ctx: dict) -> str:
    pillars_str = ""
    if "pillars" in ctx:
        pillars_str = "\n".join(
            f"    {name}: level {p['level']:.0f}, score {p['raw_score']:.1f}, tier {p['tier']}"
            for name, p in ctx["pillars"].items()
        )

    return f"""You are the AI behind Matthew Walker's Life Platform — a personal health intelligence system tracking 19 data sources (Whoop, Garmin, Eight Sleep, Withings, MacroFactor, CGM, Habitify, Todoist, and more).

You answer questions about Matthew's REAL health data. Be specific with numbers. Use a direct, data-driven voice. No fluff.

CURRENT DATA:
  Weight: {ctx.get('weight_lbs', '?')} lbs (started 302, goal 185)
  HRV: {ctx.get('hrv_ms', '?')} ms
  RHR: {ctx.get('rhr_bpm', '?')} bpm
  Recovery: {ctx.get('recovery_pct', '?')}%
  Sleep: {ctx.get('sleep_hours', '?')} hours
  Character level: {ctx.get('character_level', '?')} (tier: {ctx.get('character_tier', '?')})
  T0 habit streak: {ctx.get('tier0_streak', '?')} days ({ctx.get('tier0_pct', '?')}% completion)
  Pillars:
{pillars_str or '    Not available'}

RULES:
- Answer from the data above. If you don't have data to answer, say so.
- Be specific: "HRV is 54ms" not "HRV is moderate."
- This is N=1 data. Always note this when making comparative claims.
- Never give medical advice. Say "the data shows X" not "you should do Y."
- Keep answers concise: 2-4 short paragraphs max.
- Format numbers with units. Bold key findings with **asterisks**.
- If asked about trends you can't see in a snapshot, explain what would be needed."""


def handle_ask(event, table, user_prefix: str):
    """
    POST /api/ask
    Accepts { "question": "..." }
    Returns { "answer": "..." }
    """
    # Parse body
    try:
        body = json.loads(event.get("body", "{}"))
    except (json.JSONDecodeError, TypeError):
        return _error(400, "Invalid JSON body")

    question = body.get("question", "").strip()
    if not question:
        return _error(400, "Missing 'question' field")

    question = _sanitize_question(question)
    if len(question) < 5:
        return _error(400, "Question too short")

    # Rate limit by IP hash
    source_ip = (
        event.get("requestContext", {}).get("http", {}).get("sourceIp") or
        event.get("requestContext", {}).get("identity", {}).get("sourceIp") or
        "unknown"
    )
    ip_hash = hashlib.sha256(source_ip.encode()).hexdigest()[:16]

    allowed, remaining = _rate_check(ip_hash, table)
    if not allowed:
        return {
            "statusCode": 429,
            "headers": {
                **CORS_HEADERS,
                "Retry-After": "3600",
            },
            "body": json.dumps({"error": "Rate limit exceeded. 5 questions per hour.", "remaining": 0}),
        }

    # Fetch sanitized context
    ctx = _fetch_context(table, user_prefix)
    system_prompt = _build_system_prompt(ctx)

    # Call Anthropic API
    try:
        import httpx
    except ImportError:
        # Fallback to urllib if httpx not available
        import urllib.request

    api_key = _get_anthropic_key()

    request_body = json.dumps({
        "model": "claude-haiku-4-5-20251001",
        "max_tokens": 600,
        "system": system_prompt,
        "messages": [{"role": "user", "content": question}],
    })

    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=request_body.encode(),
        headers={
            "Content-Type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read())
    except Exception as e:
        logger.error(f"[ask] Anthropic API call failed: {e}")
        return _error(503, "AI service temporarily unavailable")

    answer = ""
    for block in result.get("content", []):
        if block.get("type") == "text":
            answer += block["text"]

    return {
        "statusCode": 200,
        "headers": {
            **CORS_HEADERS,
            "Cache-Control": "no-store",  # Never cache personalized AI answers
        },
        "body": json.dumps({
            "answer": answer,
            "remaining": remaining,
            "model": "claude-haiku-4-5",
        }),
    }
