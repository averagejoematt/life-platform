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
    "physical": {"orientation": 7, "established": 30, "source": "withings", "unit": "weight readings"},
    "mind": {"orientation": 3, "established": 14, "source": "journal", "unit": "journal entries"},
    "labs": {"orientation": 14, "established": 60, "source": "whoop", "unit": "days any data"},
    "explorer": {"orientation": 14, "established": 60, "source": "whoop", "unit": "days any data"},
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

        if days < orientation_threshold:
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
