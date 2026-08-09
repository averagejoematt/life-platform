"""
intelligence_common.py — Shared utilities for the Intelligence Layer V2.

Provides data inventory, data maturity, goals loading, and coach preamble
generation used by all content-producing Lambdas (observatory, daily brief,
weekly digest, chronicle, etc.).

Bundled into every function's deploy package (#781 retired the shared layer).

v1.0.0 — 2026-04-07 (Intelligence Layer V2 Session 1)
"""

import hashlib
import json
import logging
import os
import re
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

import boto3
from boto3.dynamodb.conditions import Attr, Key
from coach.reading_date_fidelity import guard_derived_summary  # #2343: derived-summary day correspondence
from coach.voice_register_guard import sanitize_summary  # #1987: deterministic voice-register check
from common.text_utils import truncate_at_word  # #1224: word-boundary summary truncation (no mid-word cut)
from experiment import calibration_core  # #538: the shared prediction-calibration scorer (Brier + reliability)
from experiment.phase_filter import source_reads_cross_phase, with_phase_filter  # ADR-058 / #2109

logger = logging.getLogger(__name__)

TABLE_NAME = os.environ.get("TABLE_NAME", "life-platform")
S3_BUCKET = os.environ.get("S3_BUCKET", "matthew-life-platform")
USER_ID = os.environ.get("USER_ID", "matthew")
USER_PREFIX = f"USER#{USER_ID}#SOURCE#"

dynamodb = boto3.resource("dynamodb", region_name="us-west-2")
table = dynamodb.Table(TABLE_NAME)
s3 = boto3.client("s3", region_name="us-west-2")


from common.numeric import decimals_to_float as _decimal_to_float  # noqa: E402,F401

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


def fetch_profile(table, user_id: str = "matthew") -> dict:
    """Canonical profile read — pk USER#{user_id}, sk PROFILE#v1.

    This is the only profile key that exists in the table. Ten lambdas carried
    local copies, and two other key shapes circulated that silently returned
    {} on every call (hypothesis_engine, site-api AI context — found 2026-06-12).
    """
    try:
        r = table.get_item(Key={"pk": f"USER#{user_id}", "sk": "PROFILE#v1"})
        return _decimal_to_float(r.get("Item", {}))
    except Exception as e:
        logging.getLogger("intelligence-common").error(f"fetch_profile: {e}")
        return {}


def build_data_inventory() -> dict:
    """
    Query DynamoDB for existence and recency of all major data partitions.

    Returns dict of source → {exists, latest, records, days_of_data}.
    Used by data maturity, coach prompts, and the intelligence validator.

    Read PER-SOURCE cross-phase (#2109). This is the #1203 liveness/recency shape at
    its highest-leverage site: `days_of_data` is what `_MATURITY_THRESHOLDS` compares
    against to decide whether a coach speaks in ORIENTATION, EMERGING or ESTABLISHED
    voice, and `latest` is what the validator calls staleness. Phase-filtered, both
    answered "the cycle's age" instead of "the pipe's history" — measured on cycle 12
    Day 2, the 90-day COUNT over SOURCE#whoop returned 137 rows unfiltered and 1
    filtered, so every coach was pushed back to "I have 1 night of data" the morning
    after a reset, and the platform reported its own pipes as days old.

    That is the exact question the phase tag must not answer: a maturity threshold is
    a claim about how much of the BODY has been measured, and the body's record does
    not reset when the experiment does (#2079/#2089). The window (90 days) is what
    bounds it. Every partition in `_INVENTORY_SOURCES` is RAW_TIMESERIES or CROSS_PHASE
    today, so all of them read cross-phase — but the decision is derived per partition
    from `phase_taxonomy` (#2092's shape), so adding an EXPERIMENT_SCOPED partition to
    the inventory later keeps its filter without anyone remembering to ask.
    """
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    d90 = (datetime.now(timezone.utc) - timedelta(days=90)).strftime("%Y-%m-%d")

    inventory: dict[str, Any] = {}
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
            # #2109: cross-phase unless the partition is EXPERIMENT_SCOPED — see the docstring.
            cross_phase = source_reads_cross_phase(partition)
            # Count records in last 90 days
            resp = table.query(
                **with_phase_filter(
                    {
                        "KeyConditionExpression": Key("pk").eq(pk) & Key("sk").between(f"DATE#{d90}", f"DATE#{today}~"),
                        "Select": "COUNT",
                    },
                    include_pilot=cross_phase,
                )
            )
            count = resp.get("Count", 0)

            # Get latest record. NB the Limit:1 half is the #1203 mechanism verbatim —
            # DynamoDB applies Limit BEFORE FilterExpression, so a filtered read here
            # returned the newest row, discarded it for being pilot-tagged, and reported
            # `latest: None` for a partition ingesting normally.
            latest_resp = table.query(
                **with_phase_filter(
                    {
                        "KeyConditionExpression": Key("pk").eq(pk) & Key("sk").begins_with("DATE#"),
                        "ScanIndexForward": False,
                        "Limit": 1,
                        "ProjectionExpression": "sk",
                    },
                    include_pilot=cross_phase,
                )
            )
            latest_items = latest_resp.get("Items", [])
            latest_date = None
            if latest_items:
                sk = latest_items[0].get("sk", "")
                latest_date = sk.replace("DATE#", "")[:10]

            # For CGM, check if blood_glucose_avg exists in apple_health records
            if label == "cgm":
                cgm_resp = table.query(
                    **with_phase_filter(
                        {
                            "KeyConditionExpression": Key("pk").eq(pk) & Key("sk").between(f"DATE#{d90}", f"DATE#{today}~"),
                            "FilterExpression": "attribute_exists(blood_glucose_avg)",
                            "Select": "COUNT",
                        },
                        include_pilot=cross_phase,
                    )
                )
                count = cgm_resp.get("Count", 0)
                # #1658: `latest_date` above is the newest apple_health row, and HAE writes
                # apple_health EVERY day — so cgm inherited a permanently-fresh date and the
                # >=3d/>=7d staleness directives in build_coach_preamble were structurally
                # unreachable for glucose. Re-probe for the newest GLUCOSE-BEARING record.
                # Deliberately NOT `Limit: 1` + filter: DynamoDB applies Limit before the
                # FilterExpression (#1203), which is the exact trap this function documents.
                # The 90-day key range bounds the read instead.
                cgm_latest_resp = table.query(
                    **with_phase_filter(
                        {
                            "KeyConditionExpression": Key("pk").eq(pk) & Key("sk").between(f"DATE#{d90}", f"DATE#{today}~"),
                            "FilterExpression": "attribute_exists(blood_glucose_avg)",
                            "ScanIndexForward": False,
                            "ProjectionExpression": "sk",
                        },
                        include_pilot=cross_phase,
                    )
                )
                cgm_items = cgm_latest_resp.get("Items", [])
                latest_date = cgm_items[0].get("sk", "").replace("DATE#", "")[:10] if cgm_items else None

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
    "physical": {
        "orientation": 7,
        "established": 30,
        "source": "withings",
        "unit": "weight readings",
        "composite": True,
        "requires_dexa": True,
    },
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
    '- End with: "I\'ll have more to say once I have enough data to see a pattern."\n'
    "- Tone: professional introduction, not apology for lack of data\n"
)

