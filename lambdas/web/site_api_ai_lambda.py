"""
site_api_ai_lambda.py — AI endpoints for averagejoematt.com (/api/ask, /api/board_ask)

Split from site_api_lambda.py (ADR-036 fix) to isolate AI endpoint concurrency.
AI calls make sequential Anthropic Haiku invocations (up to 6 for board_ask) which
can take 3-20s. By running in a separate Lambda with reserved_concurrent_executions=2,
a traffic spike on AI endpoints cannot starve the data-serving Lambda.

Endpoints:
  POST /api/ask       — AI Q&A with health data context (5 anon / 20 subscriber per hour)
  POST /api/board_ask — 6-persona board panel answers (5 per IP per hour)

IAM: Read DynamoDB + S3 config + Secrets Manager (site-api-ai-key). Writes are
scoped by LeadingKeys to RATE#* (rate-limit counters) and COACH#* (#531: the
board_ask episodic write-back — a coach's public answers enter its own memory).
"""

import base64 as _b64
import hashlib
import hmac as _hmac
import json
import logging
import os
import re
import time
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import boto3
import privacy_guard  # deterministic real-name + vice scrub (layer module)
from boto3.dynamodb.conditions import Key
from constants import EXPERIMENT_BASELINE_WEIGHT_LBS  # ADR-058
from phase_filter import with_phase_filter  # ADR-058
from source_registry import public_board_sources, public_paused_sources  # #387: derived source count

from web.site_api_common import _scrub_blocked_terms as _scrub_blocked_terms_base  # canonical shared helpers (#368)

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# ── Config ─────────────────────────────────────────────────
TABLE_NAME = os.environ.get("TABLE_NAME", "life-platform")
USER_ID = os.environ.get("USER_ID", "matthew")
USER_PREFIX = f"USER#{USER_ID}#SOURCE#"
DDB_REGION = os.environ.get("DYNAMODB_REGION", "us-west-2")
S3_REGION = os.environ.get("S3_REGION", "us-west-2")

# R17-04: Separate Anthropic key for site-api — injected via CDK env var
AI_SECRET_NAME = os.environ.get("AI_SECRET_NAME", "life-platform/site-api-ai-key")
# R17-11: env-overridable model string — avoids silent deprecation failures
AI_MODEL_HAIKU = os.environ.get("AI_MODEL_HAIKU", "claude-haiku-4-5-20251001")

# #387: the prompt's source count derives from the canonical registry — the
# old hardcoded literal (nineteen) had drifted from the real pipeline board.
_LIVE_SOURCE_COUNT = len(public_board_sources())
_PAUSED_SOURCE_COUNT = len(public_paused_sources())

# ── AWS clients (module-level for warm container reuse) ────
dynamodb = boto3.resource("dynamodb", region_name=DDB_REGION)
table = dynamodb.Table(TABLE_NAME)
_cw = boto3.client("cloudwatch", region_name=DDB_REGION)
_LAMBDA_NAME = os.environ.get("AWS_LAMBDA_FUNCTION_NAME", "life-platform-site-api-ai")

# #531: voice specs live in S3 config/coaches/ — lazy client, role has config/* read.
S3_BUCKET = os.environ.get("S3_BUCKET", "matthew-life-platform")
_s3 = None


def _s3_client():
    global _s3
    if _s3 is None:
        _s3 = boto3.client("s3", region_name=S3_REGION)
    return _s3


def _emit_token_metrics(usage: dict, endpoint: str) -> None:
    """V2 follow-up (2026-05-19): inline token telemetry (no shared layer).

    Mirrors retry_utils._emit_token_metrics but copy-inlined because site-api-ai
    is intentionally layer-less for cold-start performance. Emits to the same
    LifePlatform/AI namespace as the other AI Lambdas, dimensioned by both
    LambdaFunction and Endpoint so /api/ask and /api/board_ask can be graphed
    separately.
    """
    if not isinstance(usage, dict) or not usage:
        return
    try:
        dims_base = [
            {"Name": "LambdaFunction", "Value": _LAMBDA_NAME},
            {"Name": "Endpoint", "Value": endpoint},
        ]
        in_tok = int(usage.get("input_tokens", 0) or 0)
        out_tok = int(usage.get("output_tokens", 0) or 0)
        cache_w = int(usage.get("cache_creation_input_tokens", 0) or 0)
        cache_r = int(usage.get("cache_read_input_tokens", 0) or 0)
        metric_data = [
            {"MetricName": "AnthropicInputTokens", "Dimensions": dims_base, "Value": in_tok, "Unit": "Count"},
            {"MetricName": "AnthropicOutputTokens", "Dimensions": dims_base, "Value": out_tok, "Unit": "Count"},
        ]
        if cache_w or cache_r:
            metric_data.append({"MetricName": "AnthropicCacheWriteTokens", "Dimensions": dims_base, "Value": cache_w, "Unit": "Count"})
            metric_data.append({"MetricName": "AnthropicCacheReadTokens", "Dimensions": dims_base, "Value": cache_r, "Unit": "Count"})
        _cw.put_metric_data(Namespace="LifePlatform/AI", MetricData=metric_data)
    except Exception as e:
        logger.warning(f"site_api_ai token-metric emit failed (non-fatal): {e}")


# ── CORS headers ───────────────────────────────────────────
CORS_ORIGIN = os.environ.get("CORS_ORIGIN", "https://averagejoematt.com")
CORS_HEADERS = {
    "Access-Control-Allow-Origin": CORS_ORIGIN,
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type, X-Subscriber-Token",
    "Access-Control-Max-Age": "3600",
    "Content-Type": "application/json",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
    # Phase 2.8 (2026-05-16): AI responses are personalized — never cache.
    # Prevents proxy/browser from serving one user's reply to another.
    "Cache-Control": "private, no-store, must-revalidate",
    "Pragma": "no-cache",
}

# ── Rate limiting (Phase 2.1, 2026-05-16): DynamoDB-backed ────
# Replaces in-memory dict which didn't survive warm-container distribution.
# Old stores kept as fallbacks if rate_limiter import fails.
_ask_rate_store: dict = {}  # legacy, only used if DDB rate_limiter fails
_board_rate_store: dict = {}  # legacy, only used if DDB rate_limiter fails
BOARD_RATE_LIMIT = 5  # 5 req/IP/hr — matches WAF rate limit tier; each call makes up to 6 Haiku calls

try:
    from rate_limiter import check_rate_limit as _ddb_rate_check

    _RATE_LIMITER_READY = True
except ImportError:
    _RATE_LIMITER_READY = False

# ── Anthropic API key cache ────────────────────────────────
_anthropic_key_cache = None

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
        **with_phase_filter(
            {  # ADR-058: hide pilot records
                "KeyConditionExpression": Key("pk").eq(pk),
                "ScanIndexForward": False,
                "Limit": 1,
            }
        )
    )
    items = _decimal_to_float(resp.get("Items", []))
    return items[0] if items else None


def _error(status: int, message: str) -> dict:
    return {
        "statusCode": status,
        "headers": CORS_HEADERS,
        "body": json.dumps({"error": message}),
    }


