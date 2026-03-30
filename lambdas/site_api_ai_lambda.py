"""
site_api_ai_lambda.py — AI endpoints for averagejoematt.com (/api/ask, /api/board_ask)

Split from site_api_lambda.py (ADR-036 fix) to isolate AI endpoint concurrency.
AI calls make sequential Anthropic Haiku invocations (up to 6 for board_ask) which
can take 3-20s. By running in a separate Lambda with reserved_concurrent_executions=2,
a traffic spike on AI endpoints cannot starve the data-serving Lambda.

Endpoints:
  POST /api/ask       — AI Q&A with health data context (5 anon / 20 subscriber per hour)
  POST /api/board_ask — 6-persona board panel answers (5 per IP per hour)

IAM: Read-only DynamoDB + S3 config + Secrets Manager (site-api-ai-key). No writes.
"""

import hashlib
import hmac as _hmac
import base64 as _b64
import json
import logging
import os
import re
import time
import urllib.request
from datetime import datetime, timezone, timedelta
from decimal import Decimal

import boto3
from boto3.dynamodb.conditions import Key

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# ── Config ─────────────────────────────────────────────────
TABLE_NAME  = os.environ.get("TABLE_NAME", "life-platform")
USER_ID     = os.environ.get("USER_ID", "matthew")
USER_PREFIX = f"USER#{USER_ID}#SOURCE#"
DDB_REGION  = os.environ.get("DYNAMODB_REGION", "us-west-2")
S3_REGION   = os.environ.get("S3_REGION", "us-west-2")

# R17-04: Separate Anthropic key for site-api — injected via CDK env var
AI_SECRET_NAME = os.environ.get("AI_SECRET_NAME", "life-platform/site-api-ai-key")
# R17-11: env-overridable model string — avoids silent deprecation failures
AI_MODEL_HAIKU = os.environ.get("AI_MODEL_HAIKU", "claude-haiku-4-5-20251001")

# ── AWS clients (module-level for warm container reuse) ────
dynamodb = boto3.resource("dynamodb", region_name=DDB_REGION)
table    = dynamodb.Table(TABLE_NAME)

# ── CORS headers ───────────────────────────────────────────
CORS_ORIGIN = os.environ.get("CORS_ORIGIN", "https://averagejoematt.com")
CORS_HEADERS = {
    "Access-Control-Allow-Origin":  CORS_ORIGIN,
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type, X-Subscriber-Token",
    "Access-Control-Max-Age":       "3600",
    "Content-Type":                 "application/json",
    "X-Content-Type-Options":       "nosniff",
    "X-Frame-Options":              "DENY",
    "Strict-Transport-Security":    "max-age=31536000; includeSubDomains",
}

# ── In-memory rate limit stores (warm container state) ─────
_ask_rate_store: dict = {}    # ip_hash -> list of timestamps
_board_rate_store: dict = {}  # ip_hash -> list of timestamps
BOARD_RATE_LIMIT = 5  # 5 req/IP/hr — matches WAF rate limit tier; each call makes up to 6 Haiku calls

# ── Anthropic API key cache ────────────────────────────────
_anthropic_key_cache = None

# ── Content safety filter cache ────────────────────────────
_content_filter_cache = None

# ── Subscriber token secret cache ──────────────────────────
_token_secret_cache = None


# ── Helper functions ───────────────────────────────────────

