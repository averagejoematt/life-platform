"""
coach_observatory_renderer.py — Coach Intelligence: Observatory Card Renderer

Pure DynamoDB reader + JSON assembler for observatory page coaching cards.
NO LLM calls — reads pre-computed coach state and assembles display-ready JSON
payloads for the frontend.

Supports two modes:
  1. Single domain:  event = {"domain": "sleep"}
  2. All coaches:    event = {"all": true}  (returns all 8 cards)

DynamoDB read patterns:
  PK=COACH#{coach_id}  SK begins_with OUTPUT#       (latest output)
  PK=COACH#{coach_id}  SK begins_with THREAD#       (open threads)
  PK=COACH#{coach_id}  SK=RELATIONSHIP#state        (rapport/phase)
  PK=COACH#{coach_id}  SK begins_with LEARNING#     (revision signals)
  PK=ENSEMBLE#digest   SK begins_with CYCLE#        (cross-coach refs)
  PK=COACH#computation SK begins_with RESULTS#      (statistical guardrails)

Schedule: Invoked by site-api or directly via API Gateway / Step Functions.

v1.0.0 — 2026-04-06 (Coach Intelligence)
"""

import json
import logging
import os
from datetime import datetime, timezone
from decimal import Decimal

import boto3
from boto3.dynamodb.conditions import Key

# ── Structured logger ────────────────────────────────────────────────────────
try:
    from platform_logger import get_logger
    logger = get_logger("coach-observatory-renderer")
except ImportError:
    logger = logging.getLogger("coach-observatory-renderer")
    logger.setLevel(logging.INFO)

# ══════════════════════════════════════════════════════════════════════════════
# CONFIGURATION
# ══════════════════════════════════════════════════════════════════════════════

REGION = os.environ.get("AWS_REGION", "us-west-2")
TABLE_NAME = os.environ.get("TABLE_NAME", "life-platform")
USER_ID = os.environ.get("USER_ID", "matthew")

EXPERIMENT_START = "2026-04-01"

# AWS clients
dynamodb = boto3.resource("dynamodb", region_name=REGION)
table = dynamodb.Table(TABLE_NAME)

# ══════════════════════════════════════════════════════════════════════════════
# DOMAIN / COACH MAPPING
# ══════════════════════════════════════════════════════════════════════════════

DOMAIN_COACH_MAP = {
    "sleep": "sleep_coach",
    "nutrition": "nutrition_coach",
    "training": "training_coach",
    "mind": "mind_coach",
    "physical": "physical_coach",
    "glucose": "glucose_coach",
    "labs": "labs_coach",
    "explorer": "explorer_coach",
}

COACH_DISPLAY = {
    "sleep_coach": {
        "name": "Dr. Lisa Park",
        "initials": "LP",
        "title": "Sleep & Circadian Rhythm Specialist",
        "color": "#818cf8",
    },
    "nutrition_coach": {
        "name": "Dr. Marcus Webb",
        "initials": "MW",
        "title": "Evidence-Based Nutrition",
        "color": "#10b981",
    },
    "training_coach": {
        "name": "Dr. Sarah Chen",
        "initials": "SC",
        "title": "Exercise Physiology & Strength",
        "color": "#3db88a",
    },
    "mind_coach": {
        "name": "Dr. Nathan Reeves",
        "initials": "NR",
        "title": "Psychiatrist — Behavioral Patterns",
        "color": "#a78bfa",
    },
    "physical_coach": {
        "name": "Dr. Victor Reyes",
        "initials": "VR",
        "title": "Longevity & Body Composition",
        "color": "#f59e0b",
    },
    "glucose_coach": {
        "name": "Dr. Amara Patel",
        "initials": "AP",
        "title": "Metabolic Health & CGM",
        "color": "#2dd4bf",
    },
    "labs_coach": {
        "name": "Dr. James Okafor",
        "initials": "JO",
        "title": "Clinical Pathology & Preventive Labs",
        "color": "#5ba4cf",
    },
    "explorer_coach": {
        "name": "Dr. Henning Brandt",
        "initials": "HB",
        "title": "Biostatistics & N=1 Research",
        "color": "#e879f9",
    },
}