def _ai_paused_response():
    """If the budget tier has paused website AI (the tier-3 hard stop — ADR-100:
    readers degrade LAST), return a friendly HTTP-200 'paused' payload the
    frontend renders calmly; else None. Fail-open."""
    try:
        from budget_guard import allow

        if not allow("website_ai"):
            return {
                "statusCode": 200,
                "headers": {**CORS_HEADERS, "Cache-Control": "no-store"},
                "body": json.dumps(
                    {
                        "answer": (
                            "The AI assistant is paused for the rest of the month " "to stay within budget — it'll be back on the 1st."
                        ),
                        "paused": True,
                        "remaining": 0,
                    }
                ),
            }
    except Exception:
        pass
    return None


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


_SUBSCRIBER_TOKEN_SECRET_NAME = os.environ.get("SUBSCRIBER_TOKEN_SECRET_NAME", "life-platform/subscriber-token-secret")


def _get_token_secret() -> str:
    """Fetch the dedicated subscriber-token HMAC secret from Secrets Manager.
    #106 (2026-05-30). The pre-#106 fallback (a secret derived from the
    Anthropic API key) was removed 2026-06-12 — its 24h migration window
    expired 2026-05-31, and a loud failure beats silently signing with a
    derivable key."""
    global _token_secret_cache
    if _token_secret_cache:
        return _token_secret_cache
    try:
        sm = boto3.client("secretsmanager", region_name="us-west-2")
        _token_secret_cache = sm.get_secret_value(SecretId=_SUBSCRIBER_TOKEN_SECRET_NAME)["SecretString"]
        return _token_secret_cache
    except Exception as e:
        logger.error(f"[token_secret] Signing secret unavailable: {e}")
        raise RuntimeError("Token signing secret unavailable") from e


def _validate_subscriber_token(token: str) -> bool:
    """Return True if token is valid and unexpired. Signed with the dedicated
    secret only — the legacy dual-validation branch was removed 2026-06-12
    (every pre-migration token expired by 2026-06-01; token TTL is 24h)."""
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
        expected = _hmac.new(secret, payload.encode(), digestmod="sha256").hexdigest()[:32]
        return _hmac.compare_digest(provided_sig, expected)
    except Exception:
        return False


def _scrub_blocked_terms(text: str) -> str:
    """Vice scrub (canonical impl in site_api_common) + real-name redaction for AI responses.

    The base two-layer scrub (zero-width strip, literal removal, obfuscation
    fail-safe) lives in site_api_common._scrub_blocked_terms. This wrapper adds
    privacy_guard.scrub() for coach persona real-name redaction — AI-endpoint
    specific and not needed for non-AI content filtering.
    """
    result = _scrub_blocked_terms_base(text)
    if result == "I can't share that.":
        return result
    # Real-public-figure redaction (the coaches are fictional personas). privacy_guard
    # catches names the vice list doesn't — e.g. a persona channeling a real expert.
    return privacy_guard.scrub(result)[0]


def _emit_rate_limit_metric(endpoint: str) -> None:
    """OBS-03: EMF metric emitted when a rate limit is hit."""
    try:
        emf = {
            "_aws": {
                "Timestamp": int(time.time() * 1000),
                "CloudWatchMetrics": [
                    {
                        "Namespace": "LifePlatform/SiteApiAi",
                        "Dimensions": [["Endpoint"]],
                        "Metrics": [{"Name": "RateLimitHit", "Unit": "Count"}],
                    }
                ],
            },
            "Endpoint": endpoint,
            "RateLimitHit": 1,
        }
        print(json.dumps(emf))
    except Exception:
        pass


def _ask_rate_check(ip_hash: str, limit: int = 5) -> tuple:
    """Rate limit: N questions per IP-hash per hour.

    Phase 2.1 (2026-05-16): now uses DynamoDB atomic counters via
    rate_limiter.check_rate_limit — global enforcement across warm containers.
    Falls back to legacy in-memory dict if rate_limiter module unavailable.
    """
    if _RATE_LIMITER_READY:
        allowed, remaining, _retry = _ddb_rate_check(
            table,
            endpoint="ask",
            ip_hash=ip_hash,
            limit=limit,
            window_seconds=3600,
            fail_open=False,  # AI endpoint: a DDB blip must not unmeter Bedrock spend
        )
        return allowed, remaining
    # Legacy fallback (warm-container only)
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
        if wh.get("hrv"):
            ctx["hrv_ms"] = float(wh["hrv"])
        if wh.get("resting_heart_rate"):
            ctx["rhr_bpm"] = float(wh["resting_heart_rate"])
        if wh.get("recovery_score"):
            ctx["recovery_pct"] = float(wh["recovery_score"])
        if wh.get("sleep_duration_hours"):
            ctx["sleep_hours"] = float(wh["sleep_duration_hours"])
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
                pillars[p] = {
                    "level": float(pd.get("level", 1)),
                    "raw_score": float(pd.get("raw_score", 0)),
                    "tier": pd.get("tier", "Foundation"),
                }
            ctx["pillars"] = pillars
            break
    hs_pk = f"{USER_PREFIX}habit_scores"
    hs_resp = table.query(
        **with_phase_filter(  # ADR-058: hide pilot habit scores
            {"KeyConditionExpression": Key("pk").eq(hs_pk), "ScanIndexForward": False, "Limit": 1}
        )
    )
    hs_items = _decimal_to_float(hs_resp.get("Items", []))
    if hs_items:
        ctx["tier0_streak"] = int(hs_items[0].get("t0_perfect_streak", 0) or 0)
    # Fetch start/goal from profile for dynamic prompt injection
    try:
        # Canonical profile key — the old {USER_PREFIX}profile/PROFILE item never
        # existed, so this read silently fell back to constants (found 2026-06-12).
        prof_resp = table.get_item(Key={"pk": "USER#matthew", "sk": "PROFILE#v1"})
        prof = _decimal_to_float(prof_resp.get("Item", {}))
        ctx["start_weight"] = float(prof.get("journey_start_weight_lbs", EXPERIMENT_BASELINE_WEIGHT_LBS))
        ctx["goal_weight"] = float(prof.get("goal_weight_lbs", 185))
    except Exception:
        ctx["start_weight"] = EXPERIMENT_BASELINE_WEIGHT_LBS
        ctx["goal_weight"] = 185
    ctx["reads"] = _ask_fetch_computed_reads()
    return ctx


