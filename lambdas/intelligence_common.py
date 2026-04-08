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
import re
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

    # 6. Credibility score (V2.2)
    try:
        _cred = load_credibility(domain)
        _cred_label = _cred.get("label", "nascent")
        _cred_accuracy = _cred.get("accuracy_pct", 0)
        _cred_resolved = _cred.get("predictions_resolved", 0)
        _cred_calibration = _cred.get("calibration", "insufficient_data")
        parts.append(
            f"YOUR CREDIBILITY:\n"
            f"Track record: {_cred_label} ({_cred_resolved} predictions resolved, {_cred_accuracy}% accuracy)\n"
            f"Calibration: {_cred_calibration}\n"
        )
        if _cred_calibration == "over-confident":
            parts.append(
                "NOTE: Your high-confidence predictions have been wrong frequently. "
                "Consider being more measured in your confidence levels.\n"
            )
    except Exception:
        pass

    # 7. Action history (if provided)
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


# ══════════════════════════════════════════════════════════════════════════════
# ACTION COMPLETION LOOP (Workstream 3)
# ══════════════════════════════════════════════════════════════════════════════

# Cache for detection rules
_detection_rules_cache = None
_detection_rules_cache_ts = 0
_DETECTION_RULES_CACHE_TTL = 300  # 5 minutes


def _load_detection_rules() -> dict:
    """Load action detection rules from S3. Cached for Lambda warm instances."""
    global _detection_rules_cache, _detection_rules_cache_ts
    import time
    now = time.time()

    if _detection_rules_cache and (now - _detection_rules_cache_ts) < _DETECTION_RULES_CACHE_TTL:
        return _detection_rules_cache

    try:
        resp = s3.get_object(Bucket=S3_BUCKET, Key="config/action_detection_rules.json")
        _detection_rules_cache = json.loads(resp["Body"].read())
        _detection_rules_cache_ts = now
        return _detection_rules_cache
    except Exception as e:
        logger.warning("Failed to load action detection rules: %s — using empty ruleset", e)
        return {"rules": [], "expiry_days": 14, "version": "0"}


def _iso_week(date_str: str) -> str:
    """Convert YYYY-MM-DD to YYYY-WNN format."""
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    iso = dt.isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"


def write_action(coach_id: str, domain: str, action_text: str,
                 issued_date: str) -> dict:
    """
    Write a new coach action to DynamoDB.

    Before writing, supersedes any existing open actions for the same domain
    by setting their status to 'superseded'.

    Returns the new action item dict.
    """
    action_id = f"{issued_date}-{domain}"
    issued_week = _iso_week(issued_date)

    # Supersede existing open actions for this domain
    existing_open = get_open_actions(domain=domain)
    for old_action in existing_open:
        old_id = old_action.get("action_id", "")
        if old_id == action_id:
            continue  # Don't supersede ourselves
        try:
            table.update_item(
                Key={
                    "pk": f"USER#{USER_ID}",
                    "sk": f"SOURCE#coach_actions#{old_id}",
                },
                UpdateExpression="SET #st = :s, superseded_by = :sb",
                ExpressionAttributeNames={"#st": "status"},
                ExpressionAttributeValues={
                    ":s": "superseded",
                    ":sb": action_id,
                },
            )
            logger.info("Superseded action %s with %s", old_id, action_id)
        except Exception as e:
            logger.warning("Failed to supersede action %s: %s", old_id, e)

    item = {
        "pk": f"USER#{USER_ID}",
        "sk": f"SOURCE#coach_actions#{action_id}",
        "action_id": action_id,
        "coach_id": coach_id,
        "domain": domain,
        "issued_date": issued_date,
        "issued_week": issued_week,
        "action_text": action_text,
        "status": "open",
        "completion_date": None,
        "completion_method": None,
        "follow_up_note": None,
        "superseded_by": None,
    }

    try:
        clean = json.loads(json.dumps(item, default=str), parse_float=Decimal)
        table.put_item(Item=clean)
        logger.info("Action written: %s (coach=%s, domain=%s)", action_id, coach_id, domain)
        return item
    except Exception as e:
        logger.error("Failed to write action %s: %s", action_id, e)
        raise


