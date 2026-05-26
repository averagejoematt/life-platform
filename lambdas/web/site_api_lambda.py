"""
site_api_lambda.py — Real-time public API for averagejoematt.com

PURPOSE:
    Serves live health/journey/character data to the website.
    This is a SEPARATE, READ-ONLY Lambda from the MCP server.
    Never expose the MCP endpoint publicly — this Lambda is the
    only thing the website talks to.

ARCHITECTURE:
    Browser → CloudFront (TTL cache) → API Gateway → this Lambda → DynamoDB

    CloudFront TTL tiers (set on each route):
      /api/vitals      → 300s  (5 min) — weight, HRV, recovery
      /api/journey     → 3600s (1 hr)  — weight trajectory, goal date
      /api/character   → 900s  (15 min) — pillar scores, level
      /api/status      → 60s   (1 min) — system health check

DEPLOYMENT:
    1. Lambda: life-platform-site-api
    2. Reserved concurrency: 20 (hard cap — returns 429 if exceeded)
    3. Function URL or API Gateway HTTP route
    4. CloudFront distribution with /api/* → Lambda origin
    5. Add to CDK: operational_stack.py

IAM ROLE:
    Primary (read):  dynamodb:GetItem/Query, s3:GetObject
    Limited writes: vote/follow/checkin/suggestion records
    AI endpoints:   handled by life-platform-site-api-ai (ADR-036)
    NO access to MCP server.

P1.1 Phase B (2026-05-26):
    Shared helpers, CORS, AWS clients, caches, request-id state are now in
    lambdas/web/site_api_common.py and imported here. Site-api-only logic
    (endpoint handlers + routing) stays in this file.

v1.0.0 — 2026-03-16
"""
# stdlib
import hashlib  # noqa: F401 — used by handlers
import json
import os
import re
import time
import urllib.request  # noqa: F401 — used by AI handlers (kept for backward-compat)
import base64 as _b64  # noqa: F401 — used by subscriber-token helpers
import hmac as _hmac  # noqa: F401 — used by subscriber-token helpers
from datetime import datetime, timezone, timedelta
from decimal import Decimal  # noqa: F401 — kept for backward-compat with handlers

# third-party
import boto3  # noqa: F401 — kept for handlers that create clients
from boto3.dynamodb.conditions import Key

# shared layer
from phase_filter import with_phase_filter  # noqa: F401 — used by handlers below

# P1.1 Phase B (2026-05-26): shared helpers extracted to sibling module.
# Re-import as module-level names so the rest of this file (and the
# ROUTES dict) reference them unchanged.
from web.site_api_common import (
    logger,
    # config
    TABLE_NAME, USER_ID, USER_PREFIX, PT, DDB_REGION, S3_REGION,
    EXPERIMENT_START, EXPERIMENT_BASELINE_WEIGHT_LBS, EXPERIMENT_QUERY_START,
    # AWS
    dynamodb, table,
    # CORS
    CORS_ORIGIN, SITE_API_ORIGIN_SECRET, CORS_HEADERS,
    # caches
    STATUS_CACHE_TTL, PLATFORM_STATS,
    # helpers
    _cached_secret,
    _decimal_to_float,
    _experiment_date,
    _query_source,
    _latest_item,
    _get_profile,
    _load_supp_metadata,
    _load_content_filter,
    _scrub_blocked_terms,
    _is_blocked_vice,
    _request_id_headers,
    _ok,
    _error,
    # request-id state (set by lambda_handler; read by _ok/_error)
    set_request_id, get_request_id,
)

# P1.1 Phase B step 2 (2026-05-26): observatory handlers extracted to sibling module.
from web.site_api_observatory import (
    handle_nutrition_overview,
    handle_training_overview,
    handle_weekly_physical_summary,
    handle_protein_sources,
    handle_physical_overview,
    handle_journal_analysis,
    handle_mind_overview,
    handle_frequent_meals,
    handle_meal_glucose,
    handle_strength_benchmarks,
    handle_food_delivery_overview,
    handle_strength_deep_dive,
    handle_benchmark_trends,
    handle_meal_responses,
)

# P1.1 Phase B step 3 (2026-05-26): status + pulse handlers extracted.
from web.site_api_intelligence import (
    handle_status,
    handle_status_summary,
    handle_pulse,
    handle_pulse_history,
)

# P1.1 Phase B step 4 (2026-05-26): social cluster extracted to sibling module.
from web.site_api_social import (
    _handle_verify_subscriber,
    handle_subscriber_count,
    _handle_nudge,
    _handle_submit_finding,
    handle_experiment_library,
    _handle_experiment_vote,
    _handle_experiment_follow,
    _handle_experiment_detail,
    _handle_experiment_suggest,
    handle_challenge_catalog,
    handle_challenges,
    _handle_challenge_vote,
    _handle_challenge_follow,
    _handle_challenge_checkin,
    handle_current_challenge,
)

# P1.1 Phase B step 5 (2026-05-26): vitals cluster extracted.
from web.site_api_vitals import (
    handle_vitals,
    handle_journey,
    handle_character,
    handle_weight_progress,
    handle_character_stats,
    handle_journey_timeline,
    handle_journey_waveform,
    handle_achievements,
    handle_snapshot,
    handle_timeline,
)

# P1.1 Phase B step 6 (2026-05-26): data cluster extracted.
from web.site_api_data import (
    handle_glucose,
    handle_sleep_detail,
    handle_habits,
    handle_habit_streaks,
    handle_habit_registry,
    handle_correlations,
    handle_genome_risks,
    handle_observatory_week,
    handle_changes_since,
    handle_supplements,
    handle_vice_streaks,
    handle_experiments,
    handle_ledger,
    handle_discoveries,
    handle_labs,
    handle_protocols,
    handle_tools_baseline,
    handle_platform_stats,
    handle_domains,
)


# ── Endpoint handlers ───────────────────────────────────────

# ── BS-11: Timeline data ────────────────────────────────────────

# ── Sprint 9: Supplements + Habits public endpoints ─────────────

# ── WEB-CE: Correlation data ────────────────────────────────────

# ── BS-BM2: Genome risk data ────────────────────────────────────

# ── WR-24: Subscriber verification ──────────────────────────────────────────

import hmac as _hmac
import base64 as _b64


# ── S2-T2-2: Board Ask ────────────────────────────────────────────────────────

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