def _ask_fetch_computed_reads() -> dict:
    """#387: the drivers/trends/correlations the platform ALREADY computes,
    assembled server-side so the model narrates Python's work instead of
    confessing it only has a handful of latest numbers (or worse, asking the
    reader to supply Matthew's data). Every block is fail-soft — a missing
    compute just omits that read; ask still answers from the vitals."""
    reads: dict = {}

    # Canonical daily facts (computed_metrics → the same numbers coaches ground
    # on): weight trend rate + the protein trio the vitals block doesn't carry.
    try:
        from canonical_facts import build_canonical_facts

        facts = build_canonical_facts(_latest_item("computed_metrics") or {})
        if facts.get("weekly_rate_lbs") is not None:
            reads["weekly_rate_lbs"] = facts["weekly_rate_lbs"]
        if facts.get("protein_g_avg") is not None:
            reads["protein"] = {
                "avg_7d_g": facts["protein_g_avg"],
                "target_g": facts.get("protein_g_target"),
                "floor_g": facts.get("protein_g_floor"),
            }
    except Exception as e:
        logger.warning(f"[ask reads] canonical facts skipped: {e}")

    # Daily insight drivers (computed_insights): momentum + which metrics are
    # moving which way + habit strengths/weaknesses.
    try:
        ins = _latest_item("computed_insights") or {}
        if ins.get("momentum_signal"):
            reads["momentum"] = str(ins["momentum_signal"])[:300]
        for src_key, out_key in (("improving_metrics", "improving"), ("declining_metrics", "declining")):
            raw = ins.get(src_key)
            vals = json.loads(raw) if isinstance(raw, str) else raw
            if vals:
                reads[out_key] = [str(v)[:80] for v in vals][:4]
        if ins.get("strongest_habits"):
            reads["strongest_habits"] = [str(h)[:60] for h in ins["strongest_habits"]][:3]
        if ins.get("weakest_habits"):
            reads["weakest_habits"] = [str(h)[:60] for h in ins["weakest_habits"]][:3]
    except Exception as e:
        logger.warning(f"[ask reads] computed_insights skipped: {e}")

    # Adaptive-mode read (the platform's own morning verdict + its reasons —
    # this is the precomputed answer to "what drove today?").
    try:
        am = _latest_item("adaptive_mode") or {}
        if am.get("mode_label"):
            factors = am.get("factors") or {}
            reads["adaptive_mode"] = {
                "label": str(am["mode_label"])[:60],
                "score": am.get("engagement_score"),
                "factors": {str(k)[:30]: str(v)[:120] for k, v in factors.items() if v},
            }
    except Exception as e:
        logger.warning(f"[ask reads] adaptive_mode skipped: {e}")

    # Monthly motion (what_changed SNAPSHOT#current — trailing-30d vs prior-30d,
    # written weekly; real deltas only, honest_null on a flat month).
    try:
        wc = table.get_item(Key={"pk": f"{USER_PREFIX}what_changed", "sk": "SNAPSHOT#current"}).get("Item")
        wc = _decimal_to_float(wc or {})
        deltas = []
        for d in (wc.get("deltas") or [])[:6]:
            deltas.append(
                {
                    "label": d.get("label") or d.get("metric"),
                    "this_month_avg": d.get("this_month_avg"),
                    "prior_month_avg": d.get("prior_month_avg"),
                    "delta": d.get("delta"),
                    "unit": d.get("unit") or "",
                    "direction": d.get("direction"),
                }
            )
        if deltas:
            reads["month_deltas"] = deltas
    except Exception as e:
        logger.warning(f"[ask reads] what_changed skipped: {e}")

    # FDR-significant correlations (weekly_correlations) — the statistically
    # defensible pattern set, strongest first.
    try:
        resp = table.query(
            **with_phase_filter(
                {
                    "KeyConditionExpression": Key("pk").eq(f"{USER_PREFIX}weekly_correlations"),
                    "ScanIndexForward": False,
                    "Limit": 4,
                }
            )
        )
        pairs: dict = {}
        for item in _decimal_to_float(resp.get("Items", [])):
            corrs = item.get("correlations", {})
            if not isinstance(corrs, dict):
                continue
            for label, data in corrs.items():
                if not isinstance(data, dict) or not data.get("fdr_significant") or label in pairs:
                    continue
                pairs[label] = {
                    "a": str(data.get("metric_a", ""))[:40],
                    "b": str(data.get("metric_b", ""))[:40],
                    "r": round(float(data.get("pearson_r", 0) or 0), 2),
                    "n_days": int(data.get("n_days", 0) or 0),
                }
        if pairs:
            reads["correlations"] = sorted(pairs.values(), key=lambda p: -abs(p["r"]))[:5]
    except Exception as e:
        logger.warning(f"[ask reads] correlations skipped: {e}")

    # Presence (engagement_state — same public allowlist as /api/presence, so a
    # quiet stretch is narrated honestly instead of read as missing data).
    try:
        pres = table.get_item(Key={"pk": USER_PREFIX + "engagement_state", "sk": "STATE#current"}).get("Item")
        pres = _decimal_to_float(pres or {})
        if pres.get("presence_class"):
            reads["presence"] = {
                "class": str(pres["presence_class"])[:20],
                "gap_days": pres.get("gap_days"),
                "passive_still_flowing": bool(pres.get("passive_still_flowing")),
            }
    except Exception as e:
        logger.warning(f"[ask reads] presence skipped: {e}")

    return reads


def _ask_reads_block(reads: dict) -> str:
    """Render the computed reads for the prompt — compact, values verbatim."""
    if not reads:
        return ""
    lines = []
    am = reads.get("adaptive_mode")
    if am:
        score = f" ({am['score']:.0f}/100)" if isinstance(am.get("score"), (int, float)) else ""
        lines.append(f"  Today's computed mode: {am['label']}{score}")
        for k, v in (am.get("factors") or {}).items():
            lines.append(f"    - {k}: {v}")
    if reads.get("momentum"):
        lines.append(f"  Momentum read: {reads['momentum']}")
    if reads.get("improving"):
        lines.append(f"  Improving (7d): {', '.join(reads['improving'])}")
    if reads.get("declining"):
        lines.append(f"  Declining (7d): {', '.join(reads['declining'])}")
    if reads.get("strongest_habits"):
        lines.append(f"  Strongest habits: {', '.join(reads['strongest_habits'])}")
    if reads.get("weakest_habits"):
        lines.append(f"  Weakest habits: {', '.join(reads['weakest_habits'])}")
    if reads.get("weekly_rate_lbs") is not None:
        lines.append(f"  Weight trend: {reads['weekly_rate_lbs']:+.1f} lbs/week (computed)")
    pr = reads.get("protein")
    if pr:
        seg = f"  Protein: {pr['avg_7d_g']:.0f}g 7-day avg intake"
        if pr.get("target_g") is not None:
            seg += f" (target {pr['target_g']:.0f}g"
            seg += f", floor {pr['floor_g']:.0f}g)" if pr.get("floor_g") is not None else ")"
        lines.append(seg)
    for d in reads.get("month_deltas", []):
        lines.append(
            f"  30-day motion: {d['label']} {d['this_month_avg']} vs {d['prior_month_avg']} prior "
            f"({d['delta']:+g} {d['unit']}, {d['direction']})".rstrip()
        )
    for c in reads.get("correlations", []):
        direction = "higher" if c["r"] > 0 else "lower"
        lines.append(
            f"  Correlation (FDR-significant): higher {c['a']} tracks with {direction} {c['b']} (r={c['r']:+.2f}, n={c['n_days']} days)"
        )
    p = reads.get("presence")
    if p and p["class"] not in ("present", ""):
        gap = f" — {p['gap_days']:.0f} days since the last manual log" if isinstance(p.get("gap_days"), (int, float)) else ""
        passive = "; passive devices still flowing" if p.get("passive_still_flowing") else ""
        lines.append(f"  Presence: quiet stretch ({p['class']}){gap}{passive}")
    return "\n".join(lines)


# WR-40: Question safety filter — block sensitive query categories
_ASK_BLOCKED_PATTERNS = [
    r"\b(ssn|social.?security|passport|credit.?card|bank.?account|routing.?number)\b",
    r"\b(password|api.?key|secret|token|credential)\b",
    r"\b(address|phone.?number|email.?address|zip.?code|employer.?name)\b",
    r"\b(salary|income|net.?worth|financial|tax)\b",
    r"\b(suicid|self.?harm|eating.?disorder|mental.?illness|diagnos)\b",
    r"\b(medication.?name|prescription|dosage|drug.?interaction)\b",
]