def get_open_actions(domain: str = None) -> list:
    """
    Query all open actions, optionally filtered by domain.

    Returns list of action dicts.
    """
    try:
        resp = table.query(
            KeyConditionExpression=(
                Key("pk").eq(f"USER#{USER_ID}")
                & Key("sk").begins_with("SOURCE#coach_actions#")
            ),
            FilterExpression="attribute_exists(#st) AND #st = :open",
            ExpressionAttributeNames={"#st": "status"},
            ExpressionAttributeValues={":open": "open"},
        )
        items = _decimal_to_float(resp.get("Items", []))
    except Exception as e:
        logger.error("Failed to query open actions: %s", e)
        return []

    if domain:
        items = [i for i in items if i.get("domain") == domain]

    # Sort by issued_date descending
    items.sort(key=lambda x: x.get("issued_date", ""), reverse=True)
    return items


def get_action_history(domain: str = None, limit: int = 10) -> list:
    """
    Query all actions sorted by date, optionally filtered by domain.

    Returns list of action dicts (most recent first), capped at limit.
    """
    try:
        resp = table.query(
            KeyConditionExpression=(
                Key("pk").eq(f"USER#{USER_ID}")
                & Key("sk").begins_with("SOURCE#coach_actions#")
            ),
            ScanIndexForward=False,
        )
        items = _decimal_to_float(resp.get("Items", []))
    except Exception as e:
        logger.error("Failed to query action history: %s", e)
        return []

    if domain:
        items = [i for i in items if i.get("domain") == domain]

    # Sort by issued_date descending
    items.sort(key=lambda x: x.get("issued_date", ""), reverse=True)
    return items[:limit]


def complete_action(action_id: str, method: str = "manual",
                    note: str = None) -> dict:
    """
    Mark an action as completed.

    Returns the updated action item dict.
    """
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    update_expr = "SET #st = :completed, completion_date = :cd, completion_method = :cm"
    attr_names = {"#st": "status"}
    attr_values = {
        ":completed": "completed",
        ":cd": today,
        ":cm": method,
    }

    if note:
        update_expr += ", follow_up_note = :fn"
        attr_values[":fn"] = note

    try:
        resp = table.update_item(
            Key={
                "pk": f"USER#{USER_ID}",
                "sk": f"SOURCE#coach_actions#{action_id}",
            },
            UpdateExpression=update_expr,
            ExpressionAttributeNames=attr_names,
            ExpressionAttributeValues=attr_values,
            ReturnValues="ALL_NEW",
        )
        updated = _decimal_to_float(resp.get("Attributes", {}))
        logger.info("Action %s completed (method=%s)", action_id, method)
        return updated
    except Exception as e:
        logger.error("Failed to complete action %s: %s", action_id, e)
        raise


def check_action_completion(action: dict, inventory: dict) -> dict:
    """
    Check if an action was auto-completed based on detection rules.

    Loads rules from config/action_detection_rules.json, matches the action
    text against rule patterns, and checks whether the relevant data source
    has records after the action's issued date.

    Returns {"completed": True, "method": "auto_detected", "detail": "..."}
    if completion detected, or None if not.
    """
    action_text = (action.get("action_text") or "").lower()
    issued_date = action.get("issued_date", "")
    if not action_text or not issued_date:
        return None

    rules_config = _load_detection_rules()
    rules = rules_config.get("rules", [])

    for rule in rules:
        pattern = rule.get("pattern", "")
        if not pattern:
            continue

        if not re.search(pattern, action_text, re.IGNORECASE):
            continue

        source = rule.get("source", "")
        condition = rule.get("condition", "")

        if condition == "record_exists_after_issued_date":
            src_info = inventory.get(source, {})
            if not src_info.get("exists"):
                continue
            latest = src_info.get("latest", "")
            if latest and latest >= issued_date:
                return {
                    "completed": True,
                    "method": "auto_detected",
                    "detail": f"{source} data found after {issued_date} (latest: {latest})",
                }
        elif condition == "metric_check":
            # Metric threshold checks require querying actual values — skip for now
            continue

    return None