BOARD_RATE_LIMIT = 5  # per IP per hour
# ── Ask the Platform (AI Q&A) ─────────────────────────────────────


# R17-04: Separate Anthropic key for site-api — injected via CDK env var
AI_SECRET_NAME = os.environ.get("AI_SECRET_NAME",  "life-platform/site-api-ai-key")


# ── ARCH-03: Achievements endpoint ──────────────────────────

# ── ARCH-02: Snapshot endpoint ──────────────────────────────

# ── ACCT-2: Nudge handler ───────────────────────────────────

NUDGE_CATEGORIES = {"back_on_it", "watching", "take_your_time", "you_got_this"}
NUDGE_LABELS = {
    "back_on_it":    "Get back on it 🔥",
    "watching":      "We're watching 👀",
    "take_your_time": "Take your time ⏰",
    "you_got_this":  "You've got this 💪",
}


# ── NEW-1: Submit Finding ────────────────────────────────────

FINDING_RATE_LIMIT = 3  # per IP per hour


# ── EL-2: Experiment Library endpoint ───────────────────────

# ── EL-3/4: Experiment Vote POST handler ────────────────────

# ── EL-F1: Per-experiment follow (email interest) ─────────

# ── EL-F2: Single experiment detail endpoint ────────────────

# ── Router ──────────────────────────────────────────────────

# ── S3 config caches for data-driven pages ─────────────────

def _load_s3_json(key, cache_name):
    """Load a JSON file from S3. Returns parsed dict. Cached per Lambda container."""
    try:
        S3_BUCKET = os.environ.get("S3_BUCKET", "matthew-life-platform")
        s3 = boto3.client("s3", region_name=S3_REGION)
        resp = s3.get_object(Bucket=S3_BUCKET, Key=key)
        data = json.loads(resp["Body"].read())
        logger.info(f"[{cache_name}] Loaded from S3: {key}")
        return data
    except Exception as e:
        logger.warning(f"[{cache_name}] Failed to load {key}: {e}")
        return {}

# ── PULSE-A4: Pulse endpoint ───────────────────────────────────────────────

# ── Observatory API endpoints ────────────────────────────────────────────────

def handle_ai_analysis() -> dict:
    """
    GET /api/ai_analysis?expert=mind|nutrition|training|physical
    Returns cached AI expert analysis from DynamoDB.
    Cache: 300s.
    """
    # Note: query params handled in lambda_handler before ROUTES dispatch
    # This function is not directly called via ROUTES; handled specially
    pass


# ── BL-02: Bloodwork/Labs endpoint ─────────────────────────────
# ── Frequent Meals endpoint ───────────────────────────────────
# ── Meal Glucose Response endpoint ─────────────────────────────
# ── Strength Benchmarks endpoint ──────────────────────────────
# ── Phase 1: Changes-Since endpoint ─────────────────────────────
# ── Phase 1: Observatory Week endpoint ─────────────────────────
# ── Benchmark trends endpoint ─────────────────────────────────
# ── Meal responses endpoint ───────────────────────────────────
# ── Experiment suggestion POST handler ────────────────────────
ROUTES = {
    "/api/vitals":          handle_vitals,
    "/api/journey":         handle_journey,
    "/api/character":       handle_character,
    "/api/status":          handle_status,
    "/api/status/summary":  handle_status_summary,
    # BS-07: new public endpoints
    "/api/weight_progress": handle_weight_progress,
    "/api/character_stats": handle_character_stats,
    "/api/habit_streaks":   handle_habit_streaks,
    "/api/experiments":        handle_experiments,
    "/api/current_challenge":  handle_current_challenge,
    # Sprint 4: BS-11, WEB-CE, BS-BM2
    "/api/timeline":           handle_timeline,
    "/api/correlations":       handle_correlations,
    "/api/genome_risks":       handle_genome_risks,
    # Sprint 9: new public endpoints
    "/api/supplements":        handle_supplements,
    "/api/habits":             handle_habits,
    "/api/vice_streaks":       handle_vice_streaks,
    "/api/journey_timeline":   handle_journey_timeline,
    "/api/journey_waveform":   handle_journey_waveform,
    # Sprint 11: glucose + sleep intelligence pages
    "/api/glucose":            handle_glucose,
    "/api/sleep_detail":       handle_sleep_detail,
    # ARCH-03: Achievement badges
    "/api/achievements":       handle_achievements,
    # ARCH-02: Combined snapshot — single-call summary for pages that need vitals + journey + character
    "/api/snapshot":           handle_snapshot,
    # WR-24 + S2-T2-2: handled specially in lambda_handler (POST routes)
    "/api/verify_subscriber":  None,
    "/api/board_ask":          None,
    "/api/submit_finding":     None,  # NEW-1: POST handler in lambda_handler
    # EL-2: Experiment library (GET) + EL-3: Experiment vote (POST)
    "/api/experiment_library":  handle_experiment_library,
    "/api/experiment_vote":     None,  # POST handler in lambda_handler
    "/api/experiment_follow":   None,  # EL-F1: POST handler in lambda_handler
    "/api/experiment_detail":   None,  # EL-F2: GET with query params
    # DATA-DRIVEN: S3 config + DynamoDB source-of-truth endpoints
    "/api/protocols":          handle_protocols,
    "/api/challenges":         handle_challenges,
    "/api/challenge_catalog":  handle_challenge_catalog,
    "/api/challenge_vote":     None,  # POST handler in lambda_handler
    "/api/challenge_follow":   None,  # POST handler in lambda_handler
    "/api/challenge_checkin":  None,  # POST handler in lambda_handler
    "/api/domains":            handle_domains,
    "/api/habit_registry":     handle_habit_registry,
    # PULSE-A4: Daily pulse endpoint
    "/api/pulse":              handle_pulse,
    "/api/pulse_history":      handle_pulse_history,
    # Subscriber count social proof (read-only) — must NOT match /api/subscribe* CloudFront pattern
    "/api/sub_count":          handle_subscriber_count,
    # Observatory pages
    "/api/nutrition_overview":  handle_nutrition_overview,
    "/api/training_overview":   handle_training_overview,
    "/api/mind_overview":       handle_mind_overview,
    "/api/physical_overview":   handle_physical_overview,
    "/api/journal_analysis":    handle_journal_analysis,
    "/api/ai_analysis":         None,  # GET with ?expert= query param, handled in lambda_handler
    "/api/coach_analysis":      None,  # GET with ?domain= query param, handled in lambda_handler (Coach Intelligence)
    "/api/weekly_priority":     None,  # GET — integrator synthesis, handled in lambda_handler
    # BL-03: The Ledger / Snake Fund
    "/api/ledger":              handle_ledger,
    # BL-04: Field Notes
    "/api/field_notes":         None,  # GET with optional ?week= query param, handled in lambda_handler
    # BL-02: Bloodwork/Labs
    "/api/labs":                handle_labs,
    "/api/frequent_meals":      handle_frequent_meals,
    "/api/protein_sources":     handle_protein_sources,
    "/api/weekly_physical_summary": handle_weekly_physical_summary,
    "/api/strength_deep_dive":      handle_strength_deep_dive,
    "/api/food_delivery_overview":  handle_food_delivery_overview,
    "/api/meal_glucose":        handle_meal_glucose,
    "/api/strength_benchmarks": handle_strength_benchmarks,
    # Benchmark trends + meal responses (stub endpoints)
    "/api/benchmark_trends":    handle_benchmark_trends,
    "/api/meal_responses":      handle_meal_responses,
    # Tools page: baseline vs current comparison
    "/api/tools_baseline":      handle_tools_baseline,
    # Platform stats: single source of truth for all site pages
    "/api/platform_stats":      handle_platform_stats,
    # Discoveries page: active hypotheses + inner life + AI findings
    "/api/discoveries":         handle_discoveries,
    # Experiment suggestion (POST)
    "/api/experiment_suggest":  None,  # POST handler in lambda_handler
    # Phase 1: Reader engagement
    "/api/changes-since":       None,  # GET with ?ts= query param
    "/api/observatory_week":    None,  # GET with ?domain= query param
    # Coaching Dashboard
    "/api/coaching-dashboard":  None,  # GET — assembled coaching dashboard data
    # Prediction Ledger + Coach Timeline
    "/api/predictions":         None,  # GET with ?status=&coach_id=&limit= query params
    "/api/coach_timeline":      None,  # GET with ?coach_id= query param
}