EMERGING_VOICE = (
    "You are in EMERGING mode. You have {days} {unit} of data. "
    "Patterns are starting to form but confidence is low.\n\n"
    "Voice rules:\n"
    "- You may note preliminary patterns with explicit confidence caveats\n"
    '- Use language: "An early signal suggests...", "I\'m watching whether..."\n'
    '- Do NOT use definitive language like "your pattern is" or "this shows"\n'
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
            target_date = (
                (today + timedelta(days=max(0, orientation_threshold - days))).strftime("%B %d") if phase == "orientation" else None
            )
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
        from common.constants import EXPERIMENT_BASELINE_WEIGHT_LBS, EXPERIMENT_START_DATE  # ADR-058

        return {
            "mission": "12-month body recomposition for longevity",
            "start_date": EXPERIMENT_START_DATE,
            "start_weight_lbs": EXPERIMENT_BASELINE_WEIGHT_LBS,
            "targets": {},
            "philosophy": "",
            "known_constraints": [],
            "coach_briefing": "No goals configuration found.",
        }


# ══════════════════════════════════════════════════════════════════════════════
# COACH PREAMBLE BUILDER
# ══════════════════════════════════════════════════════════════════════════════


def build_coach_preamble(coach_name: str, domain: str, goals: dict, inventory: dict, maturity: dict, action_history: list = None) -> str:
    """
    Build the standard context preamble injected into every coach prompt.

    This is the single source of truth for coach context — ensures every coach
    (observatory, daily brief, weekly digest) gets the same foundational info.
    """
    parts = []

    # 1. First-person voice directive
    parts.append(
        f"VOICE: Write in FIRST PERSON. You ARE {coach_name}. "
        f'Say "I" not "{coach_name}". Address Matthew directly as "you". '
        f"Never refer to yourself in third person.\n"
    )

    # 2. Goals context — V2.2 updated schema
    # Mission + athlete profile (replaces old coach_briefing)
    mission = goals.get("mission", goals.get("coach_briefing", ""))
    if mission:
        parts.append(f"MATTHEW'S MISSION:\n{mission}\n")

    philosophy = goals.get("philosophy", "")
    if philosophy:
        parts.append(f"PHILOSOPHY: {philosophy}\n")

    # Athlete profile (V2.2)
    profile = goals.get("athlete_profile", {})
    if profile:
        prior = profile.get("prior_transformation", {})
        if prior:
            parts.append(
                f"ATHLETE CONTEXT: {profile.get('type', 'unknown')}. "
                f"Prior transformation: {prior.get('start_weight')}→{prior.get('end_weight')} lbs "
                f"in {prior.get('duration_months')} months. {prior.get('outcome', '')}\n"
            )
        if profile.get("binge_eating_pattern"):
            parts.append(f"BEHAVIORAL NOTE: {profile['binge_eating_pattern']}\n")

    # Targets
    targets = goals.get("targets", {})
    target_lines = []
    _target_map = {
        "weight.goal_lbs": "Weight goal",
        "body_composition.goal_body_fat_pct": "Body fat goal",
        "body_composition.lean_mass_floor_lbs": "Lean mass floor (HARD STOP)",
        "nutrition.daily_calories_target": "Calorie target",
        "nutrition.daily_protein_min_g": "Protein minimum",
        "nutrition.daily_fiber_min_g": "Fiber minimum",
        "sleep.target_hours": "Sleep target",
        "biomarkers.resting_hr_target_bpm": "RHR target",
        "biomarkers.hrv_target_ms": "HRV target",
        "behavioral.journal_entries_per_week": "Journal entries/week",
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

    # Training phase (V2.2)
    training = targets.get("training", {})
    if training.get("current_phase"):
        phases = training.get("phases", [])
        current = next((p for p in phases if p.get("phase", "").lower() == training["current_phase"].lower()), None)
        if current:
            parts.append(
                f"TRAINING PHASE: {current['phase']} (months {current.get('months', '?')})\n"
                f"  Structure: {current.get('structure', 'TBD')}\n"
                f"  Notes: {current.get('notes', '')}\n"
            )

    # Nutrition specifics (V2.2)
    nutrition = targets.get("nutrition", {})
    eating_window = nutrition.get("eating_window", {})
    if eating_window:
        parts.append(
            f"EATING WINDOW: {eating_window.get('type', 'IF')} ({eating_window.get('window', '')}). " f"{eating_window.get('note', '')}\n"
        )

    # Mental health context — COACHES ONLY (V2.2)
    # This section is injected into coach prompts but NOT surfaced in public API responses
    mh = goals.get("mental_health_context", {})
    if mh and mh.get("drivers"):
        parts.append(
            "MENTAL HEALTH CONTEXT (COACHES ONLY — do not reference specifics publicly):\n"
            + "\n".join(f"  - {d}" for d in mh["drivers"])
            + "\n"
            + f"Coach guidance: {mh.get('coach_guidance', '')}\n"
        )

    # Failure mode + early warning signals (V2.2)
    fm = goals.get("failure_mode", {})
    if fm:
        parts.append(
            f"FAILURE MODE PATTERN: {fm.get('pattern', '')}\n"
            f"Early warning signals:\n"
            + "\n".join(f"  ⚠️ {s}" for s in fm.get("early_warning_signals", []))
            + "\n"
            + f"Response protocol: {fm.get('coach_response', '')}\n"
        )

    # Communication directives (V2.2)
    comm = goals.get("coach_communication", {})
    do_not = comm.get("do_not", [])
    if do_not:
        parts.append("DO NOT:\n" + "\n".join(f"  - {d}" for d in do_not) + "\n")

    constraints = goals.get("known_constraints", [])
    if constraints:
        parts.append("KNOWN CONSTRAINTS:\n" + "\n".join(f"  - {c}" for c in constraints) + "\n")

    # 3. Data maturity + phase voice template
    domain_maturity = maturity.get(domain, {})
    phase = domain_maturity.get("phase", "orientation")
    days = domain_maturity.get("days", 0)
    unit = domain_maturity.get("unit", "days")
    threshold = domain_maturity.get("threshold", 7)

    if phase == "orientation":
        voice_tmpl = ORIENTATION_VOICE.format(
            days=days,
            unit=unit,
            threshold=threshold,
            name=coach_name,
            domain=domain,
        )
    elif phase == "emerging":
        voice_tmpl = EMERGING_VOICE.format(days=days, unit=unit)
    else:
        voice_tmpl = ESTABLISHED_VOICE.format(days=days, unit=unit)

    parts.append(f"DATA MATURITY STATUS:\nPhase: {phase} ({days} {unit} of data, threshold: {threshold})\n{voice_tmpl}\n")

    # 4. Data inventory + staleness signals (P5.8)
    # Days-since-latest computed inline so coaches know NOT to opine on stale
    # sources. The evaluator's distinction between "no data" and "stale data"
    # matters here — silent-failure mode was the v7.x audit's #1 cost driver.
    _today = datetime.now(timezone.utc).date()
    inventory_lines = []
    stale_sources = []  # sources stale enough to warrant a separate hard warning
    for src, info in sorted(inventory.items()):
        if info.get("exists"):
            latest = info.get("latest", "?")
            count = info.get("records", 0)
            staleness_tag = ""
            try:
                latest_dt = datetime.strptime(latest, "%Y-%m-%d").date()
                days_stale = (_today - latest_dt).days
                if days_stale >= 7:
                    staleness_tag = f" ⚠️ STALE — {days_stale} days since last record"
                    stale_sources.append((src, days_stale))
                elif days_stale >= 3:
                    staleness_tag = f" (⚠️ {days_stale} days since last record)"
            except (ValueError, TypeError):
                pass  # latest isn't a parseable date — skip staleness check
            inventory_lines.append(f"  - {src}: AVAILABLE ({count} records, latest: {latest}){staleness_tag}")
        else:
            inventory_lines.append(f"  - {src}: not available")
    parts.append("DATA SOURCES:\n" + "\n".join(inventory_lines) + "\n")

    # Hard staleness directive — if any source is ≥7 days behind, instruct
    # the coach to avoid claims about it. This is the explicit P5.8 fix:
    # without it, coaches confidently opine on sources that haven't reported
    # in weeks (the silent-failure mode from ADR-051).
    if stale_sources:
        parts.append(
            "DATA STALENESS WARNINGS:\n"
            + "\n".join(
                f"  - {src} hasn't reported in {days} days. Do NOT make claims about "
                f"{src}-related patterns or recent behavior using {src}; reference "
                f"its last-known state explicitly if you must mention it."
                for src, days in stale_sources
            )
            + "\n"
        )

    # 5. Data interpretation rules
    parts.append(
        "DATA INTERPRETATION RULES:\n"
        "- If an activity count or log is ZERO, that means Matthew hasn't done that activity — "
        'say "no training logged" NOT "provide your training data"\n'
        "- If a data source exists but values are null for today, use the most recent available data\n"
        '- NEVER tell Matthew to "obtain" or "get" a scan/test if the data already exists above\n'
        "- Garmin is the step count source of truth (wearable). Ignore Apple Health step counts if Garmin data is available.\n"
        '- If a target is "not yet set", do NOT invent one. You may suggest one with reasoning.\n'
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
            action_lines.append(f'  - [{week}] "{text}" — STATUS: {status.upper()}')
        parts.append("YOUR PREVIOUS ACTIONS:\n" + "\n".join(action_lines) + "\n")

    return "\n".join(parts)


# ══════════════════════════════════════════════════════════════════════════════
# INTELLIGENCE VALIDATOR (Workstream 4)
# ══════════════════════════════════════════════════════════════════════════════

# Phrases indicating a coach claims data is missing
_NULL_CLAIM_PHRASES = [
    "unavailable",
    "not yet available",
    "remains unknown",
    "data gap",
    "cannot determine",
    "no data",
    "data is null",
    "not available",
    "remains null",
    "awaiting data",
    "hasn't been provided",
    "provide your",
    "obtain a",
    "get a scan",
    "submit your",
    "share your",
    "we don't have",
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


# The checks validate_coach_output can actually emit. write_quality_results derives
# `checks_run` from this tuple (#1658) — the count used to be a hardcoded 5 while only
# four checks could fire, so the intelligence_quality partition asserted a check that
# was structurally dark.
_VALIDATOR_CHECKS = ("null_claim_vs_data", "stale_action", "cross_coach_contradiction", "overconfidence")

# Numeric claims compared across coaches (check 4). #1658: `%` used to sit inside an
# alternation closed by `\b`; `%` is a non-word character, so `22%` followed by a space
# or end-of-string had no word boundary and NEVER matched — every percentage claim (body
# fat, adherence, recovery) was invisible to the contradiction check. `%` now terminates
# its own branch. No capturing groups: `findall` must return whole matches.
_NUMERIC_CLAIM_RE = re.compile(r"\b\d+(?:\.\d+)?\s*(?:mg/dL|bpm|ms|lbs?|kcal|g)\b|\b\d+(?:\.\d+)?\s*%")

# Definitive phrasing neither ORIENTATION nor EMERGING has earned (check 5). EMERGING_VOICE
# instructs 'Do NOT use definitive language like "your pattern is" or "this shows"' — until
# #1658 nothing checked it, so that rule was prompt-only (reference_prompt_structural_guarantees).
_UNEARNED_CONFIDENCE_PHASES = ("orientation", "emerging")
_CONFIDENT_PHRASES = (
    "your pattern shows",
    "this demonstrates",
    "clearly indicates",
    "the data confirms",
    "we can see that",
    "it's clear that",
    "definitively",
    "without question",
    "conclusively",
)


def validate_coach_output(coach_id: str, domain: str, narrative: str, inventory: dict, maturity: dict, all_narratives: dict = None) -> list:
    """
    Run all validation checks against a coach narrative.

    Returns list of flag dicts: {check, severity, detail, source_text}.
    """
    import re

    flags = []
    text_lower = narrative.lower()

    # ── Check 1: Null claim vs actual data ─────────────────────────────
    # #1658: scan EVERY occurrence of each phrase, not just the first. The old
    # `text_lower.index(phrase)` read only occurrence #1, so a narrative that said
    # "no data" once about a genuinely empty source and again about a source with 90
    # records was never flagged for the second — and the false claim later in a long
    # narrative is the one that ships.
    for phrase in _NULL_CLAIM_PHRASES:
        for match in re.finditer(re.escape(phrase), text_lower):
            idx = match.start()
            # Find the surrounding context (±50 chars)
            context = narrative[max(0, idx - 50) : idx + len(phrase) + 50]

            # Determine which domain the claim references
            for domain_kw, sources in _CLAIM_DOMAIN_MAP.items():
                if domain_kw in context.lower():
                    # Check if any of these sources actually have data
                    for src in sources:
                        src_info = inventory.get(src, {})
                        if src_info.get("exists") and src_info.get("records", 0) > 0:
                            flags.append(
                                {
                                    "check": "null_claim_vs_data",
                                    "severity": "error",
                                    "detail": (
                                        f"Coach claims '{domain_kw}' data is unavailable "
                                        f"but {src} has {src_info['records']} records "
                                        f"(latest: {src_info.get('latest', '?')})"
                                    ),
                                    "source_text": context.strip(),
                                }
                            )
                            break

    # ── Check 2: Stale action — asking for data that exists ───────────
    action_phrases = [
        "obtain a",
        "get a",
        "schedule a",
        "request a",
        "provide your",
        "submit your",
        "share your",
        "start logging",
        "begin tracking",
    ]
    for phrase in action_phrases:
        if phrase in text_lower:
            idx = text_lower.index(phrase)
            context = narrative[idx : idx + 80].lower()
            for domain_kw, sources in _CLAIM_DOMAIN_MAP.items():
                if domain_kw in context:
                    for src in sources:
                        if inventory.get(src, {}).get("exists"):
                            flags.append(
                                {
                                    "check": "stale_action",
                                    "severity": "error",
                                    "detail": (f"Coach suggests obtaining/providing '{domain_kw}' " f"but {src} data already exists"),
                                    "source_text": narrative[idx : idx + 80].strip(),
                                }
                            )
                            break

    # ── Check 3 (REMOVED, #1658) ──────────────────────────────────────
    # The "SOT violation" check was a no-op: it parsed the step count into a
    # discarded expression, confirmed garmin and apple_health both existed, and then
    # executed `pass` behind a "deferred to full implementation" comment. It could
    # not produce a flag, yet write_quality_results advertised checks_run=5 — a gate
    # reporting green while dark (the ADR-125/#1927 class). Deleted rather than
    # half-implemented; `_VALIDATOR_CHECKS` below is now the single source for the
    # advertised count, so it cannot drift from the checks that can actually fire.
    # Re-instating a real SOT comparison needs the cited figure checked against the
    # garmin metric values, which this function does not have.

    # ── Check 4: Cross-coach contradiction ────────────────────────────
    if all_narratives:
        # Extract numeric claims from this narrative
        this_numbers = set(_NUMERIC_CLAIM_RE.findall(narrative))
        for other_domain, other_text in all_narratives.items():
            if other_domain == domain:
                continue
            other_numbers = set(_NUMERIC_CLAIM_RE.findall(other_text))
            # Find numbers that appear in both but with different values for same unit
            # This is a simplified check — full implementation would parse metric+value pairs
            for num in this_numbers:
                unit = re.search(r"[a-zA-Z/%]+$", num)
                if unit:
                    unit_str = unit.group()
                    for other_num in other_numbers:
                        if other_num.endswith(unit_str) and other_num != num:
                            # Different value, same unit — potential contradiction
                            flags.append(
                                {
                                    "check": "cross_coach_contradiction",
                                    "severity": "warning",
                                    "detail": f"This coach cites {num}, {other_domain} coach cites {other_num}",
                                    "source_text": num,
                                }
                            )

    # ── Check 5: Overconfidence without data ──────────────────────────
    domain_maturity = maturity.get(domain, {})
    phase = domain_maturity.get("phase", "orientation")
    if phase in _UNEARNED_CONFIDENCE_PHASES:
        for phrase in _CONFIDENT_PHRASES:
            if phrase in text_lower:
                flags.append(
                    {
                        "check": "overconfidence",
                        "severity": "warning",
                        "detail": (
                            f"Coach uses definitive language '{phrase}' "
                            f"but is in {phase} phase ({domain_maturity.get('days', 0)} "
                            f"{domain_maturity.get('unit', 'days')} of data)"
                        ),
                        "source_text": phrase,
                    }
                )

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
        "checks_run": len(_VALIDATOR_CHECKS),  # #1658: derived, never a hand-typed count
        "errors": errors,
        "warnings": warnings,
        "flags": flags,
        "validated_at": datetime.now(timezone.utc).isoformat(),
    }

    try:
        # Convert floats to Decimal for DynamoDB
        clean = json.loads(json.dumps(item, default=str), parse_float=Decimal)
        table.put_item(Item=clean)
        logger.info("Quality results written: %s/%s — %d errors, %d warnings", coach_id, date, errors, warnings)
    except Exception as e:
        logger.error("Failed to write quality results: %s", e)


# ══════════════════════════════════════════════════════════════════════════════
# ACTION COMPLETION LOOP (Workstream 3)
# ══════════════════════════════════════════════════════════════════════════════
# #1658: `_load_detection_rules` and its two cache globals were deleted here. The
# action-completion detection loop that consumed config/action_detection_rules.json
# was removed by #1239; the loader had no caller anywhere in lambdas/ or mcp/ and
# shipped in every bundle (#781). Coach actions are still completed manually via
# `complete_action` — auto-detection would be a new feature, not a repair, so the
# dead loader is removed rather than left looking like a live path.


def _iso_week(date_str: str) -> str:
    """Convert YYYY-MM-DD to YYYY-WNN format."""
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    iso = dt.isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"


def get_open_actions(domain: str = None) -> list:
    """
    Query all open actions, optionally filtered by domain.

    Returns list of action dicts.
    """
    try:
        resp = table.query(
            **with_phase_filter(
                {
                    "KeyConditionExpression": (Key("pk").eq(f"USER#{USER_ID}") & Key("sk").begins_with("SOURCE#coach_actions#")),
                    "FilterExpression": "attribute_exists(#st) AND #st = :open",
                    "ExpressionAttributeNames": {"#st": "status"},
                    "ExpressionAttributeValues": {":open": "open"},
                }
            )
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
            **with_phase_filter(
                {
                    "KeyConditionExpression": (Key("pk").eq(f"USER#{USER_ID}") & Key("sk").begins_with("SOURCE#coach_actions#")),
                    "ScanIndexForward": False,
                }
            )
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


def complete_action(action_id: str, method: str = "manual", note: str = None) -> dict:
    """
    Mark an action as completed.

    Returns the updated action item dict.

    #1658: guarded with `attribute_exists(pk)`. DynamoDB `update_item` UPSERTS, so an
    unknown action id silently MINTED a SOURCE#coach_actions# row carrying nothing but
    status=completed + completion_date — a phantom completed action with no text, domain
    or issue date, which then flowed into get_action_history and the coach preamble. The
    accountability record could gain completions for work never assigned. A conditional
    failure now surfaces as the same raised exception every other write failure uses.
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
            ConditionExpression=Attr("pk").exists(),
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

    # Platform activity: Todoist tasks completed (ADR-058: phase=pilot filtered)
    platform_tasks = 0
    try:
        resp = table.query(
            **with_phase_filter(
                {
                    "KeyConditionExpression": Key("pk").eq(f"{USER_PREFIX}todoist") & Key("sk").between(f"DATE#{start}", f"DATE#{today}~"),
                }
            )
        )
        for item in resp.get("Items", []):
            # #2271: todoist records carry `completed_count` (the only name
            # todoist_lambda has ever written). The previous `tasks_completed`
            # read matched nothing, so this always fell through to the
            # len(item["tasks"]) fallback — which is itself a field no todoist
            # record carries, making the Builder's Paradox task count a
            # permanent measured zero.
            platform_tasks += int(item.get("completed_count", 0) or 0)
            # #2271: the former `tasks` fallback is deleted, not repaired. No
            # todoist record has ever carried a `tasks` key, and the branch
            # counted the LENGTH of an OPEN task list as tasks COMPLETED — a
            # latent inversion that would have inflated platform intensity the
            # moment anything started writing that name.
    except Exception as e:
        logger.warning("Builder's Paradox: Todoist query failed: %s", e)

    # Health signals (ADR-058: phase=pilot filtered)
    workouts = 0
    try:
        resp = table.query(
            **with_phase_filter(
                {
                    "KeyConditionExpression": Key("pk").eq(f"{USER_PREFIX}strava") & Key("sk").between(f"DATE#{start}", f"DATE#{today}~"),
                    "Select": "COUNT",
                }
            )
        )
        workouts = resp.get("Count", 0)
    except Exception:
        pass

    journal_entries = 0
    try:
        resp = table.query(
            **with_phase_filter(
                {
                    "KeyConditionExpression": Key("pk").eq(f"{USER_PREFIX}notion") & Key("sk").between(f"DATE#{start}", f"DATE#{today}~"),
                    "Select": "COUNT",
                }
            )
        )
        journal_entries = resp.get("Count", 0)
    except Exception:
        pass

    habit_adherence_pct = 0
    habit_days = 0  # #1658 (ADR-105): the n behind habit_adherence_pct
    step_days = 0  # #1658 (ADR-105): the n behind avg_steps
    try:
        resp = table.query(
            **with_phase_filter(
                {
                    "KeyConditionExpression": Key("pk").eq(f"{USER_PREFIX}habitify") & Key("sk").between(f"DATE#{start}", f"DATE#{today}~"),
                }
            )
        )
        items = resp.get("Items", [])
        pcts = []
        for item in items:
            p = item.get("completion_pct") or item.get("tier0_pct")
            if p is not None:
                pcts.append(float(p) * (100 if float(p) <= 1 else 1))
        if pcts:
            habit_adherence_pct = round(sum(pcts) / len(pcts))
            habit_days = len(pcts)  # #1658: ADR-105 — publish n, don't discard it
    except Exception:
        pass

    avg_steps = 0
    try:
        resp = table.query(
            **with_phase_filter(
                {
                    "KeyConditionExpression": Key("pk").eq(f"{USER_PREFIX}garmin") & Key("sk").between(f"DATE#{start}", f"DATE#{today}~"),
                }
            )
        )
        # #1658: filter on PRESENCE, not truth. `if i.get("steps")` is falsy for a
        # genuine 0-step day, so sedentary days were dropped from the mean instead of
        # pulling it down — a week with two zero days reported the average of the
        # active ones, systematically flattering the health side of the ratio.
        step_vals = []
        for i in resp.get("Items", []):
            if "steps" not in i:
                continue
            try:
                step_vals.append(float(i["steps"]))
            except (TypeError, ValueError):
                continue
        if step_vals:
            avg_steps = round(sum(step_vals) / len(step_vals))
            step_days = len(step_vals)
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
    # #1658 (ADR-104): a total absence of observations used to be mapped to score=50,
    # which lands in the 'tipping' band and printed "Platform activity is outpacing
    # health behaviors — watch this trend" alongside "0 platform tasks completed, 0
    # workouts". That is a behavioural verdict derived from no behaviour. Absence now
    # stays absent: no score, an explicit label, and no trend sentence.
    no_observations = (health_score + platform_intensity) == 0
    if no_observations:
        score = None
        label = "insufficient_data"
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
        f"{journal_entries} journal entries, {habit_adherence_pct}% habit adherence "
        f"(n={habit_days} days), {avg_steps} avg steps (n={step_days} days)."
    )
    if no_observations:
        interpretation += " No platform OR health activity was observed in this window — not enough to score."
    elif score > 50:
        interpretation += " The platform is consuming the time and energy it was designed to protect."
    elif score > 30:
        interpretation += " Platform activity is outpacing health behaviors — watch this trend."
    else:
        interpretation += " Health behaviors are keeping pace with platform work — balanced."

    return {
        "score": score,
        "label": label,
        "platform_tasks": platform_tasks,
        "workouts": workouts,
        "journal_entries": journal_entries,
        "habit_adherence_pct": habit_adherence_pct,
        "habit_days": habit_days,  # #1658 (ADR-105): n behind habit_adherence_pct
        "avg_steps": avg_steps,
        "step_days": step_days,  # #1658 (ADR-105): n behind avg_steps
        "health_score": round(health_score),
        "platform_intensity": round(platform_intensity),
        "interpretation": interpretation,
    }


# ══════════════════════════════════════════════════════════════════════════════
# MOVEMENT HONESTY GUARD (WORKORDER DI-1.3)
# ══════════════════════════════════════════════════════════════════════════════
# Mirrors the readiness future-stamp guard (tools_health.tool_get_readiness_score,
# is_forward_dated / staleness_warning): when the movement sources can't see the
# activity, output "not assessable + which source + why" instead of a confident
# "under-training / sedentary." Hevy is the authoritative training-stimulus signal
# and is reported regardless; the verdict that's withheld is only the NEAT/aerobic
# one that depends on the unavailable sources. Correlational framing only.

# Strava is authoritative for *what moved* (TRAINING_CALIBRATION §4a) — it carries the
# aerobic/NEAT dose. Garmin is a redundant backstop and steps systematically undercount,
# so aerobic/NEAT volume is "assessable" iff Strava is live. A state not in this set is
# treated as unavailable (paused / stale / rate_limited / missing).
_MOVEMENT_LIVE_STATES = {"live", "fresh", "ok", "current", None}
# Movement sources surfaced in the unavailability note, in priority order.
_MOVEMENT_NOTE_SOURCES = ("strava", "garmin", "steps")
# C-4 (#494): INGEST_HEALTH sentinel statuses (ingest_health.evaluate_source_health)
# that mean the ingestion pipe *ran and completed its fetch without error* — i.e. the
# source is confirmed live regardless of whether it returned any new records. Only "ok"
# qualifies: "unknown" (no sentinel yet), "stale" (cron stopped), and "failing" (running
# but erroring) all leave breakage-vs-rest ambiguous, so they must NOT unlock the verdict.
_PIPE_HEALTHY_STATUSES = {"ok"}


def _pipe_confirmed_live(ingest_health: dict, source: str) -> bool:
    """True iff `source`'s INGEST_HEALTH sentinel status is a confirmed-live one.

    ingest_health: {source: status} where status is the ingest_health.evaluate_source_health
    verdict ('ok'|'stale'|'failing'|'unknown'). Missing/None ⇒ not confirmed (conservative).
    """
    return (ingest_health or {}).get(source) in _PIPE_HEALTHY_STATUSES


# Language the guard withholds when movement isn't assessable.
_UNDERTRAINING_PATTERN = re.compile(
    r"under[-\s]?train|over[-\s]?rest|sedentary|too (?:few|little) (?:workouts|training|activity|movement)"
    r"|not (?:training|moving|active) enough|low (?:training )?(?:stimulus|activity|volume|dose)"
    r"|lack(?:ing|s)? (?:of )?(?:training|activity|movement|exercise)|insufficient (?:training|activity|stimulus)"
    r"|barely (?:training|moving|active)|(?:all|mostly) rest days|detrain",
    re.IGNORECASE,
)


def _movement_state_label(state) -> str:
    """Human label for a source state ('rate_limited' → 'rate-limited')."""
    return str(state).replace("_", "-")


def movement_assessability(source_states: dict, ingest_health: dict | None = None) -> dict:
    """Is the NEAT/aerobic movement picture assessable, given per-source states?

    source_states: {"strava": "paused"|"stale"|"live", "garmin": "rate_limited"|...,
    "steps": "missing"|"live", ...}.
    ingest_health: {source: INGEST_HEALTH status} ('ok'|'stale'|'failing'|'unknown') from
    ingest_health.evaluate_source_health. Optional — omitted ⇒ the conservative records-only
    read (a non-live Strava withholds the verdict, as before C-4).

    Returns {assessable, assessable_as_rest, unavailable, note, rest_note}.

    C-4 (#494) — behavioral rest vs. pipe breakage. Strava is the authoritative aerobic/NEAT
    source (§4a); a non-live Strava means no fresh records. That has two very different causes:
      - the ingestion pipe is DOWN (auth/throttle/cron) — volume genuinely can't be read, and a
        confident under-training verdict would be a lie ⇒ NOT assessable (withhold).
      - the pipe is HEALTHY ('ok' sentinel: it ran, fetched, returned an empty set) — that IS
        genuine behavioral rest, honestly assessable AS REST ⇒ assessable_as_rest, verdict
        available (framed "no activity logged, pipe confirmed live").
    Before C-4 both collapsed to "not assessable", gagging the coach through real quiet stretches.
    """
    states = source_states or {}
    unavailable = []
    for src in _MOVEMENT_NOTE_SOURCES:
        st = states.get(src, "live")
        if st not in _MOVEMENT_LIVE_STATES:
            unavailable.append((src, _movement_state_label(st)))
    strava_live = states.get("strava", "live") in _MOVEMENT_LIVE_STATES
    # No fresh Strava records, but its ingestion pipe is confirmed live → behavioral rest.
    assessable_as_rest = (not strava_live) and _pipe_confirmed_live(ingest_health, "strava")
    assessable = strava_live or assessable_as_rest
    note = ""
    rest_note = ""
    if assessable_as_rest:
        if unavailable:
            pretty = "; ".join(f"{s}: no activity logged" for s, _ in unavailable)
            rest_note = (
                f"no movement logged ({pretty}) — ingestion pipe confirmed live (INGEST_HEALTH ok), "
                "so this is genuine behavioral rest, not a data gap"
            )
        else:
            rest_note = (
                "no movement logged — ingestion pipe confirmed live (INGEST_HEALTH ok), "
                "so this is genuine behavioral rest, not a data gap"
            )
    elif unavailable:
        pretty = "; ".join(f"{s}: {st}" for s, st in unavailable)
        note = f"movement sources unavailable ({pretty})"
    return {
        "assessable": assessable,
        "assessable_as_rest": assessable_as_rest,
        "unavailable": unavailable,
        "note": note,
        "rest_note": rest_note,
    }


def apply_movement_honesty_guard(position_summary: str, assessability: dict, hevy_present: bool = False, hevy_summary: str = "") -> str:
    """Withhold an under-training/sedentary verdict when movement isn't assessable.

    If the picture IS assessable — Strava live, OR no records but the pipe is confirmed
    live so it's genuine behavioral rest (assessable_as_rest, C-4/#494) — the text is
    returned unchanged (the honest under-training/rest verdict is allowed to stand). If it
    is NOT assessable and the summary asserts under-training/sedentary, that verdict is
    replaced with an honest statement that (a) reports the Hevy training that did happen
    and (b) names the unavailable sources + why, withholding the verdict. A summary that
    makes no such assertion is returned unchanged (nothing false to withhold).
    """
    if not assessability or assessability.get("assessable", True):
        return position_summary
    text = position_summary or ""
    if not _UNDERTRAINING_PATTERN.search(text):
        return text
    note = (assessability.get("note") or "movement sources unavailable").rstrip(".")
    parts = []
    if hevy_present:
        parts.append(
            f"Logged training this period: {hevy_summary}." if hevy_summary else "Strength training was logged this period (Hevy)."
        )
    parts.append(
        f"{note} — so NEAT/aerobic volume is not assessable; I'm not making a training-adequacy call until those sources are live again."
    )
    return " ".join(parts)


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


# #1658: Limit-before-Filter paging for the phase-filtered thread read. Over-fetch per
# page so a run of pilot-tagged rows can't hide the live entries behind them, and cap
# the walk so a partition of nothing but filtered-out rows can't spin.
_THREAD_PAGE_OVERFETCH = 4
_THREAD_MAX_PAGES = 5


def read_coach_thread(coach_id: str, limit: int = 4) -> list:
    """Read recent thread entries for prompt injection.

    Returns list of thread entries, most recent first.

    #1658 / #1203: this read pairs `Limit` with the ADR-058 phase FilterExpression, and
    DynamoDB applies Limit BEFORE the filter — the same mechanism build_data_inventory
    documents. When the newest `limit` rows are pilot-tagged (i.e. every cycle reset)
    the single-shot read returned fewer rows than exist, or none at all, while live
    entries sat just past the page; build_thread_prompt_block then told a coach with
    months of history "This is your first assessment". So page until `limit` VISIBLE
    rows are collected, over-fetching per page and bounded by _THREAD_MAX_PAGES.
    """
    try:
        collected: list = []
        start_key = None
        for _page in range(_THREAD_MAX_PAGES):
            params = with_phase_filter(
                {  # ADR-058
                    "KeyConditionExpression": Key("pk").eq(f"USER#{USER_ID}") & Key("sk").begins_with(f"SOURCE#coach_thread#{coach_id}#"),
                    "ScanIndexForward": False,
                    "Limit": max(1, limit) * _THREAD_PAGE_OVERFETCH,
                }
            )
            if start_key is not None:
                params["ExclusiveStartKey"] = start_key
            resp = table.query(**params)
            collected.extend(resp.get("Items", []))
            start_key = resp.get("LastEvaluatedKey")
            if len(collected) >= limit or not start_key:
                break
        return [_decimal_to_float(i) for i in collected[:limit]]
    except Exception as e:
        logger.warning("Failed to read thread for %s: %s", coach_id, e)
        return []


def update_prediction_status(coach_id: str, prediction_id: str, status: str, outcome_note: str = None) -> bool:
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
            parts.append(f'Week {week} position: "{pos}"')

        for pred in entry.get("predictions", []):
            status = pred.get("status", "pending")
            text = pred.get("text", "")
            conf = pred.get("confidence", "medium")
            status_note = f" — {pred.get('outcome_note', '')}" if pred.get("outcome_note") else ""
            parts.append(f'Week {week} prediction ({conf} confidence): "{text}" ({status.upper()}{status_note})')

        for surprise in entry.get("surprises", []):
            parts.append(f'Week {week} surprise: "{surprise}"')

        for change in entry.get("stance_changes", []):
            parts.append(
                f"Week {week} stance change: \"{change.get('from', '')}\" → \"{change.get('to', '')}\" (reason: {change.get('reason', '')})"
            )

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
        '- Reference your previous positions naturally. "Last week I flagged [X] — here\'s what happened."\n'
        '- If a prediction resolved: explicitly call it out. "I predicted [X]. I was [right/wrong]."\n'
        '- If your position changed: own it. "I initially thought [X] but the data now suggests [Y]."\n'
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


def _prediction_slug(text: str) -> str:
    """Deterministic semantic slug for a prediction claim (the dedup key).

    Claims of 40 characters or fewer keep the exact construction the canonical
    COACH#/PREDICTION# path uses (coach_state_updater.py), so short claims still read
    the same identity in both prediction stores.

    #1658: longer claims additionally carry a digest of the FULL text. The bare
    `[:40]` truncation collapsed two distinct forecasts sharing a 40-character prefix
    ("Your resting heart rate will fall below 55 bpm" vs "…below 60 bpm") onto one
    semantic_key, and `stamped[key] = rec` in stamp_thread_predictions then silently
    dropped the first — a forecast the coach actually made was never recorded and
    never graded. The digest is a pure function of the text, so the key stays stable
    across days; only long-form claims get a different key than before.
    """
    t = (text or "").lower()
    base = re.sub(r"[^a-z0-9]+", "_", t[:40]).strip("_")
    if not base or len(t) <= 40:
        return base
    return f"{base}_{hashlib.sha256(t.encode('utf-8')).hexdigest()[:6]}"


def _timeframe_to_window_days(timeframe: str) -> int:
    """Map a natural-language horizon ('in 2 weeks', 'by next month') to a
    strictly-positive evaluation window in days. Mirrors coach_state_updater's
    mapping; defaults to 14 so a metric-bearing claim is always gradeable."""
    tf = (timeframe or "").lower()
    if not tf:
        return 14
    if "month" in tf:
        m = re.search(r"(\d+)", tf)
        return int(m.group(1)) * 30 if m else 30
    if "week" in tf:
        m = re.search(r"(\d+)", tf)
        return int(m.group(1)) * 7 if m else 7
    if "day" in tf:
        m = re.search(r"(\d+)", tf)
        return int(m.group(1)) if m else 14
    return 14


def stamp_thread_predictions(coach_id: str, raw_predictions: list, today: str = None) -> list:
    """Code-stamp prediction identity + target date (ADR-106: only code ships).

    The LLM authors claim text, confidence, an optional metric and an optional
    natural timeframe — never `prediction_id` or `target_date`. This function:
      • strips any model-authored id/date (defensive — the schema no longer asks),
      • stamps `prediction_id = pred_{today}_{semantic-slug}` and a strictly-future
        `target_date` (today + timeframe window) so no record is ungradeable-by-
        construction whenever a metric is present,
      • carries an open prior prediction forward on a matching `semantic_key` so
        daily re-emission of the same claim UPDATES one record instead of minting
        a new duplicate every day (the `pred_2024…` vs `pred_2025…` inflation bug).

    Returns the cleaned prediction list (deduped within the batch by semantic_key).
    """
    today = today or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    day_compact = today.replace("-", "")

    # Prior OPEN predictions by semantic key — so a re-emitted claim reuses its
    # original id + target_date (a stable deadline) rather than resetting daily.
    prior_open = {}
    try:
        for entry in read_coach_thread(coach_id, limit=10):
            for p in entry.get("predictions", []):
                key = p.get("semantic_key") or _prediction_slug(p.get("text", ""))
                if key and p.get("status", "pending") == "pending" and key not in prior_open:
                    prior_open[key] = p
    except Exception as e:  # read is best-effort; a fresh stamp is always valid
        logger.warning("prior-prediction lookup failed for %s: %s", coach_id, e)

    stamped = {}
    for pred in raw_predictions or []:
        text = (pred.get("text") or "").strip()
        if not text:
            continue
        key = _prediction_slug(text)
        if not key:
            continue
        metric = (pred.get("metric") or "").strip() or None
        confidence = pred.get("confidence") or "medium"

        window = _timeframe_to_window_days(pred.get("timeframe", ""))
        target = (datetime.strptime(today, "%Y-%m-%d") + timedelta(days=max(1, window))).strftime("%Y-%m-%d")

        carried = prior_open.get(key)
        if carried:
            # Update in place: keep the original id + deadline, refresh confidence/metric.
            # #1658: a prior written before #725 carries no target_date, and
            # `carried.get("target_date")` then stamped target_date=None — ungradeable,
            # permanently pending, and re-carried every day forever, inflating
            # predictions_total. Re-stamp a missing deadline from today's timeframe.
            # And first_seen is NOT back-filled from target_date any more: that is a
            # FUTURE date, so "first seen" read later than the deadline it precedes.
            # An unknown first_seen stays honestly unknown (None).
            rec = {
                "prediction_id": carried.get("prediction_id") or f"pred_{day_compact}_{key}",
                "semantic_key": key,
                "text": text,
                "confidence": confidence,
                "metric": metric,
                "target_date": carried.get("target_date") or target,
                "first_seen": carried.get("first_seen"),
                "status": "pending",
                "reaffirmed_on": today,
            }
        else:
            rec = {
                "prediction_id": f"pred_{day_compact}_{key}",
                "semantic_key": key,
                "text": text,
                "confidence": confidence,
                "metric": metric,
                "target_date": target,  # strictly future by construction
                "first_seen": today,
                "status": "pending",
            }
        stamped[key] = rec  # dedup within-batch by semantic key
    return list(stamped.values())


def extract_thread_from_narrative(coach_id: str, narrative: str, api_key: str) -> dict:
    """Extract thread data from a coach's generated narrative via a lightweight API call.

    Makes a Haiku-class call to parse: position_summary, predictions, surprises,
    emotional_investment_level, open_questions. Prediction identity + target dates
    are stamped in code (ADR-106) — see stamp_thread_predictions.
    """
    import urllib.request

    prompt = f"""Extract structured thread data from this coach narrative. Return ONLY valid JSON.

NARRATIVE:
{narrative[:2000]}

Extract:
{{
  "position_summary": "2-3 sentence summary of the coach's current stance/assessment",
  "predictions": [
    {{"text": "the prediction in natural language", "confidence": "low|medium|high", "metric": "optional metric to check", "timeframe": "optional natural horizon, e.g. 'in 2 weeks' or 'by next month'"}}
  ],
  "surprises": ["things that surprised the coach — empty list if nothing surprising"],
  "emotional_investment": "detached|observing|engaged|invested|concerned|excited",
  "open_questions": ["things the coach is curious about or watching"]
}}

Rules:
- position_summary: what does the coach believe RIGHT NOW about their domain for Matthew? Write it AS the coach, in first person ("I'm noticing...", "I'd expect...") — never refer to the coach in third person (do not write "the coach believes..." or "the sleep coach is...").
- predictions: only include explicit forward-looking claims. Not observations. State the claim, a confidence, an optional metric, and an optional timeframe. Do NOT invent an ID or a calendar date — the system stamps prediction_id and target_date in code.
- emotional_investment: infer from language intensity. Academic/measured = observing. Strong opinions = invested. Worry = concerned.
- If nothing fits a field, use empty list or "observing" default."""

    try:
        model = os.environ.get("AI_MODEL_HAIKU", "claude-haiku-4-5-20251001")
        os.environ.get("AI_SECRET_NAME", "life-platform/ai-keys")

        # Use provided API key
        req_body = json.dumps(
            {
                "model": model,
                "max_tokens": 500,
                "messages": [{"role": "user", "content": prompt}],
            }
        )

        req = urllib.request.Request(
            "https://api.anthropic.com/v1/messages",
            data=req_body.encode(),
            headers={
                "Content-Type": "application/json",
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
            },
        )

        # Phase 3.4 (2026-05-16): retry via retry_utils (4 attempts, 5/15/45s).
        from common.retry_utils import call_anthropic_raw

        result = call_anthropic_raw(req, timeout=30)

        text = "".join(b["text"] for b in result.get("content", []) if b.get("type") == "text")

        # Parse JSON
        cleaned = text.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[1] if "\n" in cleaned else cleaned[3:]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
        parsed = json.loads(cleaned.strip())
        # ADR-106: code owns prediction identity + target dates, never the model.
        parsed["predictions"] = stamp_thread_predictions(coach_id, parsed.get("predictions", []))
        # #1987: deterministic voice-register check (zero AI cost), sibling to the
        # anti-pattern check in coach_state_updater.py. Strips markdown emphasis
        # unconditionally; if what's left is still third-person coach register,
        # reject and fall back to the same truncated-narrative text the except
        # block below already uses on a hard parse failure — no new control flow.
        summary, register_rejected = sanitize_summary(parsed.get("position_summary"))
        if register_rejected:
            logger.warning("position_summary rejected for %s (third-person coach register) — falling back to narrative", coach_id)
        # #2343: sibling write path, same defect class — a derived summary that drops the
        # night its source attached to a vital. Both rejections take the same fallback.
        summary = guard_derived_summary(summary, narrative, "position_summary", coach_id, logger)
        parsed["position_summary"] = summary or truncate_at_word(narrative, 200)  # #1224: word boundary
        return parsed

    except Exception as e:
        logger.warning("Thread extraction failed for %s: %s — using defaults", coach_id, e)
        return {
            "position_summary": truncate_at_word(narrative, 200),  # #1224: word boundary, no mid-word cut
            "predictions": [],
            "surprises": [],
            "emotional_investment": "observing",
            "open_questions": [],
        }


# ══════════════════════════════════════════════════════════════════════════════
# CREDIBILITY SCORES (V2.2 Workstream 4)
# ══════════════════════════════════════════════════════════════════════════════

# Short-form coach ids (the intelligence layer's thread vocabulary) — the SAME
# roster as coach.persona_registry, just without the `_coach` suffix, so it is
# derived from the registry's own short-id projection rather than re-typed
# (#2334; guard: tests/test_coach_roster_set_guard_2334.py).
from coach.persona_registry import OPERATIONAL_SHORT_IDS

COACH_IDS_ALL = list(OPERATIONAL_SHORT_IDS)


def compute_credibility(coach_id: str) -> dict:
    """Compute a coach's credibility from its prediction track record (#538).

    Now backed by a real Brier score + reliability curve (via the shared
    `calibration_core` scorer) instead of a bare accuracy-% with a hand-rolled
    "≥3 high-confidence" check. Same source (the coach thread's resolved
    predictions), same return contract, plus `brier`/`brier_skill`/`reliability_bins`
    so every credibility surface reads the same calibration numbers.

    Returns: {score, label, accuracy_pct, calibration, brier, brier_skill,
    reliability_bins, predictions_total, predictions_resolved, confirmed, refuted, pending}
    """
    entries = read_coach_thread(coach_id, limit=20)

    all_preds = []
    for entry in entries:
        for pred in entry.get("predictions", []):
            all_preds.append(pred)

    # One scorer: extract (stated_confidence, outcome) pairs and grade them. The
    # thread predictions carry word confidences ("high") — calibration_core normalizes
    # those onto the same [0,1] axis as the coach engine's numeric confidence.
    pairs = calibration_core.pairs_from_prediction_records(all_preds)
    summary = calibration_core.score_pairs(pairs)
    pending = [p for p in all_preds if p.get("status") == "pending"]

    return {
        "score": summary["score"],
        "label": summary["label"],
        "accuracy_pct": summary["accuracy_pct"] if summary["accuracy_pct"] is not None else 0,
        "calibration": summary["calibration"],
        "brier": summary["brier"],
        "brier_skill": summary["brier_skill"],
        "reliability_bins": summary["reliability_bins"],
        "predictions_total": len(all_preds),
        "predictions_resolved": summary["n"],
        "confirmed": summary["confirmed"],
        "refuted": summary["refuted"],
        "pending": len(pending),
    }


def load_credibility(coach_id: str) -> dict:
    """Load cached credibility score for a coach."""
    try:
        resp = table.get_item(Key={"pk": f"USER#{USER_ID}", "sk": f"SOURCE#coach_credibility#{coach_id}"})
        item = resp.get("Item")
        return _decimal_to_float(item) if item else {"label": "nascent", "score": 30}
    except Exception:
        return {"label": "nascent", "score": 30}
