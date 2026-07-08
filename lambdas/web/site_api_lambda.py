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

import base64 as _b64  # noqa: F401 — used by subscriber-token helpers

# stdlib
import hashlib  # noqa: F401 — used by handlers
import hmac as _hmac  # noqa: F401 — used by subscriber-token helpers
import json
import os
import urllib.request  # noqa: F401 — used by AI handlers (kept for backward-compat)
from decimal import Decimal  # noqa: F401 — kept for backward-compat with handlers

# third-party
import boto3  # noqa: F401 — kept for handlers that create clients
from boto3.dynamodb.conditions import Key

# shared layer
from phase_filter import with_phase_filter  # noqa: F401 — used by handlers below

from web.site_api_agents import handle_agent_activity
from web.site_api_autonomic import (
    handle_autonomic_balance,
    handle_zone2_breakdown,
)

# P1.1 Phase B extension (2026-05-27): coach + misc inline blocks extracted.
from web.site_api_coach import (
    handle_ai_analysis,
    handle_calibration,
    handle_coach,
    handle_coach_analysis,
    handle_coach_team,
    handle_coach_timeline,
    handle_coaches,
    handle_experiment_synthesis,
    handle_field_notes,
    handle_panel_ledger,
    handle_predictions,
    handle_recap,
    handle_voice_fidelity,
    handle_weekly_priority,
)

# P1.1 Phase B (2026-05-26): shared helpers extracted to sibling module.
# Re-import as module-level names so the rest of this file (and the
# ROUTES dict) reference them unchanged.
from web.site_api_common import (  # config; AWS; CORS; caches; helpers; request-id state (set by lambda_handler; read by _ok/_error)
    CORS_HEADERS,
    S3_REGION,
    SITE_API_ORIGIN_SECRET,
    USER_PREFIX,
    _decimal_to_float,
    _error,
    _ok,
    get_request_id,
    logger,
    set_request_id,
    table,
)

# P1.1 Phase B step 6 (2026-05-26): data cluster extracted.
from web.site_api_data import (
    handle_changes_since,
    handle_circadian,
    handle_correlations,
    handle_cycle_compare,
    handle_device_agreement,
    handle_discoveries,
    handle_domains,
    handle_experiments,
    handle_forecast,
    handle_fulfillment_ritual,
    handle_genome_risks,
    handle_glucose,
    handle_habit_registry,
    handle_habit_streaks,
    handle_habits,
    handle_inference_receipt,
    handle_labs,
    handle_last_sync,
    handle_ledger,
    handle_observatory_week,
    handle_phenoage,
    handle_pillar_coupling,
    handle_platform_stats,
    handle_presence,
    handle_protocols,
    handle_scenarios,
    handle_sleep_correlations,
    handle_sleep_detail,
    handle_source_freshness,
    handle_state_of_matthew,
    handle_supplements,
    handle_survival,
    handle_tools_baseline,
    handle_vice_streaks,
    handle_what_changed,
    handle_wrong,
)

# P1.1 Phase B step 3 (2026-05-26): status + pulse handlers extracted.
from web.site_api_intelligence import (
    handle_hypotheses,
    handle_intelligence_summary,
    handle_pulse,
    handle_pulse_history,
    handle_status,
    handle_status_summary,
)

# P1.1 Phase B step 2 (2026-05-26): observatory handlers extracted to sibling module.
from web.site_api_observatory import (
    handle_benchmark_trends,
    handle_deficit_sustainability,
    handle_food_delivery_overview,
    handle_frequent_meals,
    handle_journal_analysis,
    handle_meal_glucose,
    handle_meal_responses,
    handle_mind_overview,
    handle_nutrition_overview,
    handle_physical_overview,
    handle_protein_sources,
    handle_strength_benchmarks,
    handle_strength_deep_dive,
    handle_training_overview,
    handle_weekly_physical_summary,
    handle_workouts,
)