_COLD_START = True


# ═══════════════════════════════════════════════════════════════════════════
# Phase 4.5 SCOPED (2026-05-16): router dispatch table
# ═══════════════════════════════════════════════════════════════════════════
# Replaces 14 sequential `if path == "..."` / method-check / delegate branches
# in lambda_handler with a single dict lookup. Each entry is:
#   path → (allowed_methods, handler_fn)
# where allowed_methods is a set (or None for "any method").
#
# Only "simple delegate" routes are captured here. Complex routes (those that
# inline query-param logic, multi-step DDB queries, or branch on event shape)
# stay inline in lambda_handler. Full router-with-handler-extraction is the
# multi-week P4.5 work; this is the scoped subset that pays for itself today.

_SIMPLE_ROUTES = {
    "/api/verify_subscriber": ({"GET", "OPTIONS"}, _handle_verify_subscriber),
    "/api/nudge":             ({"POST"},           _handle_nudge),
    "/api/submit_finding":    ({"POST"},           _handle_submit_finding),
    "/api/experiment_vote":   ({"POST"},           _handle_experiment_vote),
    "/api/experiment_follow": ({"POST"},           _handle_experiment_follow),
    "/api/experiment_suggest": ({"POST"},           _handle_experiment_suggest),
    "/api/challenge_checkin": ({"POST"},           _handle_challenge_checkin),
    "/api/challenge_vote":    ({"POST"},           _handle_challenge_vote),
    "/api/challenge_follow":  ({"POST"},           _handle_challenge_follow),
    "/api/experiment_detail": (None,               _handle_experiment_detail),
}