def _ask_question_safe(question: str) -> tuple:
    """Returns (is_safe, reason). Blocks sensitive query categories."""
    q_lower = question.lower()
    for pattern in _ASK_BLOCKED_PATTERNS:
        if re.search(pattern, q_lower):
            return (
                False,
                "This question touches on sensitive personal data that the platform doesn't share publicly. Try asking about weight, sleep, HRV, training, habits, or nutrition trends instead.",
            )
    return True, ""


def _ask_build_prompt(ctx: dict) -> str:
    pillars_str = ""
    if "pillars" in ctx:
        pillars_str = "\n".join(
            f"    {n}: level {p['level']:.0f}, score {p['raw_score']:.1f}, tier {p['tier']}" for n, p in ctx["pillars"].items()
        )
    # #387: hand the model what Python already worked out — drivers, trends,
    # significant correlations, presence — so "what drove it?" gets the
    # platform's computed read instead of "I can't tell you".
    reads_block = _ask_reads_block(ctx.get("reads") or {})
    reads_section = f"\nCOMPUTED READS (precomputed by the platform's analysis pipeline):\n{reads_block}\n" if reads_block else ""
    return f"""You are the AI behind Matthew Walker's Life Platform — a personal health intelligence system tracking \
{_LIVE_SOURCE_COUNT} live data sources ({_PAUSED_SOURCE_COUNT} paused).

CURRENT DATA:
  Weight: {ctx.get('weight_lbs', '?')} lbs (started {ctx.get('start_weight', EXPERIMENT_BASELINE_WEIGHT_LBS)}, goal {ctx.get('goal_weight', 185)})
  HRV: {ctx.get('hrv_ms', '?')} ms
  RHR: {ctx.get('rhr_bpm', '?')} bpm
  Recovery: {ctx.get('recovery_pct', '?')}%
  Sleep: {ctx.get('sleep_hours', '?')} hours
  Character level: {ctx.get('character_level', '?')} (tier: {ctx.get('character_tier', '?')})
  T0 habit streak: {ctx.get('tier0_streak', '?')} days
  Pillars:
{pillars_str or '    Not available'}
{reads_section}
RULES:
- You answer READERS of Matthew's public experiment — the reader is NOT Matthew. Never tell the reader to check, sync, or refresh "your" device: the devices are Matthew's (Whoop, Withings, Eight Sleep). If a reading is missing, say the platform hasn't received it yet.
- Answer from the data above. If you don't have data, say so honestly.
- Be specific: "HRV is 54ms" not "HRV is moderate."
- N=1 data. Note this for comparative claims.
- NO ARITHMETIC: you narrate precomputed values — never sum, average, project, or derive a number yourself. Every number you cite must appear verbatim in the data above.
- "What drove X?" questions: answer from the COMPUTED READS (mode factors, momentum, improving/declining metrics, correlations) with correlative framing and a small-sample caveat. If no computed read covers the question, say the platform hasn't computed a driver read for that yet. NEVER ask the reader to supply or track Matthew's data — the platform already tracks it; readers don't have it.
- CORRELATIVE ONLY, NEVER CAUSAL: say "X tracks with Y" or "X coincided with Y," never "X causes/caused Y" or "X will improve Y." Patterns are leads, not proof.
- LABEL CONFIDENCE HONESTLY: flag thin evidence ("preliminary — only a few weeks of data," "small sample, low confidence") and never present a pattern as established. When the experiment was recently re-anchored, the data is early by design — say so.
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


# ── The board = the REAL coach roster (#373: one cast, one grounding path) ──
# The retired separate "board of directors" cast answered ungrounded and echoed
# real-expert-adjacent wire IDs. board_ask now convenes the SAME eight coaches
# the coaching pages display (config/coaches/*.json display names), each
# grounded on the canonical facts block + their own STANCE#latest.
COACH_ROSTER = {
    "sleep_coach": {"name": "Dr. Lisa Park", "title": "Sleep & Recovery", "lens": "sleep architecture, recovery, HRV, circadian rhythm"},
    "training_coach": {
        "name": "Dr. Sarah Chen",
        "title": "Training & Movement",
        "lens": "strength, cardio load, progressive overload, movement quality",
    },
    "nutrition_coach": {
        "name": "Dr. Marcus Webb",
        "title": "Evidence-Based Nutrition",
        "lens": "energy balance, protein, adherence, a sustainable deficit",
    },
    "mind_coach": {"name": "Dr. Nathan Reeves", "title": "Mind & Behaviour", "lens": "habits, stress, motivation, behavioural patterns"},
    "physical_coach": {
        "name": "Dr. Victor Reyes",
        "title": "Physical & Metabolic Health",
        "lens": "body composition, weight trajectory, metabolic adaptation",
    },
    "glucose_coach": {
        "name": "Dr. Amara Patel",
        "title": "Glucose & Metabolic Response",
        "lens": "glucose response, meal timing, metabolic flexibility",
    },
    "labs_coach": {"name": "Dr. James Okafor", "title": "Labs & Biomarkers", "lens": "bloodwork, biomarkers, long-run risk factors"},
    "explorer_coach": {
        "name": "Dr. Henning Brandt",
        "title": "Cross-Domain Patterns",
        "lens": "correlations across domains, N=1 methodology, statistical honesty",
    },
}
# Tolerant transition for cached OLD persona ids (the retired cast) — mapped to
# the nearest real coach, deduped downstream. Unknown ids (not old, not real) 400.
LEGACY_PERSONA_MAP = {
    "vasquez": "physical_coach",
    "okafor": "labs_coach",
    "patel": "glucose_coach",
    "norton": "nutrition_coach",
    "cole": "mind_coach",
    "driggs": "mind_coach",
    "clear": "mind_coach",
}


def _coach_voice_core(pid: str) -> str:
    """#531: the shared persona core — the SAME voice-spec fields the daily-brief
    self writes from (config/coaches/{pid}.json via persona_core), compacted.
    Deterministic per spec, so the system block stays byte-stable for the prompt
    cache. "" fail-soft: a missing spec keeps the roster-only block (pre-#531)."""
    try:
        import persona_core

        return persona_core.persona_block(pid, s3_client=_s3_client(), bucket=S3_BUCKET)
    except Exception as e:
        logger.warning(f"[board_ask] voice core unavailable for {pid} (fail-soft): {e}")
        return ""


def _coach_system(pid: str) -> str:
    """The persona system block — identity + voice core (#531) + WHERE-you-are
    context + the absolute grounding rules. Stable per coach so the ephemeral
    prompt cache keeps its 90% discount; the volatile facts ride in the user
    message instead. (#356: a shared situational preamble so personas hold
    character under meta-pressure and stop asking the reader for data the
    platform already collects.)"""
    c = COACH_ROSTER[pid]
    voice_core = _coach_voice_core(pid)
    return (
        f"You are {c['name']}, the {c['title']} coach — an AI coach persona on averagejoematt.com, "
        f"one of the eight-coach board that reads Matthew's real health data daily. Your lens: {c['lens']}. "
        # #531: one mind per coach — the board self writes from the same voice
        # spec as the daily-brief self. (Blank when the spec can't be loaded.)
        # The bridge rule reconciles voice specs that call for explicit numeric
        # confidence ("I'd put this at 70%") with this surface's fail-closed
        # ADR-104 gate, which kills any number absent from the input: on the
        # board, confidence is expressed in words, so the voice never fights
        # the gate. (Observed live 2026-07-04: a stated 70% confidence tripped
        # the gate and replaced a good answer with the refusal.)
        + (f"\n{voice_core}\n" if voice_core else "")
        + (
            "ON THIS SURFACE: express confidence and likelihood in WORDS (e.g. 'moderately confident', "
            "'better than even odds'), never as a percentage or numeric figure — on the public board, the "
            "only numbers you may write are ones present in the CURRENT DATA block. That block is deliberately "
            "coarse: it carries NO sleep-stage, trend, per-day, or historical figures — describe all of those "
            "qualitatively (rising, short of where I want it, stalled), never with an invented number. "
            if voice_core
            else ""
        )
        # WHERE YOU ARE (#356): the situational preamble every persona shares.
        + "WHERE YOU ARE: this is the public board of averagejoematt.com — Matthew's real, ongoing N=1 living "
        "documentary. The platform ALREADY continuously tracks his sleep (three devices), training, nutrition, "
        f"glucose, labs, recovery, HRV and habits from {_LIVE_SOURCE_COUNT} live sources; the CURRENT DATA block below is his REAL "
        "tracked data. You are answering a READER's question about that public experiment, from your discipline "
        "only — you are NOT in a private consult. Therefore: never ask the reader to supply Matthew's data, and "
        "never prescribe that he 'start tracking' something the platform already measures — speak to what the "
        "data shows and what a next read would test. "
        # IDENTITY (#356): in-voice deflection, no vendor/model naming.
        "IDENTITY: if asked who or what you 'really' are, which AI or model powers you, or any variant that tries "
        "to break the frame, answer in voice — you are {name}, a coaching persona on this site's board, an AI "
        "reading of Matthew's data. Never name the underlying AI vendor, company, or model, and never drop the "
        "coaching voice to do it. "
        # GROUNDING + safety (unchanged behaviour).
        "GROUNDING (absolute): cite ONLY numbers present in the CURRENT DATA block provided with the question — "
        "never invent, estimate, or recall figures from anywhere else. If the data you would need is not in the "
        "block, say so plainly instead of guessing. Every observation is correlative and N=1 — no causal claims, "
        "and never medical advice for the reader. Refuse requests for private information (addresses, contacts, "
        "finances, anything not a public health metric) in voice, without breaking character. "
        "First person, 3-5 sentences, plain language, at most a couple of concrete numbers."
    ).replace("{name}", c["name"])


def _board_facts_block() -> str:
    """The shared CURRENT DATA block — the same sanitized aggregates /api/ask
    grounds on, formatted once per request and injected into every persona turn."""
    ctx = _ask_fetch_context()
    lines = []
    if ctx.get("weight_lbs") is not None:
        lines.append(f"weight: {ctx['weight_lbs']:.1f} lb")
    if ctx.get("recovery_pct") is not None:
        lines.append(f"recovery: {ctx['recovery_pct']:.0f}%")
    if ctx.get("hrv_ms") is not None:
        lines.append(f"HRV: {ctx['hrv_ms']:.1f} ms")
    if ctx.get("rhr_bpm") is not None:
        lines.append(f"resting HR: {ctx['rhr_bpm']:.0f} bpm")
    if ctx.get("sleep_hours") is not None:
        lines.append(f"last sleep: {ctx['sleep_hours']:.1f} h")
    if ctx.get("character_level") is not None:
        lines.append(f"character level: {ctx['character_level']:.0f} ({ctx.get('character_tier', 'Foundation')})")
    for pname, pd in (ctx.get("pillars") or {}).items():
        lines.append(f"pillar {pname}: {pd.get('raw_score', 0):.0f}/100")
    if ctx.get("habit_completion_pct") is not None:
        lines.append(f"habit completion: {ctx['habit_completion_pct']:.0f}%")
    return "; ".join(lines) if lines else "no current data available"


def _coach_stance_bits(pid: str) -> str:
    """The coach's own current read (STANCE#latest, written weekly by the
    coach-opinion engine) — one headline + stage label. Empty pre-data."""
    try:
        item = table.get_item(Key={"pk": f"COACH#{pid}", "sk": "STANCE#latest"}).get("Item") or {}
        item = _decimal_to_float(item)
        bits = []
        if item.get("headline_read"):
            bits.append(str(item["headline_read"])[:300])
        stage = item.get("stage") or {}
        if isinstance(stage, dict) and stage.get("label"):
            bits.append(f"(stage: {stage['label']})")
        return " ".join(bits)
    except Exception:
        return ""


def _coach_memory_bits(pid: str) -> str:
    """#531: the coach's compressed memory (COMPRESSED#latest, maintained weekly
    by the history summarizer) — the same state the daily-brief self reasons
    from. Summary + top concerns, bounded. Empty pre-data / on any error."""
    try:
        item = table.get_item(Key={"pk": f"COACH#{pid}", "sk": "COMPRESSED#latest"}).get("Item") or {}
        item = _decimal_to_float(item)
        bits = []
        if item.get("summary"):
            bits.append(str(item["summary"])[:500])
        concerns = [str(x)[:120] for x in (item.get("key_concerns") or [])[:3]]
        if concerns:
            bits.append("Current concerns: " + "; ".join(concerns))
        return " ".join(bits)
    except Exception:
        return ""


def _coach_recent_interactions(pid: str, limit: int = 2) -> str:
    """#531: the coach's newest public-board answers (episodic memory) — so a
    coach can reference what it already told readers instead of contradicting
    itself. Empty pre-data / on any error."""
    try:
        resp = table.query(
            KeyConditionExpression=Key("pk").eq(f"COACH#{pid}") & Key("sk").begins_with("INTERACTION#"),
            ScanIndexForward=False,
            Limit=limit,
        )
        lines = []
        for it in resp.get("Items", []):
            q = str(it.get("question") or "")[:160]
            a = str(it.get("answer") or "")[:240]
            sk_parts = str(it.get("sk") or "").split("#")
            d = sk_parts[1] if len(sk_parts) > 1 else ""
            if q and a:
                lines.append(f"[{d}] A reader asked: {q} — you answered: {a}")
        return "\n".join(lines)
    except Exception:
        return ""


def _write_board_interaction(pid: str, question: str, answer: str, grounded: bool) -> None:
    """#531: episodic write-back — a public board answer enters the coach's OWN
    memory (PK=COACH#{pid}, SK=INTERACTION#{date}#{qhash}) so the weekly
    summarizer folds it into COMPRESSED#latest and future outputs can reference
    it. Content is already scrubbed (privacy_guard + blocked terms). The qhash
    is content-addressed, so a repeated question overwrites rather than piles
    up. Fail-soft: a write failure never affects the reader's response."""
    try:
        now = datetime.now(timezone.utc)
        qid = hashlib.sha256(question.encode()).hexdigest()[:8]
        table.put_item(
            Item={
                "pk": f"COACH#{pid}",
                "sk": f"INTERACTION#{now.strftime('%Y-%m-%d')}#{qid}",
                "interaction_type": "board_qa",
                "channel": "public_board",
                "question": question[:500],
                "answer": answer[:1200],
                "grounded": grounded,
                "created_at": now.isoformat(),
            }
        )
    except Exception as e:
        logger.warning(f"[board_ask] interaction write-back failed for {pid} (non-fatal): {e}")


# ── Lambda Handler ─────────────────────────────────────────


def lambda_handler(event: dict, context) -> dict:  # Phase 4.12 type hints
    """Routes /api/ask (POST) and /api/board_ask (POST) only."""
    # Phase 2.2: centralized request envelope validation (Body size cap +
    # injection pattern detection + param format checks). Returns 4xx on abuse.
    try:
        from request_validator import validate_envelope

        path = event.get("rawPath") or event.get("path", "/")
        method = (event.get("requestContext", {}).get("http", {}).get("method") or event.get("httpMethod", "POST")).upper()
        validate_envelope(event, path=path, method=method)
    except ImportError:
        pass
    except Exception as _ve:
        if _ve.__class__.__name__ == "ValidationError":
            return {
                "statusCode": getattr(_ve, "status", 400),
                "headers": CORS_HEADERS,
                "body": json.dumps({"error": getattr(_ve, "message", str(_ve))}),
            }
        raise
    if event.get("healthcheck"):
        return {"statusCode": 200, "body": "ok"}

    path = event.get("rawPath") or event.get("path", "/")
    method = (event.get("requestContext", {}).get("http", {}).get("method") or event.get("httpMethod", "GET")).upper()

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

    # ── POST /api/explain (#403) ───────────────────────────
    if path == "/api/explain":
        if method != "POST":
            return _error(405, "Use POST method")
        return _handle_explain(event)

    return _error(404, "Not found")


def _handle_ask(event: dict) -> dict:
    """POST /api/ask — AI Q&A with health data context."""
    _paused = _ai_paused_response()
    if _paused:
        return _paused
    source_ip = (
        event.get("requestContext", {}).get("http", {}).get("sourceIp")
        or event.get("requestContext", {}).get("identity", {}).get("sourceIp")
        or "unknown"
    )
    try:
        _body = json.loads(event.get("body") or "{}")
        question = (_body.get("question") or "").strip()[:500]
        question = re.sub(r"<[^>]+>", "", question)
        if len(question) < 5:
            return _error(400, "Question too short")

        # Follow-up memory (2026-06-13): up to 3 prior Q/A pairs from the same
        # browser session become real conversation turns, so "what about REM?"
        # works after a sleep question. Strictly validated and capped — history
        # is untrusted client input.
        history = []
        for turn in (_body.get("history") or [])[-3:]:
            if not isinstance(turn, dict):
                continue
            q = re.sub(r"<[^>]+>", "", str(turn.get("q", "")))[:500].strip()
            a = re.sub(r"<[^>]+>", "", str(turn.get("a", "")))[:1200].strip()
            # History is UNTRUSTED client input — there is no server session
            # store, so the replayed *assistant* turn `a` is fully attacker-
            # controlled and would otherwise become a real assistant message in
            # the prompt (a classic conversation-injection vector). Gate BOTH q
            # and a through the safety filter, and scrub blocked terms from the
            # replayed answer, so a crafted turn can't inject unsafe steering or
            # reintroduce a blocked vice term as a fake prior assistant message.
            if q and a and _ask_question_safe(q)[0] and _ask_question_safe(a)[0]:
                history.append((q, _scrub_blocked_terms(a)))

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

        req_body = json.dumps(
            {
                "model": AI_MODEL_HAIKU,
                "max_tokens": 600,
                "system": system_prompt,
                "messages": (
                    [m for q_, a_ in history for m in ({"role": "user", "content": q_}, {"role": "assistant", "content": a_})]
                    + [{"role": "user", "content": question}]
                ),
            }
        )

        # ADR-062 (2026-05-27): Bedrock invoke_model (was urllib → api.anthropic.com).
        from bedrock_client import invoke as _bedrock_invoke

        result = _bedrock_invoke(json.loads(req_body))

        # V2 follow-up: emit token metrics (was dark)
        _emit_token_metrics(result.get("usage", {}), endpoint="api_ask")

        answer = "".join(b["text"] for b in result.get("content", []) if b.get("type") == "text")

        # ADR-104 grounding gate (reader-facing → fail-closed): every number in
        # the answer must exist in what the model was given (system context,
        # the question, prior turns). One corrective regen; if numbers still
        # can't be grounded, say so honestly instead of serving them.
        try:
            import grounded_generation as _gg

            _allowed = _gg.allowed_numbers(system_prompt, question, [a_ for _, a_ in history])

            def _ask_findings(_t):
                return _gg.grounding_findings(_t, allowed=_allowed)

            _pre = _ask_findings(answer)
            if _pre:
                logger.warning(f"[site_api_ai] /api/ask ungrounded: {[f['detail'] for f in _pre][:4]}")

                def _ask_regen(_corr):
                    _r2 = _bedrock_invoke(
                        {
                            "model": AI_MODEL_HAIKU,
                            "max_tokens": 600,
                            "system": system_prompt,
                            "messages": (
                                [m for q_, a_ in history for m in ({"role": "user", "content": q_}, {"role": "assistant", "content": a_})]
                                + [
                                    {"role": "user", "content": question},
                                    {"role": "assistant", "content": answer},
                                    {"role": "user", "content": _corr},
                                ]
                            ),
                        }
                    )
                    _emit_token_metrics(_r2.get("usage", {}), endpoint="api_ask")
                    return "".join(b["text"] for b in _r2.get("content", []) if b.get("type") == "text")

                answer, _left, _ = _gg.regen_once(answer, _ask_findings, _ask_regen)
                if _left:
                    answer = (
                        "I couldn't ground part of that answer in the data I actually have, "
                        "so I'd rather not guess at numbers. Try asking about something the "
                        "current record covers — sleep, recovery, weight trend, training, or nutrition."
                    )
        except ImportError:
            pass  # helper not bundled — serve as before
        except Exception as _gg_e:
            logger.warning(f"[site_api_ai] grounding gate error (fail-open): {_gg_e}")

        return {
            "statusCode": 200,
            "headers": {**CORS_HEADERS, "Cache-Control": "no-store"},
            "body": json.dumps({"answer": _scrub_blocked_terms(answer), "remaining": remaining}),
        }
    except Exception as e:
        logger.error(f"[site_api_ai] /api/ask failed: {e}")
        return _error(500, "AI service error")


# ── #403: 'Explain this page' — server-grounded one-tap explainers ──────────
# The affordance sends ONLY a surface name; the server refetches the
# allowlisted read-only endpoint's JSON itself, so client-supplied numbers are
# never trusted (the injection hole is closed by construction). One small
# Haiku call per tap, sharing the ask endpoint's budget pause, DDB rate
# limiting, prompt caching, and the ADR-104 fail-closed number gate.

_SITE_BASE = os.environ.get("SITE_BASE_URL", "https://averagejoematt.com")

# surface name -> what the reader is looking at (drives the prompt framing).
# Fetching is per-surface in _fetch_surface_json; nothing outside this dict
# can ever be explained.
_EXPLAIN_SURFACES = {
    "observatory_week": "the cockpit's week view — six instruments (sleep, training, nutrition, glucose, physical, mind), "
    "each a 7-day sparkline with this week's primary number and its delta vs the week before",
    "what_changed": "the cockpit's month view — real trailing-30-day vs prior-30-day averages per metric, "
    "plus correlations that first passed FDR significance in the last 30 days; honest_null means a genuinely steady month",
    "sleep_correlations": "the sleep page's cross-source signal board — candidate correlations with n, weeks of overlap, "
    "and a confidence tag; under 2 weeks of overlap only a direction is shown, and thin pairs are flagged likely-noise",
}

_EXPLAIN_WEEK_DOMAINS = ("sleep", "training", "nutrition", "glucose", "physical", "mind")


def _fetch_public_json(path: str):
    """GET one of our own read-only public endpoints (server-side, stdlib)."""
    import urllib.request

    req = urllib.request.Request(f"{_SITE_BASE}{path}", headers={"accept": "application/json"})
    with urllib.request.urlopen(req, timeout=6) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    # Unwrap the standard {"data": ...} envelope when present.
    if isinstance(data, dict) and isinstance(data.get("data"), (dict, list)) and len(data) <= 3:
        return data["data"]
    return data


def _fetch_surface_json(surface: str):
    """Refetch the surface's real payload — the ONLY numbers the model sees."""
    if surface == "observatory_week":
        out = {}
        for d in _EXPLAIN_WEEK_DOMAINS:
            try:
                j = _fetch_public_json(f"/api/observatory_week?domain={d}") or {}
                p = ((j.get("summary") or {}).get("primary") or {}) if isinstance(j, dict) else {}
                if p:
                    out[d] = {k: p.get(k) for k in ("value", "unit", "delta", "trend", "delta_label", "sparkline") if p.get(k) is not None}
            except Exception as e:
                logger.warning(f"[explain] {d} week read skipped: {e}")
        return out
    if surface == "what_changed":
        return _fetch_public_json("/api/what_changed")
    if surface == "sleep_correlations":
        return _fetch_public_json("/api/sleep_correlations")
    return None


def _shrink_for_prompt(data, cap: int = 9000) -> str:
    """Deterministically bound the JSON handed to the model: long lists are
    trimmed (first 12 items) rather than the text being cut mid-token."""

    def _trim(v):
        if isinstance(v, list):
            return [_trim(x) for x in v[:12]]
        if isinstance(v, dict):
            return {k: _trim(x) for k, x in v.items()}
        return v

    txt = json.dumps(_trim(data), default=str)
    return txt[:cap]


_EXPLAIN_SYSTEM = (
    "You are the plain-English tour guide for averagejoematt.com — Matthew's public, single-subject (N=1) "
    "health experiment. A reader tapped 'explain this page' on a data-dense surface. You receive the page's "
    "REAL, server-fetched JSON and a description of what the surface shows.\n\n"
    "RULES (absolute):\n"
    "- 3-4 short sentences of plain English. No headers, no bullets, no markdown.\n"
    "- Narrate ONLY values present in the JSON — never compute, average, or extrapolate a number yourself.\n"
    "- Correlative framing only: 'tracks with', 'coincided with' — never causal claims, never health advice.\n"
    "- If the data is thin or empty, say so honestly and plainly (the experiment-day context tells you why a "
    "young record is short) — never pad with invented data.\n"
    "- The reader is NOT Matthew; the data and devices are Matthew's.\n"
    "- N=1: flag thin evidence as preliminary where it matters."
)


def _handle_explain(event: dict) -> dict:
    """POST /api/explain — {surface} in, 3-4 grounded sentences out."""
    _paused = _ai_paused_response()
    if _paused:
        return _paused
    source_ip = (
        event.get("requestContext", {}).get("http", {}).get("sourceIp")
        or event.get("requestContext", {}).get("identity", {}).get("sourceIp")
        or "unknown"
    )
    try:
        body = json.loads(event.get("body") or "{}")
    except Exception:
        return _error(400, "Invalid JSON")
    surface = str(body.get("surface") or "").strip()
    if surface not in _EXPLAIN_SURFACES:
        return _error(400, "Unknown surface")

    ip_hash = hashlib.sha256(source_ip.encode()).hexdigest()[:16]
    sub_token = (event.get("headers") or {}).get("x-subscriber-token", "")
    is_subscriber = bool(sub_token) and _validate_subscriber_token(sub_token)
    allowed, remaining = _ask_rate_check(ip_hash, limit=20 if is_subscriber else 5)
    if not allowed:
        _emit_rate_limit_metric("explain")
        return {
            "statusCode": 429,
            "headers": {**CORS_HEADERS, "Retry-After": "3600"},
            "body": json.dumps({"error": "Rate limit exceeded.", "remaining": 0}),
        }

    try:
        payload = _fetch_surface_json(surface)
    except Exception as e:
        logger.warning(f"[explain] surface fetch failed for {surface}: {e}")
        payload = None
    if payload is None:
        return _error(503, "That surface's data isn't reachable right now.")

    payload_txt = _shrink_for_prompt(payload)
    try:
        from constants import EXPERIMENT_START_DATE

        _day_n = (datetime.now(timezone.utc).date() - datetime.strptime(EXPERIMENT_START_DATE, "%Y-%m-%d").date()).days + 1
        day_ctx = f"Experiment day {_day_n} (restarted {EXPERIMENT_START_DATE}) — a young record is short by design."
    except Exception:
        day_ctx = ""

    user_msg = (
        f"SURFACE: {_EXPLAIN_SURFACES[surface]}\n"
        + (f"CONTEXT: {day_ctx}\n" if day_ctx else "")
        + f"PAGE JSON (authoritative — cite only these numbers):\n{payload_txt}\n\n"
        "Explain what this page is showing right now, in 3-4 plain sentences."
    )
    try:
        from bedrock_client import invoke as _bedrock_invoke

        result = _bedrock_invoke(
            {
                "model": AI_MODEL_HAIKU,
                "max_tokens": 300,
                "system": [{"type": "text", "text": _EXPLAIN_SYSTEM, "cache_control": {"type": "ephemeral"}}],
                "messages": [{"role": "user", "content": user_msg}],
            }
        )
        _emit_token_metrics(result.get("usage", {}), endpoint="api_explain")
        explanation = "".join(b["text"] for b in result.get("content", []) if b.get("type") == "text").strip()

        # ADR-104 fail-closed gate: every number must exist in the fetched JSON.
        try:
            import grounded_generation as _gg

            _allowed = _gg.allowed_numbers(payload_txt, day_ctx)
            if _gg.grounding_findings(explanation, allowed=_allowed):
                logger.warning(f"[explain] ungrounded numbers for {surface} — refusing")
                explanation = (
                    "I'd rather not narrate numbers I can't ground in this page's data. "
                    "The chart itself is the honest read — try again in a moment."
                )
        except ImportError:
            pass

        return {
            "statusCode": 200,
            "headers": {**CORS_HEADERS, "Cache-Control": "no-store"},
            "body": json.dumps({"explanation": _scrub_blocked_terms(explanation), "surface": surface, "remaining": remaining}),
        }
    except Exception as e:
        logger.error(f"[site_api_ai] /api/explain failed: {e}")
        return _error(500, "AI service error")


def _handle_board_ask(event: dict) -> dict:
    """POST /api/board_ask — 6-persona board panel answers."""
    _paused = _ai_paused_response()
    if _paused:
        return _paused
    source_ip = (
        event.get("requestContext", {}).get("http", {}).get("sourceIp")
        or event.get("requestContext", {}).get("identity", {}).get("sourceIp")
        or "unknown"
    )
    ip_hash = hashlib.sha256(source_ip.encode()).hexdigest()[:16]
    # Phase 2.1: DDB-backed rate limit (was in-memory dict — didn't survive
    # warm-container distribution). Each board_ask costs ~6 Haiku calls,
    # so global enforcement is critical to bound the worst-case bill.
    if _RATE_LIMITER_READY:
        _board_allowed, _board_remaining, _board_retry = _ddb_rate_check(
            table,
            endpoint="board_ask",
            ip_hash=ip_hash,
            limit=BOARD_RATE_LIMIT,
            window_seconds=3600,
            fail_open=False,  # each board_ask costs ~6 Haiku calls — never unmetered
        )
        if not _board_allowed:
            _emit_rate_limit_metric("board_ask")
            return {
                "statusCode": 429,
                "headers": {**CORS_HEADERS, "Retry-After": str(_board_retry or 3600)},
                "body": json.dumps({"error": "Rate limit reached. Try again in an hour."}),
            }
    else:
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

    # #373: convene the REAL roster. Legacy cached ids map to their nearest
    # coach; a genuinely unknown id is a 400 BEFORE any paid model call.
    requested = body.get("personas") or ["training_coach", "nutrition_coach", "sleep_coach"]
    if not isinstance(requested, list) or len(requested) > 12:
        return {"statusCode": 400, "headers": CORS_HEADERS, "body": json.dumps({"error": "personas must be a list of coach ids"})}
    personas = []
    for pid in requested:
        pid = LEGACY_PERSONA_MAP.get(str(pid), str(pid))
        if pid not in COACH_ROSTER:
            return {
                "statusCode": 400,
                "headers": CORS_HEADERS,
                "body": json.dumps({"error": f"Unknown persona id. Valid: {', '.join(COACH_ROSTER)}"}),
            }
        if pid not in personas:
            personas.append(pid)
    personas = personas[:8]

    api_key = _get_anthropic_key()
    if not api_key:
        return {"statusCode": 503, "headers": CORS_HEADERS, "body": json.dumps({"error": "AI service unavailable"})}

    # P5.2 (2026-05-17): cache the per-persona system prompt as ephemeral so
    # repeat questions to the same persona within 5 min hit the prompt cache
    # (90% discount on the system block). Each persona stays a distinct cache
    # entry — they don't share preamble (voice/focus differ too much).
    # One facts fetch per request; per-coach stance rides in the user turn so
    # the persona system block stays byte-stable for the prompt cache.
    facts = _board_facts_block()
    responses = {}
    for pid in personas:
        p = COACH_ROSTER[pid]
        try:
            # #531: one mind per coach — the board self loads the same memory the
            # daily-brief self reasons from (stance + compressed state), plus its
            # own recent board answers (episodic). All volatile → user turn, so
            # the persona system block stays byte-stable for the prompt cache.
            stance = _coach_stance_bits(pid)
            memory = _coach_memory_bits(pid)
            episodic = _coach_recent_interactions(pid)
            user_msg = (
                f"CURRENT DATA (authoritative — cite only these numbers): {facts}\n"
                + (f"YOUR CURRENT READ (your own published stance): {stance}\n" if stance else "")
                + (f"YOUR MEMORY (the compressed history your weekly summarizer maintains): {memory}\n" if memory else "")
                + (
                    f"YOUR RECENT BOARD ANSWERS (reference them when relevant — never silently contradict them):\n{episodic}\n"
                    if episodic
                    else ""
                )
                + f"READER QUESTION: {question}"
            )
            _sys_txt = _coach_system(pid)
            req_body = json.dumps(
                {
                    "model": AI_MODEL_HAIKU,
                    "max_tokens": 300,
                    "system": [
                        {
                            "type": "text",
                            "text": _sys_txt,
                            "cache_control": {"type": "ephemeral"},
                        }
                    ],
                    "messages": [{"role": "user", "content": user_msg}],
                }
            )
            # ADR-062 (2026-05-27): Bedrock invoke_model (was urllib → api.anthropic.com).
            # No retry wrapper — board_ask makes 6 calls/request; a transient
            # Bedrock error on call N degrades cleanly to "[name] temporarily
            # unavailable" for that persona. bedrock_client is bundled in
            # /var/task via Code.from_asset, so it imports even though site-api-ai
            # runs without the shared layer.
            from bedrock_client import invoke as _bedrock_invoke

            result = _bedrock_invoke(json.loads(req_body))
            # V2 follow-up: emit per-persona token metrics (was dark)
            _emit_token_metrics(result.get("usage", {}), endpoint="api_board_ask")
            _txt = _scrub_blocked_terms("".join(b["text"] for b in result.get("content", []) if b.get("type") == "text"))

            # ADR-104 grounding gate (reader-facing → fail-closed, no regen —
            # board_ask already costs ~6 calls/request): any number the coach
            # states must exist in its system context, the facts, its stance,
            # or the question. Ungrounded → an honest in-voice refusal, never
            # a fabricated figure served to a reader.
            _grounded = True
            try:
                import grounded_generation as _gg

                _allowed = _gg.allowed_numbers(_sys_txt, user_msg)
                _gf = _gg.grounding_findings(_txt, allowed=_allowed)
                if _gf:
                    logger.warning(f"[board_ask] {pid} ungrounded: {[f['detail'] for f in _gf][:3]}")
                    _grounded = False
                    _refusal = (
                        "I'd want to answer that with numbers I can actually stand behind, and I can't "
                        "ground them in today's record — ask me about something the current data covers."
                    )
                    # #531 follow-up (live drill 2026-07-04): ONE corrective
                    # rewrite before falling back to the refusal — the same
                    # discipline the daily-brief self gets (regen-once). The
                    # richer voice core raised fabrication pressure enough
                    # that a fixable stray figure was turning good answers
                    # into refusals. Bounded: at most one extra Haiku call per
                    # flagged persona, inside the 5/hr/IP rate limit.
                    try:
                        _corr_body = json.loads(req_body)
                        _corr_body["messages"] = [{"role": "user", "content": user_msg + "\n\n" + _gg.correction_prompt(_gf)}]
                        _retry = _bedrock_invoke(_corr_body)
                        _emit_token_metrics(_retry.get("usage", {}), endpoint="api_board_ask")
                        _txt2 = _scrub_blocked_terms("".join(b["text"] for b in _retry.get("content", []) if b.get("type") == "text"))
                        if _txt2.strip() and not _gg.grounding_findings(_txt2, allowed=_allowed):
                            _txt = _txt2
                            _grounded = True
                            logger.info(f"[board_ask] {pid} corrected once — grounded on retry")
                        else:
                            _txt = _refusal
                    except Exception as _rt_e:
                        logger.warning(f"[board_ask] {pid} correction retry failed: {_rt_e}")
                        _txt = _refusal
            except ImportError:
                pass  # helper not bundled — serve as before
            except Exception as _gg_e:
                logger.warning(f"[board_ask] {pid} grounding gate error (fail-open): {_gg_e}")

            # #531: the answer enters the coach's own memory (fail-soft).
            _write_board_interaction(pid, question, _txt, grounded=_grounded)

            responses[pid] = _txt
        except Exception as e:
            logger.error(f"[board_ask] {pid} failed: {e}")
            responses[pid] = f"[{p['name']} is temporarily unavailable]"

    return {
        "statusCode": 200,
        "headers": {**CORS_HEADERS, "Cache-Control": "no-store"},
        "body": json.dumps({"responses": responses}),
    }