def _decimal_to_float(obj):
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, dict):
        return {k: _decimal_to_float(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_decimal_to_float(i) for i in obj]
    return obj


def _latest_item(source: str) -> dict | None:
    """Get the most recent item for a source."""
    pk = f"{USER_PREFIX}{source}"
    resp = table.query(
        KeyConditionExpression=Key("pk").eq(pk),
        ScanIndexForward=False,
        Limit=1,
    )
    items = _decimal_to_float(resp.get("Items", []))
    return items[0] if items else None


def _error(status: int, message: str) -> dict:
    return {
        "statusCode": status,
        "headers": CORS_HEADERS,
        "body": json.dumps({"error": message}),
    }


def _get_anthropic_key():
    """Fetch Anthropic API key from Secrets Manager (cached after first call)."""
    global _anthropic_key_cache
    if _anthropic_key_cache:
        return _anthropic_key_cache
    try:
        sm = boto3.client("secretsmanager", region_name="us-west-2")
        resp = sm.get_secret_value(SecretId=AI_SECRET_NAME)
        _anthropic_key_cache = resp["SecretString"]
        return _anthropic_key_cache
    except Exception as e:
        logger.error(f"[ask] Failed to fetch API key from {AI_SECRET_NAME}: {e}")
        return None


def _get_token_secret() -> str:
    """Derive token signing secret from the existing Anthropic API key."""
    global _token_secret_cache
    if _token_secret_cache:
        return _token_secret_cache
    api_key = _get_anthropic_key()
    if not api_key:
        logger.error("[token_secret] No API key available")
        raise RuntimeError("Token signing secret unavailable")
    _token_secret_cache = hashlib.sha256(f"subscriber-token-v1:{api_key}".encode()).hexdigest()
    return _token_secret_cache


def _validate_subscriber_token(token: str) -> bool:
    """Return True if token is valid and unexpired."""
    try:
        decoded = _b64.urlsafe_b64decode(token.encode()).decode()
        parts = decoded.split(":")
        if len(parts) != 3:
            return False
        email, expires_str, provided_sig = parts
        if int(time.time()) > int(expires_str):
            return False
        payload = f"{email}:{expires_str}"
        secret = _get_token_secret().encode()
        expected = _hmac.new(secret, payload.encode(), digestmod='sha256').hexdigest()[:32]
        return _hmac.compare_digest(provided_sig, expected)
    except Exception:
        return False


def _load_content_filter():
    """Load blocked terms from S3 config/content_filter.json. Cached after first call."""
    global _content_filter_cache
    if _content_filter_cache is not None:
        return _content_filter_cache
    try:
        S3_BUCKET = os.environ.get("S3_BUCKET", "matthew-life-platform")
        s3 = boto3.client("s3", region_name=S3_REGION)
        resp = s3.get_object(Bucket=S3_BUCKET, Key="config/content_filter.json")
        _content_filter_cache = json.loads(resp["Body"].read())
    except Exception as e:
        logger.warning(f"[content_filter] Failed to load from S3: {e}")
        _content_filter_cache = {
            "blocked_vices": ["No porn", "No marijuana"],
            "blocked_vice_keywords": ["porn", "pornography", "marijuana", "cannabis", "weed", "thc"],
        }
    return _content_filter_cache


def _scrub_blocked_terms(text: str) -> str:
    """Remove any mention of blocked terms from public-facing text."""
    cf = _load_content_filter()
    result = text
    for term in cf.get("blocked_vice_keywords", []):
        result = re.compile(re.escape(term), re.IGNORECASE).sub("", result)
    for vice in cf.get("blocked_vices", []):
        result = re.compile(re.escape(vice), re.IGNORECASE).sub("", result)
    result = re.sub(r'\[filtered\]', '', result)
    result = re.sub(r'\s{2,}', ' ', result)
    return result.strip()


def _emit_rate_limit_metric(endpoint: str) -> None:
    """OBS-03: EMF metric emitted when a rate limit is hit."""
    try:
        emf = {
            "_aws": {
                "Timestamp": int(time.time() * 1000),
                "CloudWatchMetrics": [{
                    "Namespace": "LifePlatform/SiteApiAi",
                    "Dimensions": [["Endpoint"]],
                    "Metrics": [{"Name": "RateLimitHit", "Unit": "Count"}],
                }],
            },
            "Endpoint": endpoint,
            "RateLimitHit": 1,
        }
        print(json.dumps(emf))
    except Exception:
        pass


def _ask_rate_check(ip_hash: str, limit: int = 5) -> tuple:
    """Rate limit: N questions per IP-hash per hour (in-memory, warm container state)."""
    now = int(time.time())
    hour_ago = now - 3600
    timestamps = [t for t in _ask_rate_store.get(ip_hash, []) if t > hour_ago]
    if len(timestamps) >= limit:
        return False, 0
    timestamps.append(now)
    _ask_rate_store[ip_hash] = timestamps[-50:]
    return True, limit - len(timestamps)


def _ask_fetch_context() -> dict:
    """Fetch sanitized aggregate data for the AI prompt."""
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    yesterday_str = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")
    ctx = {}
    w = _latest_item("withings")
    if w and w.get("weight_lbs"):
        ctx["weight_lbs"] = float(w["weight_lbs"])
    wh = _latest_item("whoop")
    if wh:
        if wh.get("hrv"): ctx["hrv_ms"] = float(wh["hrv"])
        if wh.get("resting_heart_rate"): ctx["rhr_bpm"] = float(wh["resting_heart_rate"])
        if wh.get("recovery_score"): ctx["recovery_pct"] = float(wh["recovery_score"])
        if wh.get("sleep_duration_hours"): ctx["sleep_hours"] = float(wh["sleep_duration_hours"])
    cs_pk = f"{USER_PREFIX}character_sheet"
    for d in [today_str, yesterday_str]:
        resp = table.get_item(Key={"pk": cs_pk, "sk": f"DATE#{d}"})
        rec = _decimal_to_float(resp.get("Item"))
        if rec:
            ctx["character_level"] = float(rec.get("character_level", 1))
            ctx["character_tier"] = rec.get("character_tier", "Foundation")
            pillars = {}
            for p in ["sleep", "movement", "nutrition", "metabolic", "mind", "relationships", "consistency"]:
                pd = rec.get(f"pillar_{p}", {})
                pillars[p] = {"level": float(pd.get("level", 1)), "raw_score": float(pd.get("raw_score", 0)), "tier": pd.get("tier", "Foundation")}
            ctx["pillars"] = pillars
            break
    hs_pk = f"{USER_PREFIX}habit_scores"
    hs_resp = table.query(KeyConditionExpression=Key("pk").eq(hs_pk), ScanIndexForward=False, Limit=1)
    hs_items = _decimal_to_float(hs_resp.get("Items", []))
    if hs_items:
        ctx["tier0_streak"] = int(hs_items[0].get("t0_perfect_streak", 0) or 0)
    return ctx


# WR-40: Question safety filter — block sensitive query categories
_ASK_BLOCKED_PATTERNS = [
    r'\b(ssn|social.?security|passport|credit.?card|bank.?account|routing.?number)\b',
    r'\b(password|api.?key|secret|token|credential)\b',
    r'\b(address|phone.?number|email.?address|zip.?code|employer.?name)\b',
    r'\b(salary|income|net.?worth|financial|tax)\b',
    r'\b(suicid|self.?harm|eating.?disorder|mental.?illness|diagnos)\b',
    r'\b(medication.?name|prescription|dosage|drug.?interaction)\b',
]


def _ask_question_safe(question: str) -> tuple:
    """Returns (is_safe, reason). Blocks sensitive query categories."""
    q_lower = question.lower()
    for pattern in _ASK_BLOCKED_PATTERNS:
        if re.search(pattern, q_lower):
            return False, "This question touches on sensitive personal data that the platform doesn't share publicly. Try asking about weight, sleep, HRV, training, habits, or nutrition trends instead."
    return True, ""


def _ask_build_prompt(ctx: dict) -> str:
    pillars_str = ""
    if "pillars" in ctx:
        pillars_str = "\n".join(
            f"    {n}: level {p['level']:.0f}, score {p['raw_score']:.1f}, tier {p['tier']}"
            for n, p in ctx["pillars"].items()
        )
    return f"""You are the AI behind Matthew Walker's Life Platform — a personal health intelligence system tracking 19 data sources.

CURRENT DATA:
  Weight: {ctx.get('weight_lbs', '?')} lbs (started 307, goal 185)
  HRV: {ctx.get('hrv_ms', '?')} ms
  RHR: {ctx.get('rhr_bpm', '?')} bpm
  Recovery: {ctx.get('recovery_pct', '?')}%
  Sleep: {ctx.get('sleep_hours', '?')} hours
  Character level: {ctx.get('character_level', '?')} (tier: {ctx.get('character_tier', '?')})
  T0 habit streak: {ctx.get('tier0_streak', '?')} days
  Pillars:
{pillars_str or '    Not available'}

RULES:
- Answer from the data above. If you don't have data, say so honestly.
- Be specific: "HRV is 54ms" not "HRV is moderate."
- N=1 data. Note this for comparative claims.
- Never give medical advice. Say "the data shows X" not "you should do Y."
- Keep answers concise: 2-4 short paragraphs max.
- Bold key findings with **asterisks**.

SAFETY (WR-40):
- NEVER reveal: addresses, phone numbers, emails, employer details, financial info, passwords, API keys.
- NEVER provide: medical diagnoses, medication recommendations, mental health assessments.
- Stick to publicly shared health metrics: weight, HRV, sleep, recovery, training, habits, nutrition trends.
- If asked about something outside your data, say "I don't have that data" — don't speculate.
- CONTENT FILTER: NEVER mention porn, pornography, marijuana, cannabis, weed, THC, or any related terms.
- If asked about these topics, respond only with: I don't have data on that specific topic."""


# ── Board of Directors persona definitions ─────────────────

PERSONA_PROMPTS = {
    "vasquez": {
        "name": "Dr. Elena Vasquez",
        "title": "Metabolic Medicine & Longevity",
        "system": (
            "You are Dr. Elena Vasquez, MD, a metabolic medicine physician specializing in longevity. "
            "Focus on: VO2max, Zone 2 training, strength, metabolic health, and the major drivers of chronic disease. "
            "Evidence-based and nuanced. Distinguish strong evidence from speculation. "
            "Your perspective is informed by current peer-reviewed research. Do not reference specific researchers by name. "
            "Use first person. 3-5 sentences. Note N=1 for any comparative claim. "
            "Never give medical advice — reference a physician only if clinically urgent."
        ),
    },
    "okafor": {
        "name": "Dr. James Okafor",
        "title": "Performance Neuroscience",
        "system": (
            "You are Dr. James Okafor PhD, a performance neuroscientist. "
            "Focus on: sleep architecture, light exposure, stress resilience, neuroplasticity, and dopamine. "
            "Explain the mechanism first, then the protocol. "
            "Your perspective is informed by current peer-reviewed research. Do not reference specific researchers by name. "
            "Use phrases like 'the data are clear' and 'the mechanism here is'. "
            "3-5 sentences. Actionable and specific."
        ),
    },
    "patrick": {
        "name": "Rhonda Patrick",
        "title": "Cellular Biology & Nutrition",
        "system": (
            "You are Rhonda Patrick PhD, biochemist and FoundMyFitness founder. "
            "Focus on: micronutrients, cellular resilience, omega-3s, heat/cold exposure, inflammation. "
            "Cite mechanisms. Use 'the research shows' and 'at the cellular level'. "
            "Thorough, not reductive. 3-5 sentences."
        ),
    },
    "norton": {
        "name": "Layne Norton",
        "title": "Evidence-Based Nutrition",
        "system": (
            "You are Layne Norton PhD, nutrition scientist and evidence-based coach. "
            "Focus on: protein synthesis, body composition, muscle retention in deficit. "
            "No-nonsense, skeptical of broscience. "
            "Use 'the evidence actually shows' and 'people get this wrong because'. "
            "Emphasize protein quality, leucine threshold, and adherence. 3-5 sentences."
        ),
    },
    "clear": {
        "name": "James Clear",
        "title": "Habit Architecture",
        "system": (
            "You are James Clear, author of Atomic Habits. "
            "Focus on: identity-based change, the four laws of behavior change, habit stacking, systems over goals. "
            "Aphorism-style language. Make abstract ideas concrete with specific examples. "
            "3-5 sentences. Actionable and memorable."
        ),
    },
    "goggins": {
        "name": "David Goggins",
        "title": "Mental Toughness",
        "system": (
            "You are David Goggins, retired Navy SEAL and ultra-endurance athlete. "
            "You believe most people quit at 40% capacity and that the mind is the limit. "
            "Brutally honest, intense, no coddling. Use 'stay hard' and 'nobody is coming to save you'. "
            "3-5 sentences. High energy."
        ),
    },
}


# ── Lambda Handler ─────────────────────────────────────────

def lambda_handler(event, context):
    """Routes /api/ask (POST) and /api/board_ask (POST) only."""
    if event.get("healthcheck"):
        return {"statusCode": 200, "body": "ok"}

    path = event.get("rawPath") or event.get("path", "/")
    method = (
        event.get("requestContext", {}).get("http", {}).get("method")
        or event.get("httpMethod", "GET")
    ).upper()

    # CORS preflight
    if method == "OPTIONS":
        return {"statusCode": 200, "headers": CORS_HEADERS, "body": ""}

    # ── POST /api/board_ask ────────────────────────────────
    if path == "/api/board_ask":
        if method != "POST":
            return _error(405, "Use POST method")
        return _handle_board_ask(event)

    # ── POST /api/ask ──────────────────────────────────────
    if path == "/api/ask":
        if method != "POST":
            return _error(405, "Use POST method")
        return _handle_ask(event)

    return _error(404, "Not found")


def _handle_ask(event: dict) -> dict:
    """POST /api/ask — AI Q&A with health data context."""
    source_ip = (
        event.get("requestContext", {}).get("http", {}).get("sourceIp")
        or event.get("requestContext", {}).get("identity", {}).get("sourceIp")
        or "unknown"
    )
    try:
        question = json.loads(event.get("body") or "{}").get("question", "").strip()[:500]
        question = re.sub(r'<[^>]+>', '', question)
        if len(question) < 5:
            return _error(400, "Question too short")

        # WR-40: Safety filter
        is_safe, safety_reason = _ask_question_safe(question)
        if not is_safe:
            return {
                "statusCode": 200,
                "headers": {**CORS_HEADERS, "Cache-Control": "no-store"},
                "body": json.dumps({"answer": safety_reason, "remaining": 999, "filtered": True}),
            }

        ip_hash = hashlib.sha256(source_ip.encode()).hexdigest()[:16]
        # WR-24: Check for valid subscriber token → higher rate limit
        sub_token = (event.get("headers") or {}).get("x-subscriber-token", "")
        is_subscriber = bool(sub_token) and _validate_subscriber_token(sub_token)
        rate_limit = 20 if is_subscriber else 5
        allowed, remaining = _ask_rate_check(ip_hash, limit=rate_limit)
        if not allowed:
            limit_msg = "20" if is_subscriber else "5"
            _emit_rate_limit_metric("ask")
            return {
                "statusCode": 429,
                "headers": {**CORS_HEADERS, "Retry-After": "3600"},
                "body": json.dumps({"error": f"Rate limit exceeded. {limit_msg} questions per hour.", "remaining": 0}),
            }

        api_key = _get_anthropic_key()
        if not api_key:
            return _error(503, "AI service configuration error")

        ctx = _ask_fetch_context()
        system_prompt = _ask_build_prompt(ctx)

        req_body = json.dumps({
            "model": AI_MODEL_HAIKU,
            "max_tokens": 600,
            "system": system_prompt,
            "messages": [{"role": "user", "content": question}],
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

        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read())

        answer = "".join(b["text"] for b in result.get("content", []) if b.get("type") == "text")

        return {
            "statusCode": 200,
            "headers": {**CORS_HEADERS, "Cache-Control": "no-store"},
            "body": json.dumps({"answer": _scrub_blocked_terms(answer), "remaining": remaining}),
        }
    except Exception as e:
        logger.error(f"[site_api_ai] /api/ask failed: {e}")
        return _error(500, "AI service error")


def _handle_board_ask(event: dict) -> dict:
    """POST /api/board_ask — 6-persona board panel answers."""
    source_ip = (
        event.get("requestContext", {}).get("http", {}).get("sourceIp")
        or event.get("requestContext", {}).get("identity", {}).get("sourceIp")
        or "unknown"
    )
    ip_hash = hashlib.sha256(source_ip.encode()).hexdigest()[:16]
    now = int(time.time())
    hour_ago = now - 3600
    board_ts = [t for t in _board_rate_store.get(ip_hash, []) if t > hour_ago]
    if len(board_ts) >= BOARD_RATE_LIMIT:
        _emit_rate_limit_metric("board_ask")
        return {
            "statusCode": 429,
            "headers": {**CORS_HEADERS, "Retry-After": "3600"},
            "body": json.dumps({"error": "Rate limit reached. Try again in an hour."}),
        }
    board_ts.append(now)
    _board_rate_store[ip_hash] = board_ts[-20:]

    try:
        body = json.loads(event.get("body") or "{}")
    except Exception:
        return {"statusCode": 400, "headers": CORS_HEADERS, "body": json.dumps({"error": "Invalid JSON"})}

    question = re.sub(r"<[^>]+>", "", (body.get("question") or "").strip())[:500]
    if len(question) < 5:
        return {"statusCode": 400, "headers": CORS_HEADERS, "body": json.dumps({"error": "Question too short"})}

    requested = body.get("personas") or list(PERSONA_PROMPTS.keys())
    personas = [p for p in requested if p in PERSONA_PROMPTS][:6]
    if not personas:
        personas = ["vasquez", "okafor", "clear"]

    api_key = _get_anthropic_key()
    if not api_key:
        return {"statusCode": 503, "headers": CORS_HEADERS, "body": json.dumps({"error": "AI service unavailable"})}

    responses = {}
    for pid in personas:
        p = PERSONA_PROMPTS[pid]
        try:
            req_body = json.dumps({
                "model": AI_MODEL_HAIKU,
                "max_tokens": 300,
                "system": p["system"],
                "messages": [{"role": "user", "content": question}],
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
            with urllib.request.urlopen(req, timeout=20) as r:
                result = json.loads(r.read())
            responses[pid] = _scrub_blocked_terms("".join(b["text"] for b in result.get("content", []) if b.get("type") == "text"))
        except Exception as e:
            logger.error(f"[board_ask] {pid} failed: {e}")
            responses[pid] = f"[{p['name']} is temporarily unavailable]"

    return {
        "statusCode": 200,
        "headers": {**CORS_HEADERS, "Cache-Control": "no-store"},
        "body": json.dumps({"responses": responses}),
    }