def build_action_history_for_prompt(domain: str) -> str:
    """
    Build the 'YOUR PREVIOUS ACTIONS' block for coach prompt injection.

    Queries recent actions for the domain, checks expiry, and formats
    a human-readable summary of action statuses.
    """
    actions = get_action_history(domain=domain, limit=5)
    if not actions:
        return ""

    today = datetime.now(timezone.utc)
    rules_config = _load_detection_rules()
    expiry_days = rules_config.get("expiry_days", 14)

    lines = []
    for action in actions:
        week = action.get("issued_week", "")
        text = action.get("action_text", "")
        status = action.get("status", "open")
        issued_date = action.get("issued_date", "")

        if status == "open" and issued_date:
            try:
                issued_dt = datetime.strptime(issued_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
                age_days = (today - issued_dt).days
                if age_days > expiry_days:
                    status_str = f"EXPIRED ({age_days} days, exceeded {expiry_days}-day window)"
                else:
                    status_str = f"OPEN ({age_days} days)"
            except ValueError:
                status_str = "OPEN"
        elif status == "completed":
            method = action.get("completion_method", "")
            detail = action.get("follow_up_note", "")
            parts = ["COMPLETED"]
            if method:
                parts.append(f"({method}")
                if detail:
                    parts[-1] += f": {detail}"
                parts[-1] += ")"
            status_str = " ".join(parts)
        elif status == "superseded":
            superseded_by = action.get("superseded_by", "")
            status_str = f"SUPERSEDED (replaced by {superseded_by})" if superseded_by else "SUPERSEDED"
        else:
            status_str = status.upper()

        lines.append(f'  - [{week}] "{text}" -- STATUS: {status_str}')

    return "YOUR PREVIOUS ACTIONS:\n" + "\n".join(lines) + "\n"


# ══════════════════════════════════════════════════════════════════════════════
# BUILDER'S PARADOX SCORE (Workstream 6)
# ══════════════════════════════════════════════════════════════════════════════


def compute_builders_paradox_score(days: int = 7) -> dict:
    """
    Compute the Builder's Paradox score — ratio of platform activity to health activity.

    Platform signals (from Todoist):
      - Tasks completed in platform/engineering projects

    Health signals:
      - Workouts logged (Strava)
      - Journal entries written (Notion)
      - Habit completion rate (Habitify)
      - Steps (Garmin — SOT)

    Score 0-100:
      0-30: healthy (health activity >= platform activity)
      30-60: tipping (platform significantly exceeds health)
      60-100: displaced (heavy platform work, minimal health execution)
    """
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    start = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")

    # Platform activity: Todoist tasks completed
    platform_tasks = 0
    try:
        resp = table.query(
            KeyConditionExpression=Key("pk").eq(f"{USER_PREFIX}todoist") & Key("sk").between(
                f"DATE#{start}", f"DATE#{today}~"
            ),
        )
        for item in resp.get("Items", []):
            # Count completed tasks — todoist records have task_count or completed_count
            platform_tasks += int(item.get("tasks_completed", 0) or 0)
            # Fallback: count items if no aggregate field
            if platform_tasks == 0:
                tasks = item.get("tasks", [])
                if isinstance(tasks, list):
                    platform_tasks += len(tasks)
    except Exception as e:
        logger.warning("Builder's Paradox: Todoist query failed: %s", e)

    # Health signals
    workouts = 0
    try:
        resp = table.query(
            KeyConditionExpression=Key("pk").eq(f"{USER_PREFIX}strava") & Key("sk").between(
                f"DATE#{start}", f"DATE#{today}~"
            ),
            Select="COUNT",
        )
        workouts = resp.get("Count", 0)
    except Exception:
        pass

    journal_entries = 0
    try:
        resp = table.query(
            KeyConditionExpression=Key("pk").eq(f"{USER_PREFIX}notion") & Key("sk").between(
                f"DATE#{start}", f"DATE#{today}~"
            ),
            Select="COUNT",
        )
        journal_entries = resp.get("Count", 0)
    except Exception:
        pass

    habit_adherence_pct = 0
    habit_days = 0
    try:
        resp = table.query(
            KeyConditionExpression=Key("pk").eq(f"{USER_PREFIX}habitify") & Key("sk").between(
                f"DATE#{start}", f"DATE#{today}~"
            ),
        )
        items = resp.get("Items", [])
        pcts = []
        for item in items:
            p = item.get("completion_pct") or item.get("tier0_pct")
            if p is not None:
                pcts.append(float(p) * (100 if float(p) <= 1 else 1))
        if pcts:
            habit_adherence_pct = round(sum(pcts) / len(pcts))
            habit_days = len(pcts)
    except Exception:
        pass

    avg_steps = 0
    try:
        resp = table.query(
            KeyConditionExpression=Key("pk").eq(f"{USER_PREFIX}garmin") & Key("sk").between(
                f"DATE#{start}", f"DATE#{today}~"
            ),
        )
        step_vals = [float(i.get("steps", 0)) for i in resp.get("Items", []) if i.get("steps")]
        if step_vals:
            avg_steps = round(sum(step_vals) / len(step_vals))
    except Exception:
        pass

    # Compute score
    # Health score components (each 0-25, total 0-100)
    workout_score = min(25, workouts * 5)  # 5 workouts/week = max
    journal_score = min(25, journal_entries * 5)  # 5 entries/week = max
    habit_score = min(25, habit_adherence_pct * 0.25)  # 100% = 25
    step_score = min(25, avg_steps / 320)  # 8000 steps = 25

    health_score = workout_score + journal_score + habit_score + step_score

    # Platform intensity (normalized)
    platform_intensity = min(100, platform_tasks * 3)  # ~33 tasks/week = max intensity

    # Builder's Paradox score: high platform + low health = high score (bad)
    if health_score + platform_intensity == 0:
        score = 50  # No data
    else:
        # Weighted: platform overpowering health
        raw = (platform_intensity / max(1, health_score + platform_intensity)) * 100
        score = round(min(100, raw))

    if score <= 30:
        label = "healthy"
    elif score <= 60:
        label = "tipping"
    else:
        label = "displaced"

    interpretation = (
        f"{platform_tasks} platform tasks completed, {workouts} workouts, "
        f"{journal_entries} journal entries, {habit_adherence_pct}% habit adherence, "
        f"{avg_steps} avg steps."
    )
    if score > 50:
        interpretation += (
            " The platform is consuming the time and energy it was designed to protect."
        )
    elif score > 30:
        interpretation += (
            " Platform activity is outpacing health behaviors — watch this trend."
        )
    else:
        interpretation += (
            " Health behaviors are keeping pace with platform work — balanced."
        )

    return {
        "score": score,
        "label": label,
        "platform_tasks": platform_tasks,
        "workouts": workouts,
        "journal_entries": journal_entries,
        "habit_adherence_pct": habit_adherence_pct,
        "avg_steps": avg_steps,
        "health_score": round(health_score),
        "platform_intensity": round(platform_intensity),
        "interpretation": interpretation,
    }


# ══════════════════════════════════════════════════════════════════════════════
# COACH THREADS — Persistent Memory (V2.1 Workstream 1)
# ══════════════════════════════════════════════════════════════════════════════


def write_coach_thread(coach_id: str, entry: dict) -> bool:
    """Write a thread entry after coach generation.

    Entry should contain: position_summary, predictions, surprises,
    stance_changes, emotional_investment, open_questions, learning_log.
    """
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    week = _iso_week(today)

    item = {
        "pk": f"USER#{USER_ID}",
        "sk": f"SOURCE#coach_thread#{coach_id}#{today}",
        "coach_id": coach_id,
        "date": today,
        "week": week,
        "generation_context": entry.get("generation_context", "observatory"),
        "position_summary": entry.get("position_summary", ""),
        "predictions": entry.get("predictions", []),
        "surprises": entry.get("surprises", []),
        "stance_changes": entry.get("stance_changes", []),
        "emotional_investment": entry.get("emotional_investment", "observing"),
        "open_questions": entry.get("open_questions", []),
        "learning_log": entry.get("learning_log", []),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    try:
        clean = json.loads(json.dumps(item, default=str), parse_float=Decimal)
        table.put_item(Item=clean)
        logger.info("Thread entry written for %s on %s", coach_id, today)
        return True
    except Exception as e:
        logger.error("Failed to write thread for %s: %s", coach_id, e)
        return False


def read_coach_thread(coach_id: str, limit: int = 4) -> list:
    """Read recent thread entries for prompt injection.

    Returns list of thread entries, most recent first.
    """
    try:
        resp = table.query(
            KeyConditionExpression=Key("pk").eq(f"USER#{USER_ID}") & Key("sk").begins_with(
                f"SOURCE#coach_thread#{coach_id}#"
            ),
            ScanIndexForward=False,
            Limit=limit,
        )
        items = resp.get("Items", [])
        return [_decimal_to_float(i) for i in items]
    except Exception as e:
        logger.warning("Failed to read thread for %s: %s", coach_id, e)
        return []


def update_prediction_status(coach_id: str, prediction_id: str, status: str,
                              outcome_note: str = None) -> bool:
    """Mark a prediction as confirmed/refuted in the thread entry that contains it.

    Scans recent thread entries to find the prediction and updates its status.
    """
    try:
        entries = read_coach_thread(coach_id, limit=10)
        for entry in entries:
            predictions = entry.get("predictions", [])
            for pred in predictions:
                if pred.get("prediction_id") == prediction_id:
                    pred["status"] = status
                    if outcome_note:
                        pred["outcome_note"] = outcome_note
                    pred["evaluated_at"] = datetime.now(timezone.utc).isoformat()

                    # Write back the updated entry
                    clean = json.loads(json.dumps(entry, default=str), parse_float=Decimal)
                    table.put_item(Item=clean)
                    logger.info("Prediction %s updated to %s for %s", prediction_id, status, coach_id)
                    return True
        logger.warning("Prediction %s not found in thread for %s", prediction_id, coach_id)
        return False
    except Exception as e:
        logger.error("Failed to update prediction %s: %s", prediction_id, e)
        return False


def build_thread_prompt_block(coach_id: str, personality: dict = None) -> str:
    """Build the YOUR THREAD block for injection into coach prompts.

    Reads recent thread entries and formats them as a prompt section.
    """
    entries = read_coach_thread(coach_id, limit=4)
    if not entries:
        # No thread history yet — return personality seeds only
        if personality:
            return (
                "YOUR PERSONALITY TENDENCIES:\n"
                + "\n".join(f"- {t}" for t in personality.get("tendencies", []))
                + f"\nArc seed: {personality.get('arc_seed', '')}\n"
                + f"Signature behavior: {personality.get('signature_behavior', '')}\n"
                + "\nThis is your first assessment. Establish your voice and initial position.\n"
            )
        return ""

    parts = ["YOUR THREAD (what you've said and thought recently):\n"]

    for entry in entries:
        week = entry.get("week", "?")
        pos = entry.get("position_summary", "")
        if pos:
            parts.append(f"Week {week} position: \"{pos}\"")

        for pred in entry.get("predictions", []):
            status = pred.get("status", "pending")
            text = pred.get("text", "")
            conf = pred.get("confidence", "medium")
            status_note = f" — {pred.get('outcome_note', '')}" if pred.get("outcome_note") else ""
            parts.append(f"Week {week} prediction ({conf} confidence): \"{text}\" ({status.upper()}{status_note})")

        for surprise in entry.get("surprises", []):
            parts.append(f"Week {week} surprise: \"{surprise}\"")

        for change in entry.get("stance_changes", []):
            parts.append(f"Week {week} stance change: \"{change.get('from', '')}\" → \"{change.get('to', '')}\" (reason: {change.get('reason', '')})")

    # Current emotional investment
    latest = entries[0] if entries else {}
    investment = latest.get("emotional_investment", "observing")
    parts.append(f"\nYour emotional investment level: {investment.upper()}")

    # Open questions
    questions = latest.get("open_questions", [])
    if questions:
        parts.append("\nYOUR OPEN QUESTIONS:")
        for q in questions:
            parts.append(f"- {q}")

    # Thread usage rules
    parts.append(
        "\nRules for using your thread:\n"
        "- Reference your previous positions naturally. \"Last week I flagged [X] — here's what happened.\"\n"
        "- If a prediction resolved: explicitly call it out. \"I predicted [X]. I was [right/wrong].\"\n"
        "- If your position changed: own it. \"I initially thought [X] but the data now suggests [Y].\"\n"
        "- Your emotional investment should come through in tone, not stated explicitly.\n"
        "- Add to your open questions when something puzzles you.\n"
    )

    # Personality seeds (always include as context)
    if personality:
        parts.append(
            "\nYOUR PERSONALITY:\n"
            + "\n".join(f"- {t}" for t in personality.get("tendencies", []))
            + f"\nSignature behavior: {personality.get('signature_behavior', '')}\n"
        )

    return "\n".join(parts)


def extract_thread_from_narrative(coach_id: str, narrative: str, api_key: str) -> dict:
    """Extract thread data from a coach's generated narrative via a lightweight API call.

    Makes a Haiku-class call to parse: position_summary, predictions, surprises,
    emotional_investment_level, open_questions.
    """
    import urllib.request

    prompt = f"""Extract structured thread data from this coach narrative. Return ONLY valid JSON.

NARRATIVE:
{narrative[:2000]}

Extract:
{{
  "position_summary": "2-3 sentence summary of the coach's current stance/assessment",
  "predictions": [
    {{"prediction_id": "pred_YYYYMMDD_slug", "text": "the prediction in natural language", "confidence": "low|medium|high", "metric": "optional metric to check", "target_date": "optional YYYY-MM-DD", "status": "pending"}}
  ],
  "surprises": ["things that surprised the coach — empty list if nothing surprising"],
  "emotional_investment": "detached|observing|engaged|invested|concerned|excited",
  "open_questions": ["things the coach is curious about or watching"]
}}

Rules:
- position_summary: what does the coach believe RIGHT NOW about their domain for Matthew?
- predictions: only include explicit forward-looking claims. Not observations.
- emotional_investment: infer from language intensity. Academic/measured = observing. Strong opinions = invested. Worry = concerned.
- If nothing fits a field, use empty list or "observing" default."""

    try:
        model = os.environ.get("AI_MODEL_HAIKU", "claude-haiku-4-5-20251001")
        secret_name = os.environ.get("AI_SECRET_NAME", "life-platform/ai-keys")

        # Use provided API key
        req_body = json.dumps({
            "model": model,
            "max_tokens": 500,
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

        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read())

        text = "".join(
            b["text"] for b in result.get("content", []) if b.get("type") == "text"
        )

        # Parse JSON
        cleaned = text.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[1] if "\n" in cleaned else cleaned[3:]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
        return json.loads(cleaned.strip())

    except Exception as e:
        logger.warning("Thread extraction failed for %s: %s — using defaults", coach_id, e)
        return {
            "position_summary": narrative[:200] if narrative else "",
            "predictions": [],
            "surprises": [],
            "emotional_investment": "observing",
            "open_questions": [],
        }


# ══════════════════════════════════════════════════════════════════════════════
# CREDIBILITY SCORES (V2.2 Workstream 4)
# ══════════════════════════════════════════════════════════════════════════════

COACH_IDS_ALL = ["sleep", "nutrition", "training", "mind", "physical", "glucose", "labs", "explorer"]


def compute_credibility(coach_id: str) -> dict:
    """Compute credibility score for a coach based on prediction track record.

    Returns: {score, label, accuracy_pct, calibration, predictions_resolved, notable}
    """
    entries = read_coach_thread(coach_id, limit=20)

    all_preds = []
    for entry in entries:
        for pred in entry.get("predictions", []):
            all_preds.append(pred)

    resolved = [p for p in all_preds if p.get("status") in ("confirmed", "refuted")]
    confirmed = [p for p in resolved if p["status"] == "confirmed"]
    refuted = [p for p in resolved if p["status"] == "refuted"]
    pending = [p for p in all_preds if p.get("status") == "pending"]

    total_resolved = len(resolved)
    accuracy_pct = round(len(confirmed) / total_resolved * 100, 1) if total_resolved > 0 else 0

    # Calibration: do high-confidence predictions actually confirm more?
    high_conf = [p for p in resolved if p.get("confidence") == "high"]
    high_conf_right = sum(1 for p in high_conf if p["status"] == "confirmed")
    if len(high_conf) >= 3:
        high_accuracy = high_conf_right / len(high_conf)
        if high_accuracy < 0.5:
            calibration = "over-confident"
        elif high_accuracy > 0.8:
            calibration = "well-calibrated"
        else:
            calibration = "developing"
    else:
        calibration = "insufficient_data"

    # Label
    if total_resolved < 5:
        label = "nascent"
        score = 30
    elif accuracy_pct >= 80 and total_resolved >= 15:
        label = "authoritative"
        score = 90
    elif accuracy_pct >= 60 and total_resolved >= 10:
        label = "reliable"
        score = 70
    else:
        label = "developing"
        score = 50

    return {
        "score": score,
        "label": label,
        "accuracy_pct": accuracy_pct,
        "calibration": calibration,
        "predictions_total": len(all_preds),
        "predictions_resolved": total_resolved,
        "confirmed": len(confirmed),
        "refuted": len(refuted),
        "pending": len(pending),
    }


def compute_all_credibility() -> dict:
    """Compute and store credibility for all coaches."""
    results = {}
    for cid in COACH_IDS_ALL:
        cred = compute_credibility(cid)
        results[cid] = cred

        # Store in DDB
        try:
            item = {
                "pk": f"USER#{USER_ID}",
                "sk": f"SOURCE#coach_credibility#{cid}",
                "coach_id": cid,
                **cred,
                "computed_at": datetime.now(timezone.utc).isoformat(),
            }
            clean = json.loads(json.dumps(item, default=str), parse_float=Decimal)
            table.put_item(Item=clean)
        except Exception as e:
            logger.warning("Failed to store credibility for %s: %s", cid, e)

    return results


def load_credibility(coach_id: str) -> dict:
    """Load cached credibility score for a coach."""
    try:
        resp = table.get_item(
            Key={"pk": f"USER#{USER_ID}", "sk": f"SOURCE#coach_credibility#{coach_id}"}
        )
        item = resp.get("Item")
        return _decimal_to_float(item) if item else {"label": "nascent", "score": 30}
    except Exception:
        return {"label": "nascent", "score": 30}


# ══════════════════════════════════════════════════════════════════════════════
# THREAD SUMMARIZATION (V2.2 Workstream 5)
# ══════════════════════════════════════════════════════════════════════════════


def summarize_coach_month(coach_id: str, month: str) -> dict:
    """Summarize a coach's thread entries for a given month.

    Args:
        coach_id: e.g. "glucose"
        month: e.g. "2026-04"

    Returns a compressed summary for prompt injection.
    """
    # Query all thread entries for this month
    start_sk = f"SOURCE#coach_thread#{coach_id}#{month}-01"
    end_sk = f"SOURCE#coach_thread#{coach_id}#{month}-31~"

    try:
        resp = table.query(
            KeyConditionExpression=Key("pk").eq(f"USER#{USER_ID}") & Key("sk").between(start_sk, end_sk),
        )
        entries = [_decimal_to_float(i) for i in resp.get("Items", [])]
    except Exception as e:
        logger.warning("Thread query failed for %s/%s: %s", coach_id, month, e)
        return {}

    if not entries:
        return {}

    # Extract summary data
    positions = [e.get("position_summary", "") for e in entries if e.get("position_summary")]
    all_preds = []
    for e in entries:
        all_preds.extend(e.get("predictions", []))
    all_surprises = []
    for e in entries:
        all_surprises.extend(e.get("surprises", []))
    stance_changes = []
    for e in entries:
        stance_changes.extend(e.get("stance_changes", []))

    # Emotional arc
    investments = [e.get("emotional_investment", "observing") for e in entries]
    emotional_arc = " → ".join(dict.fromkeys(investments))  # deduplicated ordered

    confirmed = sum(1 for p in all_preds if p.get("status") == "confirmed")
    refuted = sum(1 for p in all_preds if p.get("status") == "refuted")

    summary = {
        "month": month,
        "entries": len(entries),
        "position_arc": f"{positions[0][:100]}... → ...{positions[-1][:100]}" if len(positions) >= 2 else (positions[0][:200] if positions else ""),
        "predictions_made": len(all_preds),
        "predictions_resolved": {"confirmed": confirmed, "refuted": refuted},
        "key_surprises": all_surprises[:3],
        "stance_changes": len(stance_changes),
        "emotional_arc": emotional_arc,
    }

    # Store summary
    try:
        item = {
            "pk": f"USER#{USER_ID}",
            "sk": f"SOURCE#coach_thread_summary#{coach_id}#{month}",
            "coach_id": coach_id,
            **summary,
            "summarized_at": datetime.now(timezone.utc).isoformat(),
        }
        clean = json.loads(json.dumps(item, default=str), parse_float=Decimal)
        table.put_item(Item=clean)
    except Exception as e:
        logger.warning("Failed to store thread summary for %s/%s: %s", coach_id, month, e)

    return summary


def read_thread_summaries(coach_id: str) -> list:
    """Read all monthly thread summaries for a coach."""
    try:
        resp = table.query(
            KeyConditionExpression=Key("pk").eq(f"USER#{USER_ID}") & Key("sk").begins_with(
                f"SOURCE#coach_thread_summary#{coach_id}#"
            ),
        )
        return [_decimal_to_float(i) for i in resp.get("Items", [])]
    except Exception:
        return []