# Domain → source mapping for statistical guardrails lookup
DOMAIN_SOURCE_MAP = {
    "sleep": "whoop",
    "nutrition": "macrofactor",
    "training": "strava",
    "mind": "apple_health",
    "physical": "withings",
    "glucose": "apple_health",
    "labs": "apple_health",
    "explorer": "whoop",
}


# ══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def _decimal_to_float(obj):
    """Recursively convert DynamoDB Decimal values to Python float."""
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, dict):
        return {k: _decimal_to_float(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_decimal_to_float(v) for v in obj]
    return obj


def _confidence_to_language(confidence_float):
    """Map a numeric confidence score to human-readable language tier."""
    if confidence_float is None:
        return "preliminary"
    if confidence_float >= 0.85:
        return "highly_confident"
    if confidence_float >= 0.7:
        return "fairly_confident"
    if confidence_float >= 0.5:
        return "moderate"
    if confidence_float >= 0.3:
        return "preliminary"
    return "uncertain"


def _get_item(pk, sk):
    """Get a single DynamoDB item. Returns None if not found or on error."""
    try:
        resp = table.get_item(Key={"pk": pk, "sk": sk})
        item = resp.get("Item")
        return _decimal_to_float(item) if item else None
    except Exception as e:
        logger.warning("get_item(%s, %s) failed: %s", pk, sk, e)
        return None


def _query_begins_with(pk, sk_prefix, scan_forward=True, limit=None):
    """Query DynamoDB for items with SK beginning with a prefix."""
    try:
        kwargs = {
            "KeyConditionExpression": Key("pk").eq(pk) & Key("sk").begins_with(sk_prefix),
            "ScanIndexForward": scan_forward,
        }
        if limit:
            kwargs["Limit"] = limit

        items = []
        while True:
            resp = table.query(**kwargs)
            items.extend(resp.get("Items", []))
            # If we have a limit and have enough items, stop paginating
            if limit and len(items) >= limit:
                items = items[:limit]
                break
            if "LastEvaluatedKey" not in resp:
                break
            kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]

        return _decimal_to_float(items)
    except Exception as e:
        logger.warning("query_begins_with(%s, %s) failed: %s", pk, sk_prefix, e)
        return []