# P1.1 Phase B step 5 (2026-05-26): vitals cluster extracted.
from web.site_api_reading import (
    handle_constellation,
    handle_reading_overview,
    handle_reading_shelf,
)

# P1.1 Phase B step 4 (2026-05-26): social cluster extracted to sibling module.
from web.site_api_social import (
    _handle_board_question,
    _handle_challenge_checkin,
    _handle_challenge_follow,
    _handle_challenge_vote,
    _handle_experiment_detail,
    _handle_experiment_follow,
    _handle_experiment_suggest,
    _handle_experiment_vote,
    _handle_nudge,
    _handle_predict_week,
    _handle_ritual_log,
    _handle_submit_finding,
    _handle_verify_subscriber,
    handle_challenge_catalog,
    handle_challenges,
    handle_current_challenge,
    handle_experiment_library,
    handle_predict_week_tally,
    handle_subscriber_count,
)
from web.site_api_vitals import (
    handle_achievements,
    handle_character,
    handle_character_config,
    handle_character_stats,
    handle_journey,
    handle_journey_timeline,
    handle_journey_waveform,
    handle_snapshot,
    handle_timeline,
    handle_vitals,
    handle_weight_progress,
)

# ── Endpoint handlers ───────────────────────────────────────

# ── BS-11: Timeline data ────────────────────────────────────────

# ── Sprint 9: Supplements + Habits public endpoints ─────────────

# ── WEB-CE: Correlation data ────────────────────────────────────

# ── BS-BM2: Genome risk data ────────────────────────────────────

# ── WR-24: Subscriber verification ──────────────────────────────────────────


# ── S2-T2-2: Board Ask ────────────────────────────────────────────────────────

# (The board persona definitions moved to site_api_ai_lambda's COACH_ROSTER —
#  /api/board_ask is served by the separate AI lambda; the old duplicate cast
#  here was dead code carrying retired wire IDs. Removed 2026-07-03, #373.)

BOARD_RATE_LIMIT = 5  # per IP per hour
# ── Ask the Platform (AI Q&A) ─────────────────────────────────────


# R17-04: Separate Anthropic key for site-api — injected via CDK env var
AI_SECRET_NAME = os.environ.get("AI_SECRET_NAME", "life-platform/site-api-ai-key")


# ── ARCH-03: Achievements endpoint ──────────────────────────

# ── ARCH-02: Snapshot endpoint ──────────────────────────────

# P1.1 Phase B step 7 follow-up (2026-05-26): NUDGE_CATEGORIES, NUDGE_LABELS,
# FINDING_RATE_LIMIT moved with their handlers to site_api_social.py (CI lint
# caught the orphan references).


# ── EL-2: Experiment Library endpoint ───────────────────────

# ── EL-3/4: Experiment Vote POST handler ────────────────────

# ── EL-F1: Per-experiment follow (email interest) ─────────

# ── EL-F2: Single experiment detail endpoint ────────────────

# ── Router ──────────────────────────────────────────────────

# P1.1 Phase B step 7 (2026-05-26): removed dead code in this section:
#   • _load_s3_json — moved to site_api_common.py (handle_protocols + handle_domains
#     now import it from there via site_api_data.py)
#   • handle_ai_analysis stub — the live handler is inline in lambda_handler
#     below (/api/ai_analysis takes ?expert= query param so it never went
#     through the ROUTES table). The stub returned None on direct call, which
#     ROUTES handled by sending None responses — kept the inline block, removed
#     the misleading function.


# ── Phase 1: Changes-Since endpoint ─────────────────────────────
# ── Phase 1: Observatory Week endpoint ─────────────────────────
# ── Benchmark trends endpoint ─────────────────────────────────
# ── Meal responses endpoint ───────────────────────────────────
# ── Experiment suggestion POST handler ────────────────────────
def handle_vacation_fund() -> dict:
    """GET /api/vacation_fund — workout miles since experiment start → USD fund.
    Read-only; delegates the math to the shared vacation_fund layer module."""
    try:
        from vacation_fund import compute_vacation_fund

        return _ok(compute_vacation_fund(), cache_seconds=900)
    except Exception as e:
        logger.error(f"[site_api] /api/vacation_fund failed: {e}")
        return _error(500, "vacation fund unavailable")