def lambda_handler(event, context):
    """
    Main Lambda handler. Supports both API Gateway HTTP API and Function URL events.
    """
    import time as _time
    import uuid as _uuid
    _req_start = _time.time()

    path = event.get("rawPath") or event.get("path", "/")
    method = (event.get("requestContext", {}).get("http", {}).get("method") or
              event.get("httpMethod", "GET")).upper()

    # P3.4: assign a per-request correlation ID. Honor an inbound x-request-id
    # header if the client (CloudFront / a debugging operator) set one — this
    # lets the same id flow end-to-end. Otherwise generate a fresh uuid4.
    inbound_headers = event.get("headers") or {}
    incoming_rid = (inbound_headers.get("x-request-id") or inbound_headers.get("X-Request-Id"))
    set_request_id(incoming_rid if incoming_rid else _uuid.uuid4().hex[:16])

    # Phase 2.2 (2026-05-16): centralized request envelope validation.
    # Catches oversized bodies, injection patterns, malformed user_id/date/source
    # before any handler runs. Returns 4xx for obvious abuse; legit traffic unaffected.
    try:
        from request_validator import validate_envelope, ValidationError
        validate_envelope(event, path=path, method=method)
    except ImportError:
        pass  # Validator not yet deployed; fall through to legacy behavior
    except Exception as _ve:
        # Imported as ValidationError above when import succeeds
        if _ve.__class__.__name__ == "ValidationError":
            return {
                "statusCode": getattr(_ve, "status", 400),
                "headers": CORS_HEADERS,
                "body": json.dumps({"error": getattr(_ve, "message", str(_ve))}),
            }
        raise

    def _emit_route_log(status_code):
        """Emit structured JSON route metric to CloudWatch Logs.

        Uses CloudWatch EMF (Embedded Metric Format) so per-route latency is
        auto-extracted as a real CloudWatch metric (no PutMetricData cost).
        Dimensions: Route + Method. The Logs Insights query can pivot on either
        via the JSON object — same line, two consumers.
        """
        global _COLD_START
        try:
            duration_ms = round((_time.time() - _req_start) * 1000, 1)
            emf = {
                # _aws block → CloudWatch automatically ingests the named
                # fields as metrics. Cheap (≤ 5 dimension sets, no API call).
                "_aws": {
                    "Timestamp": int(_time.time() * 1000),
                    "CloudWatchMetrics": [{
                        "Namespace": "LifePlatform/SiteAPI",
                        "Dimensions": [["Route", "Method"]],
                        "Metrics": [
                            {"Name": "DurationMs", "Unit": "Milliseconds"},
                            {"Name": "ColdStart", "Unit": "Count"},
                        ],
                    }],
                },
                "_type":      "route_metric",
                "Route":      path,
                "Method":     method,
                "status":     status_code,
                "DurationMs": duration_ms,
                "ColdStart":  1 if _COLD_START else 0,
                "request_id": get_request_id(),
                "duration_ms": duration_ms,  # back-compat field name
                "cold_start":  _COLD_START,
            }
            print(json.dumps(emf))
        except Exception:
            pass
        _COLD_START = False

    # CORS preflight
    if method == "OPTIONS":
        return {"statusCode": 200, "headers": CORS_HEADERS, "body": ""}

    # /api/healthz — lightweight health check (no auth, no PII)
    if path == "/api/healthz" and method == "GET":
        try:
            ddb_start = _time.time()
            table.get_item(Key={"pk": "USER#matthew#SOURCE#whoop", "sk": "DATE#2026-01-01"})
            ddb_ms = round((_time.time() - ddb_start) * 1000)
            ddb_ok = True
        except Exception:
            ddb_ms = -1
            ddb_ok = False
        try:
            s3_client = boto3.client("s3", region_name=S3_REGION)
            stats_obj = s3_client.get_object(Bucket=os.environ.get("S3_BUCKET", "matthew-life-platform"), Key="generated/public_stats.json")
            refreshed = json.loads(stats_obj["Body"].read()).get("_meta", {}).get("refreshed_at", "unknown")
        except Exception:
            refreshed = "unavailable"
        total_ms = round((_time.time() - _req_start) * 1000)
        health = {
            "status": "ok" if ddb_ok else "degraded",
            "version": "v4.5.1",
            "checks": {
                "dynamodb": {"status": "ok" if ddb_ok else "error", "latency_ms": ddb_ms},
                "last_daily_refresh": refreshed,
                "lambda_warm": not _COLD_START,
            },
            "response_ms": total_ms,
        }
        _emit_route_log(200)
        return {"statusCode": 200, "headers": CORS_HEADERS, "body": json.dumps(health)}

    # SEC-04: Reject requests that didn't come through CloudFront (when secret is configured).
    if SITE_API_ORIGIN_SECRET:
        req_headers = event.get("headers") or {}
        incoming = req_headers.get("x-amj-origin") or req_headers.get("X-AMJ-Origin") or ""
        import hmac as _hmac
        if not _hmac.compare_digest(incoming, SITE_API_ORIGIN_SECRET):
            return _error(403, "Forbidden")

    # Phase 4.5 SCOPED (2026-05-16): single dispatch for 11 simple delegate
    # routes. The complex inline routes (correlations, changes_since, etc.)
    # remain below — they include query-param parsing or multi-step logic.
    _route_entry = _SIMPLE_ROUTES.get(path)
    if _route_entry:
        _allowed_methods, _handler_fn = _route_entry
        if _allowed_methods is not None and method not in _allowed_methods:
            return _error(405, f"Method not allowed; use {'/'.join(sorted(_allowed_methods))}")
        return _handler_fn(event)

    # HP-06: Correlations with optional ?featured=true&limit=N
    if path == "/api/correlations":
        return handle_correlations(event)

    # Phase 1: Changes-since (GET with query params)
    if path == "/api/changes-since":
        qs = event.get("queryStringParameters") or {}
        return handle_changes_since(qs)

    # Phase 1: Observatory week (GET with query params)
    if path == "/api/observatory_week":
        qs = event.get("queryStringParameters") or {}
        return handle_observatory_week(qs)

    # BL-04: Field Notes (GET with optional ?week= query param)
    if path == "/api/field_notes":
        qs = event.get("queryStringParameters") or {}
        week_param = qs.get("week")
        fn_pk = f"{USER_PREFIX}field_notes"

        if week_param:
            # Single entry mode
            item = table.get_item(Key={"pk": fn_pk, "sk": f"WEEK#{week_param}"}).get("Item")
            if not item:
                return _ok({"entry": None, "week": week_param}, cache_seconds=300)
            item = _decimal_to_float(item)
            return _ok({"entry": {
                "week": item.get("week", week_param),
                "ai_present": item.get("ai_present", ""),
                "ai_cautionary": item.get("ai_cautionary"),
                "ai_affirming": item.get("ai_affirming"),
                "ai_tone": item.get("ai_tone", "mixed"),
                "ai_generated_at": item.get("ai_generated_at"),
                "matthew_agreement": item.get("matthew_agreement"),
                "matthew_logged_at": item.get("matthew_logged_at"),
            }}, cache_seconds=300)
        else:
            # List mode — return all weeks (most recent first)
            resp = table.query(
                KeyConditionExpression=Key("pk").eq(fn_pk),
                ScanIndexForward=False,
                Limit=52,
            )
            items = _decimal_to_float(resp.get("Items", []))
            entries = [{
                "week": i.get("week", i.get("sk", "").replace("WEEK#", "")),
                "ai_tone": i.get("ai_tone", "mixed"),
                "ai_generated_at": i.get("ai_generated_at"),
                "has_matthew_response": bool(i.get("matthew_agreement")),
            } for i in items]
            return _ok({"entries": entries, "count": len(entries)}, cache_seconds=300)

    # AI Analysis (GET with ?expert= query param)
    if path == "/api/ai_analysis":
        qs = event.get("queryStringParameters") or {}
        expert_key = qs.get("expert", "mind")
        if expert_key not in ("mind", "nutrition", "training", "physical", "explorer", "labs", "glucose", "sleep"):
            return _error(400, "Invalid expert key")
        ai_pk = f"{USER_PREFIX}ai_analysis"
        ai_item = table.get_item(Key={"pk": ai_pk, "sk": f"EXPERT#{expert_key}"}).get("Item")
        if not ai_item:
            return _ok({"expert_key": expert_key, "analysis": None, "generated_at": None}, cache_seconds=300)
        ai_item = _decimal_to_float(ai_item)
        analysis_val = ai_item.get("analysis", "")
        if "[AI_UNAVAILABLE]" in (analysis_val or ""):
            analysis_val = None
        resp_data = {
            "expert_key": expert_key,
            "analysis": analysis_val,
            "generated_at": ai_item.get("generated_at", ""),
        }
        if ai_item.get("key_recommendation"):
            resp_data["key_recommendation"] = ai_item["key_recommendation"]
        if ai_item.get("journaling_prompt"):
            resp_data["journaling_prompt"] = ai_item["journaling_prompt"]
        if ai_item.get("elena_quote"):
            resp_data["elena_quote"] = ai_item["elena_quote"]
        if ai_item.get("week_number"):
            resp_data["week_number"] = int(ai_item["week_number"])
        if ai_item.get("days_in_experiment"):
            resp_data["days_in_experiment"] = int(ai_item["days_in_experiment"])
        return _ok(resp_data, cache_seconds=300)

    # Coach Intelligence Analysis (GET with ?domain= query param)
    if path == "/api/coach_analysis":
        qs = event.get("queryStringParameters") or {}
        domain = qs.get("domain", "sleep")
        _coach_map = {
            "sleep": "sleep_coach", "nutrition": "nutrition_coach", "training": "training_coach",
            "mind": "mind_coach", "physical": "physical_coach", "glucose": "glucose_coach",
            "labs": "labs_coach", "explorer": "explorer_coach",
        }
        coach_id = _coach_map.get(domain)
        if not coach_id:
            return _error(400, "Invalid domain")

        _coach_display = {
            "sleep_coach": {"name": "Dr. Lisa Park", "initials": "LP", "title": "Sleep & Circadian Rhythm Specialist", "color": "#818cf8"},
            "nutrition_coach": {"name": "Dr. Marcus Webb", "initials": "MW", "title": "Evidence-Based Nutrition", "color": "#10b981"},
            "training_coach": {"name": "Dr. Sarah Chen", "initials": "SC", "title": "Exercise Physiology & Strength", "color": "#3db88a"},
            "mind_coach": {"name": "Dr. Nathan Reeves", "initials": "NR", "title": "Psychiatrist \u2014 Behavioral Patterns", "color": "#a78bfa"},
            "physical_coach": {"name": "Dr. Victor Reyes", "initials": "VR", "title": "Longevity & Body Composition", "color": "#f59e0b"},
            "glucose_coach": {"name": "Dr. Amara Patel", "initials": "AP", "title": "Metabolic Health & CGM", "color": "#2dd4bf"},
            "labs_coach": {"name": "Dr. James Okafor", "initials": "JO", "title": "Clinical Pathology & Preventive Labs", "color": "#5ba4cf"},
            "explorer_coach": {"name": "Dr. Henning Brandt", "initials": "HB", "title": "Biostatistics & N=1 Research", "color": "#e879f9"},
        }

        try:
            coach_pk = f"COACH#{coach_id}"

            # 1. Most recent OUTPUT# record
            out_resp = table.query(
                KeyConditionExpression=Key("pk").eq(coach_pk) & Key("sk").begins_with("OUTPUT#"),
                ScanIndexForward=False, Limit=1,
            )
            out_items = out_resp.get("Items", [])
            if not out_items:
                return _ok({"coach_id": coach_id, "domain": domain, "analysis": None}, cache_seconds=300)

            output = _decimal_to_float(out_items[0])
            # Prefer observatory_summary over full content
            analysis_text = output.get("observatory_summary") or output.get("content", "")
            if "[AI_UNAVAILABLE]" in (analysis_text or ""):
                analysis_text = None

            # 2. Open threads
            thread_reference = None
            try:
                thread_resp = table.query(
                    KeyConditionExpression=Key("pk").eq(coach_pk) & Key("sk").begins_with("THREAD#"),
                )
                threads = [_decimal_to_float(t) for t in thread_resp.get("Items", []) if t.get("status") == "open"]
                if threads:
                    # Pick most recently referenced thread
                    threads.sort(key=lambda t: t.get("last_referenced", ""), reverse=True)
                    thread_reference = threads[0].get("summary", "")
            except Exception:
                pass

            # 3. Ensemble digest — cross-coach references
            cross_coach_reference = None
            try:
                dig_resp = table.query(
                    KeyConditionExpression=Key("pk").eq("ENSEMBLE#digest") & Key("sk").begins_with("CYCLE#"),
                    ScanIndexForward=False, Limit=1,
                )
                dig_items = dig_resp.get("Items", [])
                if dig_items:
                    digest = _decimal_to_float(dig_items[0])
                    disagreements = digest.get("active_disagreements", [])
                    for d in disagreements:
                        coaches = d.get("coaches", [])
                        if coach_id in coaches:
                            cross_coach_reference = d.get("topic", "")
                            break
            except Exception:
                pass

            # 4. Computation guardrails — data availability
            data_availability = "preliminary"
            try:
                comp_resp = table.query(
                    KeyConditionExpression=Key("pk").eq("COACH#computation") & Key("sk").begins_with("RESULTS#"),
                    ScanIndexForward=False, Limit=1,
                )
                comp_items = comp_resp.get("Items", [])
                if comp_items:
                    guardrails = _decimal_to_float(comp_items[0]).get("statistical_guardrails", {})
                    # Find the guardrail for this domain's primary source
                    for source_name, source_guardrails in guardrails.items():
                        if isinstance(source_guardrails, dict):
                            for metric, g in source_guardrails.items():
                                if isinstance(g, dict):
                                    data_availability = g.get("data_availability", "preliminary")
                                    break
                            break
            except Exception:
                pass

            # 5. Revision signal — recent learning records
            revision_signal = None
            try:
                learn_resp = table.query(
                    KeyConditionExpression=Key("pk").eq(coach_pk) & Key("sk").begins_with("LEARNING#"),
                    ScanIndexForward=False, Limit=3,
                )
                for item in learn_resp.get("Items", []):
                    item = _decimal_to_float(item)
                    if item.get("type") == "position_revision":
                        revision_signal = item.get("revised_position", "")[:100]
                        break
            except Exception:
                pass

            # 6. Confidence language
            confidence_language = "preliminary"
            try:
                themes = output.get("themes", [])
                # Use the overall confidence from the generation if available
                conf = output.get("confidence")
                if conf is not None:
                    conf_f = float(conf)
                    if conf_f >= 0.85:
                        confidence_language = "highly_confident"
                    elif conf_f >= 0.7:
                        confidence_language = "fairly_confident"
                    elif conf_f >= 0.5:
                        confidence_language = "moderate"
                    elif conf_f >= 0.3:
                        confidence_language = "preliminary"
                    else:
                        confidence_language = "uncertain"
            except Exception:
                pass

            display = _coach_display.get(coach_id, {})
            resp = {
                "coach_id": coach_id,
                "coach_name": display.get("name", ""),
                "coach_initials": display.get("initials", ""),
                "coach_title": display.get("title", ""),
                "coach_color": display.get("color", ""),
                "domain": domain,
                "analysis": analysis_text,
                "key_recommendation": output.get("key_recommendation") or (
                    output.get("themes", [""])[0] if output.get("themes") else None
                ),
                "elena_quote": output.get("elena_quote"),
                "journaling_prompt": output.get("journaling_prompt"),
                "thread_reference": thread_reference,
                "revision_signal": revision_signal,
                "cross_coach_reference": cross_coach_reference,
                "confidence_language": confidence_language,
                "data_availability": data_availability,
                "generated_at": output.get("created_at") or output.get("generated_at", ""),
                "week_number": output.get("week_number"),
                "days_in_experiment": output.get("days_in_experiment"),
            }

            # Add cross-domain context note from the integrator (if available)
            try:
                _int_resp = table.get_item(Key={"pk": f"{USER_PREFIX}ai_analysis", "sk": "EXPERT#integrator"})
                _int_item = _decimal_to_float(_int_resp.get("Item", {}))
                _cdn = _int_item.get("cross_domain_notes", {})
                if isinstance(_cdn, dict) and domain in _cdn:
                    resp["cross_domain_note"] = _cdn[domain]
                if _int_item.get("analysis"):
                    resp["weekly_priority"] = _int_item["analysis"]
            except Exception:
                pass

            # Strip None values for cleaner JSON
            resp = {k: v for k, v in resp.items() if v is not None}
            return _ok(resp, cache_seconds=300)
        except Exception as _e:
            print(f"[WARN] /api/coach_analysis failed: {_e}")
            return _ok({"coach_id": coach_id, "domain": domain, "analysis": None}, cache_seconds=60)

    # Coaching Dashboard (GET — assembled dashboard data)
    if path == "/api/coaching-dashboard":
        try:
            _cd_coach_display = {
                "sleep": {"coach_id": "sleep", "name": "Dr. Lisa Park", "initials": "LP", "title": "Sleep & Circadian Rhythm Specialist", "color": "#818cf8", "observatory_link": "/sleep/"},
                "nutrition": {"coach_id": "nutrition", "name": "Dr. Marcus Webb", "initials": "MW", "title": "Evidence-Based Nutrition", "color": "#10b981", "observatory_link": "/nutrition/"},
                "training": {"coach_id": "training", "name": "Dr. Sarah Chen", "initials": "SC", "title": "Exercise Physiology & Strength", "color": "#3db88a", "observatory_link": "/training/"},
                "mind": {"coach_id": "mind", "name": "Dr. Nathan Reeves", "initials": "NR", "title": "Psychiatrist — Behavioral Patterns", "color": "#a78bfa", "observatory_link": "/mind/"},
                "physical": {"coach_id": "physical", "name": "Dr. Victor Reyes", "initials": "VR", "title": "Longevity & Body Composition", "color": "#f59e0b", "observatory_link": "/physical/"},
                "glucose": {"coach_id": "glucose", "name": "Dr. Amara Patel", "initials": "AP", "title": "Metabolic Health & CGM", "color": "#2dd4bf", "observatory_link": "/glucose/"},
                "labs": {"coach_id": "labs", "name": "Dr. James Okafor", "initials": "JO", "title": "Clinical Pathology & Preventive Labs", "color": "#5ba4cf", "observatory_link": "/labs/"},
                "explorer": {"coach_id": "explorer", "name": "Dr. Henning Brandt", "initials": "HB", "title": "Biostatistics & N=1 Research", "color": "#e879f9", "observatory_link": "/explorer/"},
            }
            _cd_coach_id_map = {
                "sleep": "sleep_coach", "nutrition": "nutrition_coach", "training": "training_coach",
                "mind": "mind_coach", "physical": "physical_coach", "glucose": "glucose_coach",
                "labs": "labs_coach", "explorer": "explorer_coach",
            }

            # 1. Weekly priority from integrator
            _cd_priority = {"text": None, "coach_name": "Dr. Kai Nakamura", "generated_at": None}
            try:
                _cd_int = table.get_item(Key={"pk": f"{USER_PREFIX}ai_analysis", "sk": "EXPERT#integrator"}).get("Item")
                if _cd_int:
                    _cd_int = _decimal_to_float(_cd_int)
                    _cd_priority["text"] = _cd_int.get("analysis", "")
                    _cd_priority["generated_at"] = _cd_int.get("generated_at", "")
            except Exception:
                pass

            # 2. Open actions from coach_actions source
            _cd_actions = []
            try:
                _cd_act_resp = table.query(
                    KeyConditionExpression=Key("pk").eq(f"{USER_PREFIX}coach_actions"),
                    Limit=50,
                )
                for _act in _cd_act_resp.get("Items", []):
                    _act = _decimal_to_float(_act)
                    if _act.get("status") == "open":
                        _cd_actions.append({
                            "coach_id": _act.get("coach_id", ""),
                            "domain": _act.get("domain", ""),
                            "action_text": _act.get("action_text", _act.get("action", "")),
                            "issued_date": _act.get("issued_date", _act.get("sk", "").replace("DATE#", "")),
                            "status": "open",
                        })
            except Exception:
                pass

            # 3. Coach thread summaries + predictions
            _cd_coaches = []
            _cd_predictions = []
            for _cd_domain, _cd_info in _cd_coach_display.items():
                _cd_coach_pk = f"COACH#{_cd_coach_id_map[_cd_domain]}"
                coach_entry = dict(_cd_info)
                coach_entry["position_summary"] = ""
                coach_entry["emotional_investment"] = "neutral"
                coach_entry["prediction_count"] = 0
                coach_entry["data_phase"] = "established"

                # Latest output for position_summary
                try:
                    _cd_out = table.query(
                        KeyConditionExpression=Key("pk").eq(_cd_coach_pk) & Key("sk").begins_with("OUTPUT#"),
                        ScanIndexForward=False, Limit=1,
                    )
                    _cd_out_items = _cd_out.get("Items", [])
                    if _cd_out_items:
                        _cd_out_item = _decimal_to_float(_cd_out_items[0])
                        coach_entry["position_summary"] = (
                            _cd_out_item.get("position_summary")
                            or _cd_out_item.get("observatory_summary", "")[:200]
                            or _cd_out_item.get("content", "")[:200]
                        )
                        coach_entry["emotional_investment"] = _cd_out_item.get("emotional_investment", "neutral")
                        # Count predictions
                        preds = _cd_out_item.get("predictions", [])
                        if isinstance(preds, list):
                            coach_entry["prediction_count"] = len(preds)
                            for _p in preds[-3:]:
                                if isinstance(_p, dict):
                                    _cd_predictions.append({
                                        "coach_id": _cd_domain,
                                        "text": _p.get("text", _p.get("prediction", "")),
                                        "confidence": _p.get("confidence", "medium"),
                                        "status": _p.get("status", "pending"),
                                        "date": _cd_out_item.get("sk", "").replace("OUTPUT#", ""),
                                    })
                except Exception:
                    pass

                _cd_coaches.append(coach_entry)

            # Sort coaches: invested/concerned first, then neutral
            _ei_order = {"concerned": 0, "invested": 1, "curious": 2, "neutral": 3}
            _cd_coaches.sort(key=lambda c: _ei_order.get(c.get("emotional_investment", "neutral"), 3))

            # Limit predictions to 10 most recent
            _cd_predictions = _cd_predictions[-10:]

            return _ok({
                "weekly_priority": _cd_priority,
                "open_actions": _cd_actions,
                "coaches": _cd_coaches,
                "predictions": _cd_predictions,
            }, cache_seconds=300)
        except Exception as _e:
            print(f"[WARN] /api/coaching-dashboard failed: {_e}")
            return _ok({"weekly_priority": {}, "open_actions": [], "coaches": [], "predictions": []}, cache_seconds=60)

    # Prediction Ledger (GET with query params)
    if path == "/api/predictions":
        try:
            qs = event.get("queryStringParameters") or {}
            status_filter = qs.get("status", "all")
            coach_filter = qs.get("coach_id", "")
            limit = min(int(qs.get("limit", "50")), 200)

            _pred_coach_names = {
                "sleep": "Dr. Lisa Park", "nutrition": "Dr. Marcus Webb",
                "training": "Dr. Sarah Chen", "mind": "Dr. Nathan Reeves",
                "physical": "Dr. Victor Reyes", "glucose": "Dr. Amara Patel",
                "labs": "Dr. James Okafor", "explorer": "Dr. Henning Brandt",
            }
            _pred_coach_ids = list(_pred_coach_names.keys())
            _pred_coach_id_map = {
                "sleep": "sleep_coach", "nutrition": "nutrition_coach",
                "training": "training_coach", "mind": "mind_coach",
                "physical": "physical_coach", "glucose": "glucose_coach",
                "labs": "labs_coach", "explorer": "explorer_coach",
            }

            if coach_filter and coach_filter not in _pred_coach_ids:
                return _error(400, "Invalid coach_id")

            scan_coaches = [coach_filter] if coach_filter else _pred_coach_ids
            all_predictions = []
            by_coach = {}

            for cid in scan_coaches:
                coach_pk = f"COACH#{_pred_coach_id_map[cid]}"
                by_coach[cid] = {"total": 0, "confirmed": 0, "refuted": 0, "pending": 0}

                try:
                    out_resp = table.query(
                        KeyConditionExpression=Key("pk").eq(coach_pk) & Key("sk").begins_with("OUTPUT#"),
                        ScanIndexForward=False,
                        Limit=12,
                    )
                    for out_item in out_resp.get("Items", []):
                        out_item = _decimal_to_float(out_item)
                        preds = out_item.get("predictions", [])
                        out_date = out_item.get("sk", "").replace("OUTPUT#", "")
                        if not isinstance(preds, list):
                            continue
                        for p in preds:
                            if not isinstance(p, dict):
                                continue
                            p_status = p.get("status", "pending")
                            by_coach[cid]["total"] += 1
                            if p_status in ("confirmed", "refuted", "pending"):
                                by_coach[cid][p_status] += 1
                            else:
                                by_coach[cid]["pending"] += 1

                            if status_filter != "all" and p_status != status_filter:
                                continue

                            all_predictions.append({
                                "coach_id": cid,
                                "coach_name": _pred_coach_names[cid],
                                "text": p.get("text", p.get("prediction", "")),
                                "confidence": p.get("confidence", "medium"),
                                "status": p_status,
                                "date": out_date,
                                "target_date": p.get("target_date", ""),
                            })
                except Exception:
                    pass

            # Sort predictions by date descending
            all_predictions.sort(key=lambda x: x.get("date", ""), reverse=True)
            all_predictions = all_predictions[:limit]

            # Compute overall stats
            total = sum(c["total"] for c in by_coach.values())
            confirmed = sum(c["confirmed"] for c in by_coach.values())
            refuted = sum(c["refuted"] for c in by_coach.values())
            pending = sum(c["pending"] for c in by_coach.values())
            resolved = confirmed + refuted
            accuracy_pct = round(confirmed / resolved * 100, 1) if resolved > 0 else 0

            return _ok({
                "overall": {
                    "total": total, "confirmed": confirmed,
                    "refuted": refuted, "pending": pending,
                    "accuracy_pct": accuracy_pct,
                },
                "by_coach": by_coach,
                "predictions": all_predictions,
            }, cache_seconds=300)
        except Exception as _e:
            print(f"[WARN] /api/predictions failed: {_e}")
            return _ok({"overall": {}, "by_coach": {}, "predictions": []}, cache_seconds=60)

    # Coach Learning Timeline (GET with ?coach_id= query param)
    if path == "/api/coach_timeline":
        try:
            qs = event.get("queryStringParameters") or {}
            coach_id = qs.get("coach_id", "")

            _tl_coach_names = {
                "sleep": "Dr. Lisa Park", "nutrition": "Dr. Marcus Webb",
                "training": "Dr. Sarah Chen", "mind": "Dr. Nathan Reeves",
                "physical": "Dr. Victor Reyes", "glucose": "Dr. Amara Patel",
                "labs": "Dr. James Okafor", "explorer": "Dr. Henning Brandt",
            }
            _tl_coach_id_map = {
                "sleep": "sleep_coach", "nutrition": "nutrition_coach",
                "training": "training_coach", "mind": "mind_coach",
                "physical": "physical_coach", "glucose": "glucose_coach",
                "labs": "labs_coach", "explorer": "explorer_coach",
            }

            if coach_id not in _tl_coach_names:
                return _error(400, "Invalid or missing coach_id")

            coach_pk = f"COACH#{_tl_coach_id_map[coach_id]}"
            milestones = []

            # Query OUTPUT# records for stance_changes, predictions, surprises, emotional_investment
            try:
                out_resp = table.query(
                    KeyConditionExpression=Key("pk").eq(coach_pk) & Key("sk").begins_with("OUTPUT#"),
                    ScanIndexForward=False,
                    Limit=20,
                )
                prev_investment = None
                for out_item in out_resp.get("Items", []):
                    out_item = _decimal_to_float(out_item)
                    out_date = out_item.get("sk", "").replace("OUTPUT#", "")

                    # Stance changes
                    stance_changes = out_item.get("stance_changes", [])
                    if isinstance(stance_changes, list):
                        for sc in stance_changes:
                            if isinstance(sc, dict):
                                milestones.append({
                                    "date": out_date,
                                    "type": "stance_change",
                                    "text": sc.get("topic", sc.get("text", "Position revised")),
                                    "detail": sc.get("new_stance", sc.get("detail", "")),
                                })
                            elif isinstance(sc, str):
                                milestones.append({
                                    "date": out_date,
                                    "type": "stance_change",
                                    "text": sc,
                                    "detail": "",
                                })

                    # Resolved predictions
                    preds = out_item.get("predictions", [])
                    if isinstance(preds, list):
                        for p in preds:
                            if isinstance(p, dict) and p.get("status") in ("confirmed", "refuted"):
                                milestones.append({
                                    "date": out_date,
                                    "type": "prediction_resolved",
                                    "text": p.get("text", p.get("prediction", "")),
                                    "detail": f"Status: {p['status']}",
                                })

                    # Surprises
                    surprises = out_item.get("surprises", [])
                    if isinstance(surprises, list):
                        for s in surprises:
                            if isinstance(s, dict):
                                milestones.append({
                                    "date": out_date,
                                    "type": "surprise",
                                    "text": s.get("text", s.get("observation", "")),
                                    "detail": s.get("detail", s.get("significance", "")),
                                })
                            elif isinstance(s, str):
                                milestones.append({
                                    "date": out_date,
                                    "type": "surprise",
                                    "text": s,
                                    "detail": "",
                                })

                    # Emotional investment changes
                    current_investment = out_item.get("emotional_investment", "neutral")
                    if prev_investment and current_investment != prev_investment:
                        milestones.append({
                            "date": out_date,
                            "type": "investment_change",
                            "text": f"Investment shifted: {prev_investment} -> {current_investment}",
                            "detail": "",
                        })
                    prev_investment = current_investment

                    # Learning log entries
                    learning_log = out_item.get("learning_log", [])
                    if isinstance(learning_log, list):
                        for entry in learning_log:
                            if isinstance(entry, dict):
                                milestones.append({
                                    "date": out_date,
                                    "type": "stance_change",
                                    "text": entry.get("lesson", entry.get("text", "")),
                                    "detail": entry.get("detail", ""),
                                })
            except Exception:
                pass

            # Also check LEARNING# records
            try:
                learn_resp = table.query(
                    KeyConditionExpression=Key("pk").eq(coach_pk) & Key("sk").begins_with("LEARNING#"),
                    ScanIndexForward=False,
                    Limit=20,
                )
                for l_item in learn_resp.get("Items", []):
                    l_item = _decimal_to_float(l_item)
                    l_date = l_item.get("sk", "").replace("LEARNING#", "")
                    l_type = l_item.get("type", "stance_change")
                    milestones.append({
                        "date": l_date,
                        "type": l_type if l_type in ("stance_change", "prediction_resolved", "surprise", "investment_change") else "stance_change",
                        "text": l_item.get("lesson", l_item.get("revised_position", l_item.get("text", ""))),
                        "detail": l_item.get("detail", l_item.get("evidence", "")),
                    })
            except Exception:
                pass

            # Sort by date descending, deduplicate by text
            milestones.sort(key=lambda m: m.get("date", ""), reverse=True)
            seen_texts = set()
            unique_milestones = []
            for m in milestones:
                key = m.get("text", "")[:80]
                if key and key not in seen_texts:
                    seen_texts.add(key)
                    unique_milestones.append(m)

            return _ok({
                "coach_id": coach_id,
                "coach_name": _tl_coach_names[coach_id],
                "milestones": unique_milestones[:50],
            }, cache_seconds=600)
        except Exception as _e:
            print(f"[WARN] /api/coach_timeline failed: {_e}")
            return _ok({"coach_id": "", "coach_name": "", "milestones": []}, cache_seconds=60)

    # Weekly Priority (GET — integrator synthesis)
    if path == "/api/weekly_priority":
        try:
            _int_resp = table.get_item(Key={"pk": f"{USER_PREFIX}ai_analysis", "sk": "EXPERT#integrator"})
            _int_item = _decimal_to_float(_int_resp.get("Item", {}))
            if not _int_item:
                return _ok({"weekly_priority": None, "cross_domain_notes": {}}, cache_seconds=300)
            return _ok({
                "weekly_priority": _int_item.get("analysis", ""),
                "cross_domain_notes": _int_item.get("cross_domain_notes", {}),
                "generated_at": _int_item.get("generated_at", ""),
                "week_number": _int_item.get("week_number"),
                "coach_name": "Dr. Kai Nakamura",
                "coach_title": "Integrative Health Director",
            }, cache_seconds=300)
        except Exception as _e:
            print(f"[WARN] /api/weekly_priority failed: {_e}")
            return _ok({"weekly_priority": None}, cache_seconds=60)


    if method != "GET":
        return _error(405, "Method not allowed")

    handler = ROUTES.get(path)
    if not handler:
        _emit_route_log(404)
        return _error(404, "Not found")

    try:
        result = handler()
        _emit_route_log(result.get("statusCode", 200))
        return result
    except Exception as e:
        logger.error(f"[site_api] {path} failed: {e}")
        _emit_route_log(500)
        return _error(500, "Internal error — check CloudWatch logs")
