"""
intelligence_common.py — Shared utilities for the Intelligence Layer V2.

Provides data inventory, data maturity, goals loading, and coach preamble
generation used by all content-producing Lambdas (observatory, daily brief,
weekly digest, chronicle, etc.).

Part of the shared Lambda layer — changes require layer rebuild.

v1.0.0 — 2026-04-07 (Intelligence Layer V2 Session 1)
"""

import json
import logging
import os
from datetime import datetime, timezone, timedelta
from decimal import Decimal

import boto3
from boto3.dynamodb.conditions import Key

logger = logging.getLogger(__name__)

TABLE_NAME = os.environ.get("TABLE_NAME", "life-platform")
S3_BUCKET = os.environ.get("S3_BUCKET", "matthew-life-platform")
USER_ID = os.environ.get("USER_ID", "matthew")
USER_PREFIX = f"USER#{USER_ID}#SOURCE#"

dynamodb = boto3.resource("dynamodb", region_name="us-west-2")
table = dynamodb.Table(TABLE_NAME)
s3 = boto3.client("s3", region_name="us-west-2")


def _decimal_to_float(obj):
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, dict):
        return {k: _decimal_to_float(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_decimal_to_float(i) for i in obj]
    return obj


# ══════════════════════════════════════════════════════════════════════════════
# DATA INVENTORY
# ══════════════════════════════════════════════════════════════════════════════

# Sources to inventory with their primary partition
_INVENTORY_SOURCES = [
    ("whoop", "whoop"),
    ("apple_health", "apple_health"),
    ("macrofactor", "macrofactor"),
    ("strava", "strava"),
    ("garmin", "garmin"),
    ("withings", "withings"),
    ("eightsleep", "eightsleep"),
    ("dexa", "dexa"),
    ("labs", "labs"),
    ("measurements", "measurements"),
    ("journal", "notion"),
    ("state_of_mind", "state_of_mind"),
    ("supplements", "supplements"),
    ("habitify", "habitify"),
    ("cgm", "apple_health"),  # CGM data stored in apple_health partition
]


def build_data_inventory() -> dict:
    """
    Query DynamoDB for existence and recency of all major data partitions.

    Returns dict of source → {exists, latest, records, days_of_data}.
    Used by data maturity, coach prompts, and the intelligence validator.
    """
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    d90 = (datetime.now(timezone.utc) - timedelta(days=90)).strftime("%Y-%m-%d")

    inventory = {}
    seen_partitions = set()

    for label, partition in _INVENTORY_SOURCES:
        if partition in seen_partitions and label != "cgm":
            # Avoid double-querying the same partition (except cgm which checks specific fields)
            if partition in inventory:
                inventory[label] = inventory.get(partition, {}).copy()
                continue
        seen_partitions.add(partition)

        try:
            pk = f"{USER_PREFIX}{partition}"
            # Count records in last 90 days
            resp = table.query(
                KeyConditionExpression=Key("pk").eq(pk) & Key("sk").between(
                    f"DATE#{d90}", f"DATE#{today}~"
                ),
                Select="COUNT",
            )
            count = resp.get("Count", 0)

            # Get latest record
            latest_resp = table.query(
                KeyConditionExpression=Key("pk").eq(pk) & Key("sk").begins_with("DATE#"),
                ScanIndexForward=False, Limit=1,
                ProjectionExpression="sk",
            )
            latest_items = latest_resp.get("Items", [])
            latest_date = None
            if latest_items:
                sk = latest_items[0].get("sk", "")
                latest_date = sk.replace("DATE#", "")[:10]

            # For CGM, check if blood_glucose_avg exists in apple_health records
            if label == "cgm":
                cgm_resp = table.query(
                    KeyConditionExpression=Key("pk").eq(pk) & Key("sk").between(
                        f"DATE#{d90}", f"DATE#{today}~"
                    ),
                    FilterExpression="attribute_exists(blood_glucose_avg)",
                    Select="COUNT",
                )
                count = cgm_resp.get("Count", 0)

            inventory[label] = {
                "exists": count > 0,
                "latest": latest_date,
                "records": count,
                "days_of_data": count,  # Approximation — 1 record per day
            }
        except Exception as e:
            logger.warning("Data inventory query failed for %s: %s", label, e)
            inventory[label] = {"exists": False, "latest": None, "records": 0, "days_of_data": 0}

    return inventory


# ══════════════════════════════════════════════════════════════════════════════
# DATA MATURITY
# ══════════════════════════════════════════════════════════════════════════════

# Phase thresholds per coach domain
_MATURITY_THRESHOLDS = {
    "sleep": {"orientation": 7, "established": 30, "source": "whoop", "unit": "nights"},
    "nutrition": {"orientation": 7, "established": 30, "source": "macrofactor", "unit": "days logged"},
    "training": {"orientation": 1, "established": 14, "source": "strava", "unit": "workouts"},
    "glucose": {"orientation": 7, "established": 30, "source": "cgm", "unit": "CGM days"},
    "physical": {"orientation": 7, "established": 30, "source": "withings", "unit": "weight readings",
                  "composite": True, "requires_dexa": True},
    "mind": {"orientation": 3, "established": 14, "source": "journal", "unit": "journal entries"},
    "labs": {"orientation": 1, "established": 3, "source": "labs", "unit": "blood draws"},
    "explorer": {"orientation": 14, "established": 60, "source": "whoop", "unit": "days platform data"},
}

# Voice templates per phase
ORIENTATION_VOICE = (
    "You are in ORIENTATION mode. You have {days} {unit} of data. "
    "Your minimum for meaningful analysis is {threshold} {unit}.\n\n"
    "Voice rules:\n"
    "- Open with: \"I'm {name}, and I'll be watching your {domain} data. Here's what I track and what I'm looking for.\"\n"
    "- List 2-3 specific things you're watching for as data accumulates\n"
    "- Name exactly what data you have and what's missing\n"
    "- Do NOT make analytical claims, trend statements, or recommendations\n"
    "- End with: \"I'll have more to say around {target_date}.\"\n"
    "- Tone: professional introduction, not apology for lack of data\n"
)

EMERGING_VOICE = (
    "You are in EMERGING mode. You have {days} {unit} of data. "
    "Patterns are starting to form but confidence is low.\n\n"
    "Voice rules:\n"
    "- You may note preliminary patterns with explicit confidence caveats\n"
    "- Use language: \"An early signal suggests...\", \"I'm watching whether...\"\n"
    "- Do NOT use definitive language like \"your pattern is\" or \"this shows\"\n"
    "- Actions should be data-gathering, not behavior-changing\n"
    "- Tone: curious investigator, not confident advisor\n"
)

ESTABLISHED_VOICE = "You are in ESTABLISHED mode with {days} {unit} of data. Full analytical voice."


def build_data_maturity(inventory: dict) -> dict:
    """
    Calculate data maturity per domain based on inventory record counts.

    Returns dict of domain → {days, phase, threshold, established_at, unit, voice_template}.
    """
    today = datetime.now(timezone.utc)
    maturity = {}

    for domain, thresholds in _MATURITY_THRESHOLDS.items():
        source = thresholds["source"]
        src_data = inventory.get(source, {})
        days = src_data.get("days_of_data", 0)
        unit = thresholds["unit"]

        orientation_threshold = thresholds["orientation"]
        established_threshold = thresholds["established"]

        # Physical coach: composite check — needs DEXA + weight series
        if thresholds.get("composite") and thresholds.get("requires_dexa"):
            dexa_data = inventory.get("dexa", {})
            has_dexa = dexa_data.get("exists", False)
            if not has_dexa and days < orientation_threshold:
                phase = "orientation"
            elif has_dexa and days >= orientation_threshold:
                phase = "emerging" if days < established_threshold else "established"
            else:
                phase = "orientation"
            target_date = (today + timedelta(days=max(0, orientation_threshold - days))).strftime("%B %d") if phase == "orientation" else None
        elif days < orientation_threshold:
            phase = "orientation"
            target_date = (today + timedelta(days=max(0, orientation_threshold - days))).strftime("%B %d")
        elif days < established_threshold:
            phase = "emerging"
            target_date = None
        else:
            phase = "established"
            target_date = None

        maturity[domain] = {
            "days": days,
            "phase": phase,
            "threshold": orientation_threshold,
            "established_at": established_threshold,
            "unit": unit,
            "target_date": target_date,
        }

    return maturity


# ══════════════════════════════════════════════════════════════════════════════
# GOALS LOADER
# ══════════════════════════════════════════════════════════════════════════════

_goals_cache = None
_goals_cache_ts = 0
_GOALS_CACHE_TTL = 300  # 5 minutes


def load_goals_config() -> dict:
    """Load user goals from S3. Cached in memory for Lambda warm instances."""
    global _goals_cache, _goals_cache_ts
    import time
    now = time.time()

    if _goals_cache and (now - _goals_cache_ts) < _GOALS_CACHE_TTL:
        return _goals_cache

    try:
        resp = s3.get_object(Bucket=S3_BUCKET, Key="config/user_goals.json")
        _goals_cache = json.loads(resp["Body"].read())
        _goals_cache_ts = now
        return _goals_cache
    except Exception as e:
        logger.warning("Failed to load goals config: %s — using defaults", e)
        return {
            "mission": "12-month body recomposition for longevity",
            "start_date": "2026-04-01",
            "start_weight_lbs": 307,
            "targets": {},
            "philosophy": "",
            "known_constraints": [],
            "coach_briefing": "No goals configuration found.",
        }


# ══════════════════════════════════════════════════════════════════════════════
# COACH PREAMBLE BUILDER
# ══════════════════════════════════════════════════════════════════════════════

def build_coach_preamble(coach_name: str, domain: str, goals: dict,
                         inventory: dict, maturity: dict,
                         action_history: list = None) -> str:
    """
    Build the standard context preamble injected into every coach prompt.

    This is the single source of truth for coach context — ensures every coach
    (observatory, daily brief, weekly digest) gets the same foundational info.
    """
    parts = []

    # 1. First-person voice directive
    parts.append(
        f"VOICE: Write in FIRST PERSON. You ARE {coach_name}. "
        f"Say \"I\" not \"{coach_name}\". Address Matthew directly as \"you\". "
        f"Never refer to yourself in third person.\n"
    )

    # 2. Goals context
    briefing = goals.get("coach_briefing", "")
    if briefing:
        parts.append(f"MATTHEW'S CONTEXT:\n{briefing}\n")

    targets = goals.get("targets", {})
    target_lines = []
    _target_map = {
        "weight.goal_lbs": "Weight goal",
        "body_composition.goal_body_fat_pct": "Body fat goal",
        "training.weekly_sessions_target": "Training sessions/week",
        "nutrition.daily_calories_target": "Calorie target",
        "nutrition.daily_protein_min_g": "Protein minimum",
        "biomarkers.hrv_target_ms": "HRV target",
    }
    for path, label in _target_map.items():
        keys = path.split(".")
        val = targets
        for k in keys:
            val = val.get(k) if isinstance(val, dict) else None
            if val is None:
                break
        target_lines.append(f"  - {label}: {val if val is not None else 'not yet set'}")
    parts.append("DEFINED TARGETS:\n" + "\n".join(target_lines) + "\n")

    constraints = goals.get("known_constraints", [])
    if constraints:
        parts.append("KNOWN CONSTRAINTS:\n" + "\n".join(f"  - {c}" for c in constraints) + "\n")

    # 3. Data maturity + phase voice template
    domain_maturity = maturity.get(domain, {})
    phase = domain_maturity.get("phase", "orientation")
    days = domain_maturity.get("days", 0)
    unit = domain_maturity.get("unit", "days")
    threshold = domain_maturity.get("threshold", 7)
    target_date = domain_maturity.get("target_date", "")

    if phase == "orientation":
        voice_tmpl = ORIENTATION_VOICE.format(
            days=days, unit=unit, threshold=threshold,
            name=coach_name, domain=domain, target_date=target_date or "soon",
        )
    elif phase == "emerging":
        voice_tmpl = EMERGING_VOICE.format(days=days, unit=unit)
    else:
        voice_tmpl = ESTABLISHED_VOICE.format(days=days, unit=unit)

    parts.append(f"DATA MATURITY STATUS:\nPhase: {phase} ({days} {unit} of data, threshold: {threshold})\n{voice_tmpl}\n")

    # 4. Data inventory
    inventory_lines = []
    for src, info in sorted(inventory.items()):
        if info.get("exists"):
            latest = info.get("latest", "?")
            count = info.get("records", 0)
            inventory_lines.append(f"  - {src}: AVAILABLE ({count} records, latest: {latest})")
        else:
            inventory_lines.append(f"  - {src}: not available")
    parts.append("DATA SOURCES:\n" + "\n".join(inventory_lines) + "\n")

    # 5. Data interpretation rules
    parts.append(
        "DATA INTERPRETATION RULES:\n"
        "- If an activity count or log is ZERO, that means Matthew hasn't done that activity — "
        "say \"no training logged\" NOT \"provide your training data\"\n"
        "- If a data source exists but values are null for today, use the most recent available data\n"
        "- NEVER tell Matthew to \"obtain\" or \"get\" a scan/test if the data already exists above\n"
        "- Garmin is the step count source of truth (wearable). Ignore Apple Health step counts if Garmin data is available.\n"
        "- If a target is \"not yet set\", do NOT invent one. You may suggest one with reasoning.\n"
    )

    # 6. Action history (if provided)
    if action_history:
        action_lines = []
        for action in action_history[:5]:
            status = action.get("status", "open")
            text = action.get("action_text", "")
            week = action.get("issued_week", "")
            action_lines.append(f"  - [{week}] \"{text}\" — STATUS: {status.upper()}")
        parts.append("YOUR PREVIOUS ACTIONS:\n" + "\n".join(action_lines) + "\n")

    return "\n".join(parts)


# ══════════════════════════════════════════════════════════════════════════════
# INTELLIGENCE VALIDATOR (Workstream 4)
# ══════════════════════════════════════════════════════════════════════════════

# Phrases indicating a coach claims data is missing
_NULL_CLAIM_PHRASES = [
    "unavailable", "not yet available", "remains unknown", "data gap",
    "cannot determine", "no data", "data is null", "not available",
    "remains null", "awaiting data", "hasn't been provided",
    "provide your", "obtain a", "get a scan", "submit your",
    "share your", "we don't have",
]

# Mapping from claim domain keywords to inventory sources
_CLAIM_DOMAIN_MAP = {
    "body composition": ["dexa", "withings"],
    "dexa": ["dexa"],
    "lean mass": ["dexa"],
    "visceral fat": ["dexa"],
    "body fat": ["dexa"],
    "weight": ["withings"],
    "meal timing": ["macrofactor"],
    "food log": ["macrofactor"],
    "nutrition": ["macrofactor"],
    "calorie": ["macrofactor"],
    "protein": ["macrofactor"],
    "training": ["strava"],
    "workout": ["strava"],
    "exercise": ["strava"],
    "glucose": ["cgm"],
    "cgm": ["cgm"],
    "blood sugar": ["cgm"],
    "sleep": ["whoop", "eightsleep"],
    "hrv": ["whoop"],
    "recovery": ["whoop"],
    "journal": ["journal"],
    "lab": ["labs"],
    "bloodwork": ["labs"],
    "biomarker": ["labs"],
}

# SOT definitions — which source is authoritative for each metric
_SOURCE_OF_TRUTH = {
    "steps": "garmin",
    "weight": "withings",
    "sleep_duration": "whoop",
    "recovery": "whoop",
    "hrv": "whoop",
    "glucose": "cgm",
    "calories": "macrofactor",
    "protein": "macrofactor",
}


def validate_coach_output(coach_id: str, domain: str, narrative: str,
                          inventory: dict, maturity: dict,
                          all_narratives: dict = None) -> list:
    """
    Run all validation checks against a coach narrative.

    Returns list of flag dicts: {check, severity, detail, source_text}.
    """
    import re
    flags = []
    text_lower = narrative.lower()

    # ── Check 1: Null claim vs actual data ─────────────────────────────
    for phrase in _NULL_CLAIM_PHRASES:
        if phrase in text_lower:
            # Find the surrounding context (±50 chars)
            idx = text_lower.index(phrase)
            context = narrative[max(0, idx - 50):idx + len(phrase) + 50]

            # Determine which domain the claim references
            for domain_kw, sources in _CLAIM_DOMAIN_MAP.items():
                if domain_kw in context.lower():
                    # Check if any of these sources actually have data
                    for src in sources:
                        src_info = inventory.get(src, {})
                        if src_info.get("exists") and src_info.get("records", 0) > 0:
                            flags.append({
                                "check": "null_claim_vs_data",
                                "severity": "error",
                                "detail": (
                                    f"Coach claims '{domain_kw}' data is unavailable "
                                    f"but {src} has {src_info['records']} records "
                                    f"(latest: {src_info.get('latest', '?')})"
                                ),
                                "source_text": context.strip(),
                            })
                            break

    # ── Check 2: Stale action — asking for data that exists ───────────
    action_phrases = [
        "obtain a", "get a", "schedule a", "request a",
        "provide your", "submit your", "share your",
        "start logging", "begin tracking",
    ]
    for phrase in action_phrases:
        if phrase in text_lower:
            idx = text_lower.index(phrase)
            context = narrative[idx:idx + 80].lower()
            for domain_kw, sources in _CLAIM_DOMAIN_MAP.items():
                if domain_kw in context:
                    for src in sources:
                        if inventory.get(src, {}).get("exists"):
                            flags.append({
                                "check": "stale_action",
                                "severity": "error",
                                "detail": (
                                    f"Coach suggests obtaining/providing '{domain_kw}' "
                                    f"but {src} data already exists"
                                ),
                                "source_text": narrative[idx:idx + 80].strip(),
                            })
                            break

    # ── Check 3: SOT violation ────────────────────────────────────────
    # Check for step count discrepancies
    step_match = re.search(r'(\d[,\d]*)\s*steps?', narrative)
    if step_match:
        cited_steps = int(step_match.group(1).replace(",", ""))
        garmin_data = inventory.get("garmin", {})
        apple_data = inventory.get("apple_health", {})
        if garmin_data.get("exists") and apple_data.get("exists"):
            # If steps cited and both sources exist, flag if it might be from wrong source
            # (We can't know the exact value without querying, but we flag the presence)
            pass  # Requires actual metric values — deferred to full implementation

    # ── Check 4: Cross-coach contradiction ────────────────────────────
    if all_narratives:
        # Extract numeric claims from this narrative
        this_numbers = set(re.findall(r'\b\d+(?:\.\d+)?\s*(?:mg/dL|bpm|ms|lbs?|%|kcal|g)\b', narrative))
        for other_domain, other_text in all_narratives.items():
            if other_domain == domain:
                continue
            other_numbers = set(re.findall(r'\b\d+(?:\.\d+)?\s*(?:mg/dL|bpm|ms|lbs?|%|kcal|g)\b', other_text))
            # Find numbers that appear in both but with different values for same unit
            # This is a simplified check — full implementation would parse metric+value pairs
            for num in this_numbers:
                unit = re.search(r'[a-zA-Z/%]+$', num)
                if unit:
                    unit_str = unit.group()
                    for other_num in other_numbers:
                        if other_num.endswith(unit_str) and other_num != num:
                            # Different value, same unit — potential contradiction
                            flags.append({
                                "check": "cross_coach_contradiction",
                                "severity": "warning",
                                "detail": f"This coach cites {num}, {other_domain} coach cites {other_num}",
                                "source_text": num,
                            })

    # ── Check 5: Overconfidence without data ──────────────────────────
    domain_maturity = maturity.get(domain, {})
    phase = domain_maturity.get("phase", "orientation")
    if phase == "orientation":
        confident_phrases = [
            "your pattern shows", "this demonstrates", "clearly indicates",
            "the data confirms", "we can see that", "it's clear that",
            "definitively", "without question", "conclusively",
        ]
        for phrase in confident_phrases:
            if phrase in text_lower:
                flags.append({
                    "check": "overconfidence",
                    "severity": "warning",
                    "detail": (
                        f"Coach uses definitive language '{phrase}' "
                        f"but is in {phase} phase ({domain_maturity.get('days', 0)} "
                        f"{domain_maturity.get('unit', 'days')} of data)"
                    ),
                    "source_text": phrase,
                })

    return flags


def write_quality_results(date: str, coach_id: str, domain: str, flags: list):
    """Write validation results to SOURCE#intelligence_quality DDB partition."""
    errors = sum(1 for f in flags if f["severity"] == "error")
    warnings = sum(1 for f in flags if f["severity"] == "warning")

    item = {
        "pk": f"USER#{USER_ID}",
        "sk": f"SOURCE#intelligence_quality#{date}#{coach_id}",
        "date": date,
        "coach_id": coach_id,
        "domain": domain,
        "checks_run": 5,
        "errors": errors,
        "warnings": warnings,
        "flags": flags,
        "validated_at": datetime.now(timezone.utc).isoformat(),
    }

    try:
        # Convert floats to Decimal for DynamoDB
        clean = json.loads(json.dumps(item, default=str), parse_float=Decimal)
        table.put_item(Item=clean)
        logger.info("Quality results written: %s/%s — %d errors, %d warnings",
                     coach_id, date, errors, warnings)
    except Exception as e:
        logger.error("Failed to write quality results: %s", e)