def handle_methods() -> dict:
    """GET /api/methods — the auto-generated statistics registry (#544, ADR-105).

    Pure and deterministic: no DB/S3 reads, just the in-code registry (formula, window,
    limitations, source module) that also renders the public /method/registry/ page —
    same source, two surfaces. Long cache TTL since the registry only changes on deploy.
    """
    try:
        from methods_registry import list_categories, list_stats

        return _ok(
            {
                "stats": list_stats(),
                "categories": list_categories(),
            },
            cache_seconds=3600,
        )
    except Exception as e:
        logger.error(f"[site_api] /api/methods failed: {e}")
        return _error(500, "methods registry unavailable")


ROUTES = {
    "/api/vitals": handle_vitals,
    # RQA-06/07 (#414): two computed views ported from the private MCP tools to the data door
    "/api/autonomic_balance": handle_autonomic_balance,
    "/api/zone2": handle_zone2_breakdown,
    "/api/reading_shelf": handle_reading_shelf,  # Mind pillar (ADR-097) — public shelf
    "/api/reading_overview": handle_reading_overview,  # Mind pillar — wheel + stats + cockpit line
    "/api/constellation": handle_constellation,  # Mind pillar (Phase E) — the idea-graph signature
    "/api/journey": handle_journey,
    "/api/vacation_fund": handle_vacation_fund,
    "/api/methods": handle_methods,  # #544: the auto-generated statistics registry (ADR-105)
    "/api/character": handle_character,
    "/api/status": handle_status,
    "/api/status/summary": handle_status_summary,
    # BS-07: new public endpoints
    "/api/weight_progress": handle_weight_progress,
    "/api/cycle_compare": handle_cycle_compare,
    "/api/inference_receipt": handle_inference_receipt,
    "/api/wrong": handle_wrong,
    "/api/survival": handle_survival,
    "/api/character_config": handle_character_config,  # the sheet's "how the engine works" contract (P1.2)
    "/api/character_stats": handle_character_stats,
    "/api/habit_streaks": handle_habit_streaks,
    "/api/experiments": handle_experiments,
    "/api/current_challenge": handle_current_challenge,
    # Sprint 4: BS-11, WEB-CE, BS-BM2
    "/api/timeline": handle_timeline,
    "/api/correlations": handle_correlations,
    "/api/what_changed": handle_what_changed,  # SS-08 monthly "what changed"
    "/api/pillar_coupling": handle_pillar_coupling,  # #590 constellation edge weights
    "/api/genome_risks": handle_genome_risks,
    # Sprint 9: new public endpoints
    "/api/supplements": handle_supplements,
    "/api/habits": handle_habits,
    "/api/vice_streaks": handle_vice_streaks,
    "/api/fulfillment_ritual": handle_fulfillment_ritual,  # #769 (ADR-124): C-floor aggregate-only publish surface
    "/api/journey_timeline": handle_journey_timeline,
    "/api/journey_waveform": handle_journey_waveform,
    # Sprint 11: glucose + sleep intelligence pages
    "/api/glucose": handle_glucose,
    "/api/sleep_correlations": handle_sleep_correlations,
    "/api/sleep_detail": handle_sleep_detail,
    # Elite review (2026-06-15): surface two compute outputs that were stored
    # daily but never exposed — circadian-compliance score.
    # ( /api/sleep_reconciliation RETIRED #487/ADR-113 — dead merge + stale date, no consumers )
    "/api/circadian": handle_circadian,
    "/api/forecast": handle_forecast,
    "/api/scenarios": handle_scenarios,
    "/api/state_of_matthew": handle_state_of_matthew,  # #552 weekly model brief
    # ARCH-03: Achievement badges
    "/api/achievements": handle_achievements,
    # ARCH-02: Combined snapshot — single-call summary for pages that need vitals + journey + character
    "/api/snapshot": handle_snapshot,
    # WR-24 + S2-T2-2: handled specially in lambda_handler (POST routes)
    "/api/verify_subscriber": None,
    "/api/board_ask": None,
    "/api/submit_finding": None,  # NEW-1: POST handler in lambda_handler
    # EL-2: Experiment library (GET) + EL-3: Experiment vote (POST)
    "/api/experiment_library": handle_experiment_library,
    "/api/experiment_vote": None,  # POST handler in lambda_handler
    "/api/experiment_follow": None,  # EL-F1: POST handler in lambda_handler
    "/api/experiment_detail": None,  # EL-F2: GET with query params
    # DATA-DRIVEN: S3 config + DynamoDB source-of-truth endpoints
    "/api/protocols": handle_protocols,
    "/api/challenges": handle_challenges,
    "/api/challenge_catalog": handle_challenge_catalog,
    "/api/challenge_vote": None,  # POST handler in lambda_handler
    "/api/challenge_follow": None,  # POST handler in lambda_handler
    "/api/challenge_checkin": None,  # POST handler in lambda_handler
    "/api/domains": handle_domains,
    "/api/habit_registry": handle_habit_registry,
    # PULSE-A4: Daily pulse endpoint
    "/api/pulse": handle_pulse,
    "/api/pulse_history": handle_pulse_history,
    # Subscriber count social proof (read-only) — must NOT match /api/subscribe* CloudFront pattern
    "/api/sub_count": handle_subscriber_count,
    # Observatory pages
    "/api/nutrition_overview": handle_nutrition_overview,
    "/api/deficit_sustainability": handle_deficit_sustainability,  # RQA-05
    "/api/training_overview": handle_training_overview,
    "/api/workouts": handle_workouts,
    "/api/mind_overview": handle_mind_overview,
    "/api/physical_overview": handle_physical_overview,
    "/api/journal_analysis": handle_journal_analysis,
    "/api/ai_analysis": None,  # GET with ?expert= query param, handled in lambda_handler
    "/api/coach_analysis": None,  # GET with ?domain= query param, handled in lambda_handler (Coach Intelligence)
    "/api/weekly_priority": None,  # GET — integrator synthesis, handled in lambda_handler
    "/api/experiment_synthesis": handle_experiment_synthesis,  # C-1 — cross-week experiment arc
    "/api/recap": handle_recap,  # Phase 3 — Elena's "previously on" cold-open
    # BL-03: The Ledger / Snake Fund
    "/api/ledger": handle_ledger,
    # BL-04: Field Notes
    "/api/field_notes": None,  # GET with optional ?week= query param, handled in lambda_handler
    # BL-02: Bloodwork/Labs
    "/api/labs": handle_labs,
    "/api/phenoage": handle_phenoage,  # P1.5 — transparent Levine PhenoAge (Option A privacy)
    "/api/frequent_meals": handle_frequent_meals,
    "/api/protein_sources": handle_protein_sources,
    "/api/weekly_physical_summary": handle_weekly_physical_summary,
    "/api/strength_deep_dive": handle_strength_deep_dive,
    "/api/food_delivery_overview": handle_food_delivery_overview,
    "/api/meal_glucose": handle_meal_glucose,
    "/api/strength_benchmarks": handle_strength_benchmarks,
    # Benchmark trends + meal responses (stub endpoints)
    "/api/benchmark_trends": handle_benchmark_trends,
    "/api/meal_responses": handle_meal_responses,
    # Tools page: baseline vs current comparison
    "/api/tools_baseline": handle_tools_baseline,
    # Platform stats: single source of truth for all site pages
    "/api/platform_stats": handle_platform_stats,
    # Live pipeline status: per-source freshness (fresh/stale/paused)
    "/api/source_freshness": handle_source_freshness,
    # #735 (/verify/ page): Whoop vs Garmin cross-device HRV/RHR agreement
    "/api/device_agreement": handle_device_agreement,
    # #406: real intra-day ingestion write times for the cockpit sync strip
    "/api/last_sync": handle_last_sync,
    # Presence / quiet-stretch: is Matthew actively logging or has he gone quiet
    "/api/presence": handle_presence,
    # Discoveries page: active hypotheses + inner life + AI findings
    "/api/discoveries": handle_discoveries,
    # Experiment suggestion (POST)
    "/api/experiment_suggest": None,  # POST handler in lambda_handler
    # Phase 1: Reader engagement
    "/api/changes-since": None,  # GET with ?ts= query param
    "/api/observatory_week": None,  # GET with ?domain= query param
    # Coaching Dashboard
    "/api/coaching-dashboard": None,  # GET — assembled coaching dashboard data
    # Prediction Ledger + Coach Timeline
    "/api/predictions": None,  # GET with ?status=&coach_id=&limit= query params
    "/api/coach_timeline": None,  # GET with ?coach_id= query param
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


def _route_predict_week(event):
    """GET → read-only tallies; POST → record a prediction (one handler, two verbs)."""
    method = ((event.get("requestContext", {}).get("http", {}) or {}).get("method") or event.get("httpMethod") or "GET").upper()
    return _handle_predict_week(event) if method == "POST" else handle_predict_week_tally(event)


_SIMPLE_ROUTES = {
    "/api/verify_subscriber": ({"GET", "OPTIONS"}, _handle_verify_subscriber),
    "/api/nudge": ({"POST"}, _handle_nudge),
    "/api/submit_finding": ({"POST"}, _handle_submit_finding),
    "/api/experiment_vote": ({"POST"}, _handle_experiment_vote),
    "/api/experiment_follow": ({"POST"}, _handle_experiment_follow),
    "/api/experiment_suggest": ({"POST"}, _handle_experiment_suggest),
    "/api/challenge_checkin": ({"POST"}, _handle_challenge_checkin),
    "/api/ritual_log": ({"GET", "OPTIONS"}, _handle_ritual_log),  # #769 (ADR-124): one-tap evening ritual
    "/api/challenge_vote": ({"POST"}, _handle_challenge_vote),
    "/api/challenge_follow": ({"POST"}, _handle_challenge_follow),
    "/api/experiment_detail": (None, _handle_experiment_detail),
    "/api/predict_week": ({"GET", "POST"}, _route_predict_week),
    "/api/board_question": ({"POST"}, _handle_board_question),
}


def lambda_handler(event, context):
    """
    Main Lambda handler. Supports both API Gateway HTTP API and Function URL events.
    """
    import time as _time
    import uuid as _uuid

    _req_start = _time.time()

    path = event.get("rawPath") or event.get("path", "/")
    method = (event.get("requestContext", {}).get("http", {}).get("method") or event.get("httpMethod", "GET")).upper()

    # P3.4: assign a per-request correlation ID. Honor an inbound x-request-id
    # header if the client (CloudFront / a debugging operator) set one — this
    # lets the same id flow end-to-end. Otherwise generate a fresh uuid4.
    inbound_headers = event.get("headers") or {}
    incoming_rid = inbound_headers.get("x-request-id") or inbound_headers.get("X-Request-Id")
    set_request_id(incoming_rid if incoming_rid else _uuid.uuid4().hex[:16])

    # Phase 2.2 (2026-05-16): centralized request envelope validation.
    # Catches oversized bodies, injection patterns, malformed user_id/date/source
    # before any handler runs. Returns 4xx for obvious abuse; legit traffic unaffected.
    try:
        from request_validator import validate_envelope

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
                    "CloudWatchMetrics": [
                        {
                            "Namespace": "LifePlatform/SiteAPI",
                            "Dimensions": [["Route", "Method"]],
                            "Metrics": [
                                {"Name": "DurationMs", "Unit": "Milliseconds"},
                                {"Name": "ColdStart", "Unit": "Count"},
                            ],
                        }
                    ],
                },
                "_type": "route_metric",
                "Route": path,
                "Method": method,
                "status": status_code,
                "DurationMs": duration_ms,
                "ColdStart": 1 if _COLD_START else 0,
                "request_id": get_request_id(),
                "duration_ms": duration_ms,  # back-compat field name
                "cold_start": _COLD_START,
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

    # PB-08 / #8: Intelligence-page data feeds (Decision: public, read-only,
    # filters private hypotheses, evidence rules enforced inside the handlers).
    if path == "/api/hypotheses" and method == "GET":
        return handle_hypotheses()
    if path == "/api/intelligence_summary" and method == "GET":
        return handle_intelligence_summary()

    # Phase 1: Changes-since (GET with query params)
    if path == "/api/changes-since":
        qs = event.get("queryStringParameters") or {}
        return handle_changes_since(qs)

    # Time scrubber (2026-06-13): /api/character?date=YYYY-MM-DD — any past
    # morning's sheet. Dateless requests fall through to the ROUTES default.
    if path == "/api/character" and (event.get("queryStringParameters") or {}).get("date"):
        return handle_character(date=event["queryStringParameters"]["date"].strip())

    # Phase 4 historical window (2026-06-29): /api/vitals?date=YYYY-MM-DD — the
    # cockpit as of a past date. Dateless requests fall through to the ROUTES default.
    if path == "/api/vitals" and (event.get("queryStringParameters") or {}).get("date"):
        return handle_vitals(date=event["queryStringParameters"]["date"].strip())

    # Phase 1: Observatory week (GET with query params)
    if path == "/api/observatory_week":
        qs = event.get("queryStringParameters") or {}
        return handle_observatory_week(qs)

    # #399: Agents Showcase — roster + dated weekly Agent Activity feed, sourced
    # purely from existing watchdog artifacts (coherence-log/, ai-canary-log/,
    # remediation-log/). Read-only, content-filtered. Optional ?week=YYYY-MM-DD.
    if path == "/api/agent_activity":
        return handle_agent_activity(event)

    # BL-04: Field Notes (GET with optional ?week= query param)
    if path == "/api/field_notes":
        return handle_field_notes(event)
    if path == "/api/ai_analysis":
        return handle_ai_analysis(event)
    if path == "/api/coach_analysis":
        return handle_coach_analysis(event)
    # CC-01/02/10: Coaches-as-Characters roster + My Team + per-coach page (shaped-empty 200s)
    if path == "/api/coaches":
        return handle_coaches(event)
    if path == "/api/coach_team":
        return handle_coach_team(event)
    if path == "/api/panel_ledger":
        return handle_panel_ledger(event)
    if path.startswith("/api/coach/"):
        return handle_coach(event)
    if path == "/api/coaching-dashboard":
        try:
            _cd_coach_display = {
                "sleep": {
                    "coach_id": "sleep",
                    "name": "Dr. Lisa Park",
                    "initials": "LP",
                    "title": "Sleep & Circadian Rhythm Specialist",
                    "color": "#818cf8",
                    "observatory_link": "/sleep/",
                },
                "nutrition": {
                    "coach_id": "nutrition",
                    "name": "Dr. Marcus Webb",
                    "initials": "MW",
                    "title": "Evidence-Based Nutrition",
                    "color": "#10b981",
                    "observatory_link": "/nutrition/",
                },
                "training": {
                    "coach_id": "training",
                    "name": "Dr. Sarah Chen",
                    "initials": "SC",
                    "title": "Exercise Physiology & Strength",
                    "color": "#3db88a",
                    "observatory_link": "/training/",
                },
                "mind": {
                    "coach_id": "mind",
                    "name": "Dr. Nathan Reeves",
                    "initials": "NR",
                    "title": "Psychiatrist — Behavioral Patterns",
                    "color": "#a78bfa",
                    "observatory_link": "/mind/",
                },
                "physical": {
                    "coach_id": "physical",
                    "name": "Dr. Victor Reyes",
                    "initials": "VR",
                    "title": "Longevity & Body Composition",
                    "color": "#f59e0b",
                    "observatory_link": "/physical/",
                },
                "glucose": {
                    "coach_id": "glucose",
                    "name": "Dr. Amara Patel",
                    "initials": "AP",
                    "title": "Metabolic Health & CGM",
                    "color": "#2dd4bf",
                    "observatory_link": "/glucose/",
                },
                "labs": {
                    "coach_id": "labs",
                    "name": "Dr. James Okafor",
                    "initials": "JO",
                    "title": "Clinical Pathology & Preventive Labs",
                    "color": "#5ba4cf",
                    "observatory_link": "/labs/",
                },
                "explorer": {
                    "coach_id": "explorer",
                    "name": "Dr. Henning Brandt",
                    "initials": "HB",
                    "title": "Biostatistics & N=1 Research",
                    "color": "#e879f9",
                    "observatory_link": "/explorer/",
                },
            }
            _cd_coach_id_map = {
                "sleep": "sleep_coach",
                "nutrition": "nutrition_coach",
                "training": "training_coach",
                "mind": "mind_coach",
                "physical": "physical_coach",
                "glucose": "glucose_coach",
                "labs": "labs_coach",
                "explorer": "explorer_coach",
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
                    **with_phase_filter(
                        {  # ADR-058: hide pilot coach actions
                            "KeyConditionExpression": Key("pk").eq(f"{USER_PREFIX}coach_actions"),
                            "Limit": 50,
                        }
                    )
                )
                for _act in _cd_act_resp.get("Items", []):
                    _act = _decimal_to_float(_act)
                    if _act.get("status") == "open":
                        _cd_actions.append(
                            {
                                "coach_id": _act.get("coach_id", ""),
                                "domain": _act.get("domain", ""),
                                "action_text": _act.get("action_text", _act.get("action", "")),
                                "issued_date": _act.get("issued_date", _act.get("sk", "").replace("DATE#", "")),
                                "status": "open",
                            }
                        )
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
                        **with_phase_filter(
                            {  # ADR-058: hide pilot coach outputs
                                "KeyConditionExpression": Key("pk").eq(_cd_coach_pk) & Key("sk").begins_with("OUTPUT#"),
                                "ScanIndexForward": False,
                                "Limit": 1,
                            }
                        )
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
                                    _cd_predictions.append(
                                        {
                                            "coach_id": _cd_domain,
                                            "text": _p.get("text", _p.get("prediction", "")),
                                            "confidence": _p.get("confidence", "medium"),
                                            "status": _p.get("status", "pending"),
                                            "date": _cd_out_item.get("sk", "").replace("OUTPUT#", ""),
                                        }
                                    )
                except Exception:
                    pass

                _cd_coaches.append(coach_entry)

            # Sort coaches: invested/concerned first, then neutral
            _ei_order = {"concerned": 0, "invested": 1, "curious": 2, "neutral": 3}
            _cd_coaches.sort(key=lambda c: _ei_order.get(c.get("emotional_investment", "neutral"), 3))

            # Limit predictions to 10 most recent
            _cd_predictions = _cd_predictions[-10:]

            return _ok(
                {
                    "weekly_priority": _cd_priority,
                    "open_actions": _cd_actions,
                    "coaches": _cd_coaches,
                    "predictions": _cd_predictions,
                },
                cache_seconds=300,
            )
        except Exception as _e:
            print(f"[WARN] /api/coaching-dashboard failed: {_e}")
            return _ok({"weekly_priority": {}, "open_actions": [], "coaches": [], "predictions": []}, cache_seconds=60)

    # Prediction Ledger (GET with query params)
    if path == "/api/predictions":
        return handle_predictions(event)
    if path == "/api/calibration":
        return handle_calibration(event)
    if path == "/api/voice_fidelity":
        return handle_voice_fidelity(event)
    if path == "/api/coach_timeline":
        return handle_coach_timeline(event)
    if path == "/api/weekly_priority":
        return handle_weekly_priority(event)
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