def _compute_experiment_timing():
    """Compute current week number and days in experiment."""
    try:
        start = datetime.strptime(EXPERIMENT_START, "%Y-%m-%d").date()
        today = datetime.now(timezone.utc).date()
        days_in = max(1, (today - start).days + 1)
        week_number = max(1, (days_in - 1) // 7 + 1)
        return week_number, days_in
    except Exception:
        return 1, 1


# ══════════════════════════════════════════════════════════════════════════════
# CARD ASSEMBLY — SINGLE COACH
# ══════════════════════════════════════════════════════════════════════════════

def _render_coach_card(domain, include_threads=True):
    """Assemble the observatory card payload for a single domain/coach.

    Reads all relevant DynamoDB records and assembles a display-ready JSON
    object. Returns a graceful fallback if no OUTPUT# record exists.
    """
    coach_id = DOMAIN_COACH_MAP.get(domain)
    if not coach_id:
        logger.warning("Unknown domain requested: %s", domain)
        return {"domain": domain, "analysis": None, "error": "unknown_domain"}

    coach_pk = f"COACH#{coach_id}"
    display = COACH_DISPLAY.get(coach_id, {})

    # ── 1. Latest OUTPUT# record ────────────────────────────────────────────
    outputs = _query_begins_with(
        coach_pk, "OUTPUT#",
        scan_forward=False,
        limit=1,
    )

    if not outputs:
        logger.info("No OUTPUT# record for %s — returning empty card", coach_id)
        return {
            "coach_id": coach_id,
            "domain": domain,
            "analysis": None,
        }

    output = outputs[0]

    # Prefer observatory_summary over full content if available
    analysis = output.get("observatory_summary") or output.get("content")
    generated_at = output.get("created_at") or output.get("generated_at")
    themes = output.get("themes", [])
    key_recommendation = output.get("key_recommendation")
    elena_quote = output.get("elena_quote")
    journaling_prompt = output.get("journaling_prompt")

    # ── 2. Open threads ─────────────────────────────────────────────────────
    thread_reference = None
    if include_threads:
        all_threads = _query_begins_with(coach_pk, "THREAD#")
        open_threads = [t for t in all_threads if t.get("status") == "open"]

        if open_threads:
            # Pick the most recently referenced thread (highest reference_count
            # or most recent last_referenced timestamp)
            open_threads.sort(
                key=lambda t: (
                    t.get("reference_count", 0),
                    t.get("last_referenced", ""),
                ),
                reverse=True,
            )
            best = open_threads[0]
            thread_reference = best.get("summary") or best.get("topic") or best.get("sk", "")

    # ── 3. RELATIONSHIP#state ────────────────────────────────────────────────
    relationship = _get_item(coach_pk, "RELATIONSHIP#state")
    journey_phase = None
    rapport_level = None
    if relationship:
        journey_phase = relationship.get("journey_phase")
        rapport_level = relationship.get("rapport_level")

    # ── 4. Ensemble digest — cross-coach references ─────────────────────────
    cross_coach_reference = None
    digest_records = _query_begins_with(
        "ENSEMBLE#digest", "CYCLE#",
        scan_forward=False,
        limit=1,
    )

    if digest_records:
        digest = digest_records[0]
        # Search coach_summaries and active_disagreements for cross-coach refs
        # involving this coach's domain
        _extract_cross_coach_ref(digest, coach_id, domain)

        # Check active disagreements involving this coach
        disagreements = digest.get("active_disagreements", [])
        if isinstance(disagreements, str):
            try:
                disagreements = json.loads(disagreements)
            except (json.JSONDecodeError, TypeError):
                disagreements = []

        for d in disagreements:
            coaches_involved = d.get("coaches", [])
            if coach_id in coaches_involved:
                other_coaches = [c for c in coaches_involved if c != coach_id]
                topic = d.get("topic", "")
                if topic and other_coaches:
                    other_names = []
                    for oc in other_coaches:
                        oc_display = COACH_DISPLAY.get(oc, {})
                        other_names.append(
                            oc_display.get("name", oc.replace("_", " ").title())
                        )
                    cross_coach_reference = (
                        f"{', '.join(other_names)}'s notes on {topic}"
                    )
                    break

        # Also check coach_summaries for wants_team_input_on
        if not cross_coach_reference:
            summaries = digest.get("coach_summaries", [])
            if isinstance(summaries, str):
                try:
                    summaries = json.loads(summaries)
                except (json.JSONDecodeError, TypeError):
                    summaries = []

            for summary in summaries:
                if summary.get("coach_id") == coach_id:
                    team_input = summary.get("wants_team_input_on", [])
                    if team_input:
                        cross_coach_reference = (
                            f"Requesting team input on: {team_input[0]}"
                        )
                    break

    # ── 5. Computation results — data availability / guardrails ──────────────
    data_availability = None
    confidence_language = "preliminary"

    comp_results = _query_begins_with(
        "COACH#computation", "RESULTS#",
        scan_forward=False,
        limit=1,
    )

    if comp_results:
        result = comp_results[0]
        # statistical_guardrails is stored as JSON string
        guardrails_raw = result.get("statistical_guardrails", "{}")
        if isinstance(guardrails_raw, str):
            try:
                guardrails = json.loads(guardrails_raw)
            except (json.JSONDecodeError, TypeError):
                guardrails = {}
        else:
            guardrails = guardrails_raw

        # Find the guardrail level for this domain's primary source
        source = DOMAIN_SOURCE_MAP.get(domain)
        if source and source in guardrails:
            source_guardrails = guardrails[source]
            # Determine the overall level for this source — use the most
            # conservative (lowest) level across its metrics
            levels = []
            for metric_info in source_guardrails.values():
                if isinstance(metric_info, dict):
                    levels.append(metric_info.get("level", "observational_only"))

            if levels:
                # Priority: observational_only < preliminary < established
                level_order = {
                    "observational_only": 0,
                    "preliminary": 1,
                    "established": 2,
                }
                data_availability = min(
                    levels,
                    key=lambda lvl: level_order.get(lvl, 0),
                )

    # Read confidence from CONFIDENCE# records for this coach
    confidence_records = _query_begins_with(coach_pk, "CONFIDENCE#")
    if confidence_records:
        # Average across subdomains for a single confidence language
        conf_values = []
        for rec in confidence_records:
            alpha = rec.get("alpha", 1)
            beta_val = rec.get("beta", 1)
            if alpha is not None and beta_val is not None:
                try:
                    mean_conf = float(alpha) / (float(alpha) + float(beta_val))
                    conf_values.append(mean_conf)
                except (TypeError, ValueError, ZeroDivisionError):
                    pass
        if conf_values:
            avg_conf = sum(conf_values) / len(conf_values)
            confidence_language = _confidence_to_language(avg_conf)

    # ── 6. Revision signals ──────────────────────────────────────────────────
    revision_signal = None
    learning_records = _query_begins_with(
        coach_pk, "LEARNING#",
        scan_forward=False,
        limit=3,
    )

    for rec in learning_records:
        rec_type = rec.get("type") or rec.get("evaluation_type", "")
        if rec_type == "position_revision":
            # Build a natural-language revision signal
            rev_date = rec.get("date", "")
            reason = rec.get("reason") or rec.get("summary", "")
            if rev_date:
                try:
                    dt = datetime.strptime(rev_date, "%Y-%m-%d")
                    formatted = dt.strftime("%B %d").replace(" 0", " ")
                    revision_signal = f"Updated from my {formatted} assessment"
                    if reason:
                        revision_signal += f" — {reason}"
                except ValueError:
                    revision_signal = f"Updated from {rev_date} assessment"
            else:
                revision_signal = "Recently revised position"
            break

    # ── 7. Assemble the card ─────────────────────────────────────────────────
    week_number, days_in_experiment = _compute_experiment_timing()

    card = {
        "coach_id": coach_id,
        "coach_name": display.get("name", coach_id),
        "coach_initials": display.get("initials", ""),
        "coach_title": display.get("title", ""),
        "coach_color": display.get("color", "#6b7280"),
        "domain": domain,
        "analysis": analysis,
        "themes": themes if themes else [],
        "key_recommendation": key_recommendation,
        "elena_quote": elena_quote,
        "journaling_prompt": journaling_prompt,
        "thread_reference": thread_reference,
        "revision_signal": revision_signal,
        "cross_coach_reference": cross_coach_reference,
        "confidence_language": confidence_language,
        "data_availability": data_availability,
        "journey_phase": journey_phase,
        "rapport_level": rapport_level,
        "generated_at": generated_at,
        "week_number": week_number,
        "days_in_experiment": days_in_experiment,
    }

    # Strip None values for cleaner JSON output
    card = {k: v for k, v in card.items() if v is not None}

    logger.info(
        "Rendered card for %s (%s) — %d fields, analysis=%d chars",
        coach_id, domain, len(card),
        len(analysis) if analysis else 0,
    )

    return card


def _extract_cross_coach_ref(digest, coach_id, domain):
    """Extract cross-coach references from ensemble digest for this coach.

    This is a helper that searches the digest structure for references
    involving this coach. The actual cross_coach_reference is set in the
    caller based on disagreements and team_input — this method is a
    no-op placeholder for future enrichment of the digest search.
    """
    # Currently handled inline in _render_coach_card via disagreements
    # and wants_team_input_on. This method exists as a named extension
    # point for richer cross-coach reference extraction in future phases.
    pass


# ══════════════════════════════════════════════════════════════════════════════
# HANDLER
# ══════════════════════════════════════════════════════════════════════════════

def lambda_handler(event, context):
    """Lambda handler — renders observatory coaching cards.

    Event parameters:
      domain (str):           Required for single-coach mode (e.g. "sleep")
      all (bool):             If true, render all 8 coaches
      include_threads (bool): Include thread references (default true)

    Returns:
      Single card dict or {"coaches": [...]} for all mode.
      Always returns statusCode 200 for graceful degradation.
    """
    try:
        # Support both direct invocation and API Gateway proxy events
        if "body" in event and isinstance(event.get("body"), str):
            try:
                body = json.loads(event["body"])
            except (json.JSONDecodeError, TypeError):
                body = {}
        else:
            body = event

        # Also check queryStringParameters for API Gateway GET requests
        query_params = event.get("queryStringParameters") or {}

        all_mode = (
            body.get("all", False)
            or str(query_params.get("all", "")).lower() in ("true", "1", "yes")
        )
        include_threads = body.get("include_threads", True)
        if "include_threads" in query_params:
            include_threads = str(query_params["include_threads"]).lower() not in ("false", "0", "no")

        if all_mode:
            logger.info("Rendering all %d coach cards", len(DOMAIN_COACH_MAP))
            coaches = []
            for domain in DOMAIN_COACH_MAP:
                try:
                    card = _render_coach_card(domain, include_threads=include_threads)
                    coaches.append(card)
                except Exception as e:
                    logger.error("Failed to render card for %s: %s", domain, e)
                    coach_id = DOMAIN_COACH_MAP.get(domain, domain)
                    coaches.append({
                        "coach_id": coach_id,
                        "domain": domain,
                        "analysis": None,
                    })

            result = {"coaches": coaches}
            logger.info("Rendered %d coach cards (all mode)", len(coaches))

            return {
                "statusCode": 200,
                "headers": {
                    "Content-Type": "application/json",
                    "Access-Control-Allow-Origin": "*",
                },
                "body": json.dumps(result, default=str),
            }

        # Single domain mode
        domain = body.get("domain") or query_params.get("domain")

        if not domain:
            logger.warning("No domain specified in event")
            return {
                "statusCode": 200,
                "headers": {
                    "Content-Type": "application/json",
                    "Access-Control-Allow-Origin": "*",
                },
                "body": json.dumps({
                    "error": "domain parameter required",
                    "valid_domains": list(DOMAIN_COACH_MAP.keys()),
                }),
            }

        domain = domain.lower().strip()
        if domain not in DOMAIN_COACH_MAP:
            logger.warning("Invalid domain: %s", domain)
            return {
                "statusCode": 200,
                "headers": {
                    "Content-Type": "application/json",
                    "Access-Control-Allow-Origin": "*",
                },
                "body": json.dumps({
                    "error": f"unknown domain: {domain}",
                    "valid_domains": list(DOMAIN_COACH_MAP.keys()),
                }),
            }

        card = _render_coach_card(domain, include_threads=include_threads)

        return {
            "statusCode": 200,
            "headers": {
                "Content-Type": "application/json",
                "Access-Control-Allow-Origin": "*",
            },
            "body": json.dumps(card, default=str),
        }

    except Exception as e:
        logger.error("Unhandled error in observatory renderer: %s", e, exc_info=True)
        return {
            "statusCode": 200,
            "headers": {
                "Content-Type": "application/json",
                "Access-Control-Allow-Origin": "*",
            },
            "body": json.dumps({
                "error": "internal_error",
                "message": str(e),
            }),
        }
