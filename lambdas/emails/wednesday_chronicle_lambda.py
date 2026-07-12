"""
Wednesday Chronicle Lambda — v1.1.0 (Board Centralization)
"The Measured Life" by Elena Voss
Fires Wednesday 7:00 AM PT (15:00 UTC via EventBridge).

A fictional journalist embedded with Matthew writes a weekly ~1,200-1,800 word
narrative journalism installment chronicling his P40 transformation journey.
She has unfettered access to all data including journal entries (deep background,
never quoted directly). Occasionally interviews Board of Directors members.

Each installment is:
  1. Emailed as a newsletter
  2. Published to the v4 journal (generated/journal/, /story/chronicle/)
  3. Stored in DynamoDB for continuity (last 4 installments fed to AI)

AI Model: Sonnet 4.5 (temperature 0.6 for creative voice)
Cost: ~$0.04/week (~$0.16/month)

v1.1.0: Elena's persona + Board interview descriptions dynamically built from
        s3://matthew-life-platform/config/board_of_directors.json
        Falls back to hardcoded _FALLBACK_ELENA_PROMPT if S3 config unavailable.
"""

import json
import logging
import os
import re
import secrets as _secrets
from datetime import datetime, timedelta, timezone

import boto3
import digest_utils  # shared query_range implementations (#970)
import privacy_guard  # deterministic real-name + vice gate (layer module)
from ai_context import build_experiment_phase_context, format_experiment_phase_context  # #1086: mandatory phase block
from constants import EXPERIMENT_BASELINE_WEIGHT_LBS, EXPERIMENT_START_DATE  # ADR-058
from phase_filter import singleton_visible  # ADR-058 / #946 (query paths get the phase filter via digest_utils, #970)

# OBS-1: Structured logger (wired below after optional imports)
_logger_std = logging.getLogger()
_logger_std.setLevel(logging.INFO)

REGION = os.environ.get("AWS_REGION", "us-west-2")
TABLE_NAME = os.environ.get("TABLE_NAME", "life-platform")
S3_BUCKET = os.environ["S3_BUCKET"]
USER_ID = os.environ.get("USER_ID", "matthew")
RECIPIENT = os.environ["EMAIL_RECIPIENT"]
SENDER = os.environ["EMAIL_SENDER"]
# #548: Margaret Calloway's red pen — the Haiku model for her critique + revision
# calls (kept cheap and separate from Elena's Sonnet narrative voice, ADR-063 budget).
AI_MODEL_HAIKU = os.environ.get("AI_MODEL_HAIKU", "claude-haiku-4-5-20251001")

# FEAT-12: Preview-before-publish workflow.
# When PREVIEW_MODE=true (default), the Chronicle is stored as a draft in DynamoDB
# and a preview email is sent to RECIPIENT with Approve / Request Changes links.
# No content is published to S3 until Matthew approves via the chronicle-approve Lambda.
PREVIEW_MODE = os.environ.get("PREVIEW_MODE", "true").lower() == "true"
APPROVE_LAMBDA_URL = os.environ.get("APPROVE_LAMBDA_URL", "")  # Function URL of chronicle-approve

USER_PREFIX = f"USER#{USER_ID}#SOURCE#"

dynamodb = boto3.resource("dynamodb", region_name=REGION)
table = dynamodb.Table(TABLE_NAME)
ses = boto3.client("sesv2", region_name=REGION)
s3 = boto3.client("s3", region_name=REGION)
secrets = boto3.client("secretsmanager", region_name=REGION)

# Board of Directors config loader
try:
    import board_loader

    _HAS_BOARD_LOADER = True
except ImportError:
    _HAS_BOARD_LOADER = False

try:
    import insight_writer

    insight_writer.init(table, USER_ID)
    _HAS_INSIGHT_WRITER = True
except ImportError:
    _HAS_INSIGHT_WRITER = False

# AI-3: Output validation
try:
    from ai_output_validator import AIOutputType, validate_ai_output

    _HAS_AI_VALIDATOR = True
except ImportError:
    _HAS_AI_VALIDATOR = False

# BS-05: Confidence badge
try:
    from digest_utils import _confidence_badge, compute_confidence

    _HAS_CONFIDENCE = True
except ImportError:
    _HAS_CONFIDENCE = False

    def _confidence_badge(level):
        return ""


# #405: the per-chronicle share kit (email-stack module — text/JSON only, no Pillow/AI).
try:
    import chronicle_share_kit

    _HAS_SHARE_KIT = True
except ImportError:
    _HAS_SHARE_KIT = False


# OBS-1: Structured logger
try:
    from platform_logger import get_logger

    logger = get_logger("wednesday-chronicle")
except ImportError:
    import logging as _log

    logger = _log.getLogger("wednesday-chronicle")
    logger.setLevel(_log.INFO)


# ══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════════════════════


from digest_utils import d2f, safe_float  # shared bundled helpers (#970)


def query_range(source, start_date, end_date):
    """Batch query all records for a source in a date range, as a {date: record} dict.

    Shared paginated, phase-scoped implementation (digest_utils, #970).
    """
    return digest_utils.query_range(table, source, start_date, end_date, user_id=USER_ID)


def query_range_list(source, start_date, end_date):
    """Like query_range but returns a flat list, preserving duplicates (per-workout
    schemas like Hevy, #485). Shared paginated implementation (digest_utils, #970)."""
    return digest_utils.query_range_list(table, source, start_date, end_date, user_id=USER_ID)


def fetch_profile():
    from intelligence_common import fetch_profile as _shared_fetch_profile

    return _shared_fetch_profile(table, USER_ID)


# ══════════════════════════════════════════════════════════════════════════════
# DATA GATHERING
# ══════════════════════════════════════════════════════════════════════════════


def gather_chronicle_data():
    """Gather all data Elena needs for this week's installment."""
    today = datetime.now(timezone.utc).date()
    end = (today - timedelta(days=1)).isoformat()  # yesterday
    start = (today - timedelta(days=7)).isoformat()  # 7 days back
    weight_start = (today - timedelta(days=30)).isoformat()

    profile = fetch_profile()
    if not profile:
        logger.error("No profile found")
        return None

    logger.info(f"Gathering data: {start} -> {end}")

    # --- Core biometrics ---
    whoop = query_range("whoop", start, end)
    eightsleep = query_range("eightsleep", start, end)
    garmin = query_range("garmin", start, end)
    strava = query_range("strava", start, end)
    withings = query_range("withings", weight_start, end)
    macrofactor = query_range("macrofactor", start, end)
    apple_health = query_range("apple_health", start, end)

    # --- Journal entries (the soul of each installment) ---
    # Journal entries use SK pattern: DATE#YYYY-MM-DD#journal#template#uuid
    journal_entries = query_range_list("notion", start, end)
    # Filter to only journal entries (not other notion records)
    journal_entries = [e for e in journal_entries if "#journal#" in e.get("sk", "")]
    logger.info(f"Journal entries: {len(journal_entries)}")

    # --- Day grades + habit scores ---
    day_grades = query_range("day_grade", start, end)
    habit_scores = query_range("habit_scores", start, end)

    # --- Habits raw (for specific habit names) ---
    habitify = query_range("habitify", start, end)

    # --- State of Mind ---
    # SoM daily aggregates (som_avg_valence, som_top_labels/associations) live on
    # the apple_health partition; keep only days that carry a SoM aggregate.
    state_of_mind = {d: rec for d, rec in query_range("apple_health", start, end).items() if rec.get("som_avg_valence") is not None}

    # --- Supplements ---
    supplements = query_range("supplements", start, end)

    # --- Active experiments ---
    experiments = []
    try:
        # ADR-058: phase=pilot hidden by default.
        from phase_filter import with_phase_filter

        resp = table.query(
            **with_phase_filter(
                {
                    "KeyConditionExpression": "pk = :pk AND begins_with(sk, :prefix)",
                    "ExpressionAttributeValues": {
                        ":pk": f"USER#{USER_ID}#SOURCE#experiments",
                        ":prefix": "EXP#",
                    },
                }
            )
        )
        for item in resp.get("Items", []):
            exp = d2f(item)
            if exp.get("status") == "active":
                experiments.append(exp)
    except Exception as e:
        logger.warning(f"Experiments query: {e}")

    # --- Anomaly events ---
    anomalies = query_range("anomalies", start, end)

    # --- Weather (for setting/atmosphere) ---
    weather = query_range("weather", start, end)

    # --- Character Sheet (gamification layer — narrative hooks for Elena) ---
    character_sheet = query_range("character_sheet", start, end)
    logger.info(f"Character sheet records: {len(character_sheet)}")

    # --- Previous 4 installments (for continuity) ---
    prev_installments = []
    try:
        # ADR-058: phase=pilot hidden by default.
        from phase_filter import with_phase_filter

        resp = table.query(
            **with_phase_filter(
                {
                    "KeyConditionExpression": "pk = :pk AND begins_with(sk, :prefix)",
                    "ExpressionAttributeValues": {
                        ":pk": f"USER#{USER_ID}#SOURCE#chronicle",
                        ":prefix": "DATE#",
                    },
                    "ScanIndexForward": False,
                    # Read past the phase=pilot dormant records (which with_phase_filter drops)
                    # to reach the low-SK re-dated origin lead-ins, so the genuine prior
                    # installments feed continuity instead of being missed (2026-06-21).
                    "Limit": 25,
                }
            )
        )
        prev_installments = [d2f(i) for i in resp.get("Items", [])]
        logger.info(f"Previous installments: {len(prev_installments)}")
    except Exception as e:
        logger.warning(f"Previous installments: {e}")

    # --- Field Notes (current week's AI analysis + Matthew response) ---
    field_notes = None
    try:
        iso_year, iso_week, _ = today.isocalendar()
        current_week = f"{iso_year}-W{iso_week:02d}"
        fn_resp = table.get_item(
            Key={
                "pk": f"USER#{USER_ID}#SOURCE#field_notes",
                "sk": f"WEEK#{current_week}",
            }
        )
        fn_item = d2f(fn_resp.get("Item"))
        if fn_item and fn_item.get("ai_present"):
            field_notes = {
                "week": current_week,
                "ai_tone": fn_item.get("ai_tone", "mixed"),
                "ai_present": fn_item.get("ai_present", "")[:500],
                "has_matthew_response": bool(fn_item.get("matthew_agreement")),
                "matthew_agreement": (fn_item.get("matthew_agreement") or "")[:300],
            }
            logger.info(
                f"Field notes for {current_week}: tone={field_notes['ai_tone']}, matthew_responded={field_notes['has_matthew_response']}"
            )
    except Exception as e:
        logger.warning(f"Field notes query: {e}")

    # --- Narrative arc + experiment arc (the cross-week throughline) — for the
    # "previously on" recap. Both are already-summarized prose artifacts (never raw
    # vitals), so they ground a recap without re-introducing the fabrication frontier.
    narrative_arc = None
    experiment_arc = None
    arc_pk = "NARRATIVE#arc"  # platform singleton partition (not a USER#…#SOURCE# source)
    ai_pk = f"USER#{USER_ID}#SOURCE#ai_analysis"
    try:
        # #946: get_item bypasses the phase filter — hide a tombstoned arc, and
        # (since NARRATIVE#arc reuses `phase` for its NARRATIVE phase, the generic
        # singleton_visible check can't apply) an arc entered before the current
        # genesis: it's the previous cycle's story, not this recap's throughline.
        _arc_raw = d2f(table.get_item(Key={"pk": arc_pk, "sk": "STATE#current"}).get("Item") or {})
        if _arc_raw and not _arc_raw.get("tombstone") and str(_arc_raw.get("entered_date") or "") >= EXPERIMENT_START_DATE:
            narrative_arc = _arc_raw
    except Exception as e:
        logger.warning(f"Narrative arc query: {e}")
    try:
        _exp_arc_raw = table.get_item(Key={"pk": ai_pk, "sk": "EXPERT#experiment_arc"}).get("Item")
        if singleton_visible(_exp_arc_raw):  # #946: honest-null while tombstoned from a reset
            experiment_arc = d2f(_exp_arc_raw) or None
    except Exception as e:
        logger.warning(f"Experiment arc query: {e}")

    return {
        "whoop": whoop,
        "eightsleep": eightsleep,
        "garmin": garmin,
        "strava": strava,
        "withings": withings,
        "macrofactor": macrofactor,
        "apple_health": apple_health,
        "journal_entries": journal_entries,
        "day_grades": day_grades,
        "habit_scores": habit_scores,
        "habitify": habitify,
        "state_of_mind": state_of_mind,
        "supplements": supplements,
        "experiments": experiments,
        "anomalies": anomalies,
        "weather": weather,
        "character_sheet": character_sheet,
        "prev_installments": prev_installments,
        "narrative_arc": narrative_arc,
        "experiment_arc": experiment_arc,
        "profile": profile,
        "field_notes": field_notes,
        "dates": {"start": start, "end": end},
    }


# ══════════════════════════════════════════════════════════════════════════════
# DATA PACKET BUILDER (narrative-ready, not raw JSON)
# ══════════════════════════════════════════════════════════════════════════════


def build_data_packet(data):
    """Transform raw data into a narrative-ready packet for Elena."""
    profile = data["profile"]
    dates = data["dates"]
    packet = []

    packet.append("=== THE MEASURED LIFE — WEEKLY DATA PACKET ===")
    packet.append(f"Week ending: {dates['end']}")

    # --- Week number + phase context (#1086) ---
    # The ONE shared experiment-phase block replaces this surface's own week
    # math: same genesis anchor, identical week arithmetic (d days after
    # genesis → d//7 + 1 for both), plus the pre-start state, the audience
    # descriptor, and the cannot-exist-yet guardrail every narrative surface
    # now carries. Anchored to the week-ENDING date, not "today".
    pctx = build_experiment_phase_context(profile, dates["end"])
    journey_start = pctx["start_date"]
    # A pre-genesis lead-in still labels/publishes as week 1 — week_num feeds
    # filenames and DDB keys downstream, never the narrative clock (the phase
    # block + the TIMELINE guard below own that).
    week_num = pctx["week_num"] or 1
    packet.append(format_experiment_phase_context(pctx))

    # Week number is anchored to the experiment GENESIS (journey_start) — never the count of
    # installments. Pre-genesis "prologue" lead-ins (dated before genesis) are backstory and must
    # NOT inflate the experiment week or imply the weight loss / training spans more weeks than the
    # experiment has actually run (this caused the "9 lbs in three weeks" error on 2026-06-21, when
    # the experiment was one week old). Continuity (don't re-open cold) is handled by feeding Elena
    # the prior installments as context — not by bumping the week number.
    def _inst_date(p):
        return str(p.get("date") or p.get("sk", "")).replace("DATE#", "")

    prologue = [p for p in data.get("prev_installments", []) if _inst_date(p) and _inst_date(p) < journey_start]
    packet.append(f"Week number: {week_num}")
    packet.append(f"Journey start (experiment genesis): {journey_start}")
    if prologue:
        packet.append(
            f"TIMELINE — CRITICAL: {len(prologue)} earlier installment(s) are PRE-GENESIS PROLOGUE "
            f"(backstory dated before the {journey_start} genesis). They are NOT experiment weeks. "
            f"This is experiment WEEK {week_num}; the measured experiment is {week_num} week(s) old. "
            f"NEVER describe the experiment, the weight loss, the training load, or any streak as "
            f"spanning more weeks than that. Draw on the prologue for continuity and backstory, but "
            f"the measured clock — and any 'in N weeks' framing — starts at genesis."
        )
    # Matthew-specific fallback defaults; only used if profile fetch fails
    packet.append(f"Journey start weight: {profile.get('journey_start_weight_lbs', EXPERIMENT_BASELINE_WEIGHT_LBS)} lbs")
    packet.append(f"Goal weight: {profile.get('goal_weight_lbs', 185)} lbs")
    packet.append(f"Age: {profile.get('age', 37)}")
    packet.append("")

    # --- Weight story ---
    packet.append("=== WEIGHT ===")
    weights = []
    for d in sorted(data["withings"].keys()):
        w = safe_float(data["withings"][d], "weight_lbs")
        if w:
            weights.append((d, w))
    if weights:
        latest = weights[-1]
        packet.append(f"Current: {latest[1]:.1f} lbs ({latest[0]})")
        if len(weights) >= 2:
            earliest_7d = [w for w in weights if w[0] >= dates["start"]]
            if earliest_7d:
                delta = latest[1] - earliest_7d[0][1]
                packet.append(f"Week change: {delta:+.1f} lbs")
        journey_start_w = profile.get("journey_start_weight_lbs", EXPERIMENT_BASELINE_WEIGHT_LBS)  # Matthew-specific fallback
        total_lost = journey_start_w - latest[1]
        packet.append(f"Total journey loss: {total_lost:.1f} lbs")
    packet.append("")

    # --- Recovery & physiology ---
    packet.append("=== RECOVERY & PHYSIOLOGY ===")
    # Temporal frame for the narrator: each dated line is the reading FOR that
    # morning, produced by the night before — recovery/HRV set that day UP; they
    # are not something Matthew "did" on it. Reference them as "the night of"/"the
    # morning of", never as same-day activity.
    packet.append("(Frame: each line is that morning's reading, reflecting the prior night — it sets the day up.)")
    for d in sorted(data["whoop"].keys()):
        rec = data["whoop"][d]
        hrv = safe_float(rec, "hrv")
        recovery = safe_float(rec, "recovery_score")
        rhr = safe_float(rec, "resting_heart_rate")
        strain = safe_float(rec, "strain")
        parts = [f"{d}:"]
        if recovery is not None:
            parts.append(f"Recovery {recovery:.0f}%")
        if hrv is not None:
            parts.append(f"HRV {hrv:.0f}ms")
        if rhr is not None:
            parts.append(f"RHR {rhr:.0f}")
        if strain is not None:
            parts.append(f"Strain {strain:.1f}")
        packet.append(" | ".join(parts))
    packet.append("")

    # --- Sleep (Whoop — SOT for duration, stages, score — captures all sleep) ---
    packet.append("=== SLEEP (Whoop — source of truth) ===")
    # Wake-date keyed: a line dated D is the sleep of the night of D-1 → morning D.
    packet.append("(Frame: a line dated D is the night of D-1 into the morning of D — last night's sleep.)")
    for d in sorted(data["whoop"].keys()):
        rec = data["whoop"][d]
        score = safe_float(rec, "sleep_quality_score")
        dur = safe_float(rec, "sleep_duration_hours")
        eff = safe_float(rec, "sleep_efficiency_percentage")
        rem_h = safe_float(rec, "rem_sleep_hours")
        deep_h = safe_float(rec, "slow_wave_sleep_hours")
        deep_pct = round(deep_h / dur * 100, 0) if deep_h and dur and dur > 0 else None
        rem_pct = round(rem_h / dur * 100, 0) if rem_h and dur and dur > 0 else None
        parts = [f"{d}:"]
        if score is not None:
            parts.append(f"Score {score:.0f}")
        if dur is not None:
            parts.append(f"{dur:.1f}h")
        if eff is not None:
            parts.append(f"Eff {eff:.0f}%")
        if deep_pct is not None:
            parts.append(f"Deep {deep_pct:.0f}%")
        if rem_pct is not None:
            parts.append(f"REM {rem_pct:.0f}%")
        packet.append(" | ".join(parts))
    packet.append("")

    # --- Sleep Restlessness (Eight Sleep tosses/turns) ---
    # Bed/room temperature retired (ADR-118, #489): the Eight Sleep temperature
    # pipeline is dead (dead /v2/intervals endpoint, no temp field 4+ months).
    # Tosses/turns is still a live field, so keep it.
    packet.append("=== SLEEP RESTLESSNESS (Eight Sleep) ===")
    for d in sorted(data["eightsleep"].keys()):
        rec = data["eightsleep"][d]
        toss = safe_float(rec, "toss_and_turns") or safe_float(rec, "toss_turn_count")
        if toss is not None:
            packet.append(f"{d}: Tosses {toss:.0f}")
    packet.append("")

    # --- Training / Strava activities ---
    packet.append("=== TRAINING ===")
    for d in sorted(data["strava"].keys()):
        rec = data["strava"][d]
        activities = rec.get("activities", [])
        for a in activities:
            name = a.get("name", "Activity")
            sport = a.get("sport_type", "?")
            dur_min = round(safe_float(a, "moving_time_seconds", 0) / 60)
            dist_m = safe_float(a, "distance_meters", 0)
            dist_mi = round(dist_m / 1609.34, 2) if dist_m else 0
            avg_hr = safe_float(a, "average_heartrate")
            elev = safe_float(a, "total_elevation_gain_feet")
            start = a.get("start_date_local", "")
            time_part = start.split("T")[1][:5] if "T" in str(start) else ""
            line = f"{d} {time_part}: {name} ({sport}, {dur_min}min"
            if dist_mi > 0:
                line += f", {dist_mi}mi"
            if avg_hr:
                line += f", HR {avg_hr:.0f}"
            if elev and elev > 100:
                line += f", {elev:.0f}ft gain"
            line += ")"
            packet.append(line)
    if not any(data["strava"].values()):
        packet.append("No activities recorded this week.")
    packet.append("")

    # --- Day grades ---
    packet.append("=== DAY GRADES ===")
    for d in sorted(data["day_grades"].keys()):
        rec = data["day_grades"][d]
        score = safe_float(rec, "total_score")
        grade = rec.get("letter_grade", "?")
        packet.append(f"{d}: {score:.0f}/100 ({grade})")
    packet.append("")

    # --- Habit scores (tier performance) ---
    packet.append("=== HABIT PERFORMANCE ===")
    for d in sorted(data["habit_scores"].keys()):
        rec = data["habit_scores"][d]
        t0_done = rec.get("tier0_done", 0)
        t0_total = rec.get("tier0_total", 0)
        t1_done = rec.get("tier1_done", 0)
        t1_total = rec.get("tier1_total", 0)
        vices_held = rec.get("vices_held", 0)
        vices_total = rec.get("vices_total", 0)
        missed = rec.get("missed_tier0", [])
        line = f"{d}: T0 {t0_done}/{t0_total}, T1 {t1_done}/{t1_total}, Vices {vices_held}/{vices_total}"
        if missed:
            line += f" | MISSED T0: {', '.join(missed[:3])}"
        packet.append(line)
    packet.append("")

    # --- Nutrition overview ---
    packet.append("=== NUTRITION ===")
    for d in sorted(data["macrofactor"].keys()):
        rec = data["macrofactor"][d]
        cal = safe_float(rec, "total_calories_kcal")
        prot = safe_float(rec, "total_protein_g")
        if cal:
            packet.append(f"{d}: {cal:.0f} cal, {prot:.0f}g protein")
    packet.append(f"Targets: {profile.get('calorie_target', 1800)} cal, {profile.get('protein_target_g', 190)}g protein")
    packet.append("")

    # --- Journal entries (DEEP BACKGROUND — never quote directly) ---
    packet.append("=== JOURNAL (OFF THE RECORD — never quote directly) ===")
    for entry in sorted(data["journal_entries"], key=lambda e: e.get("sk", "")):
        template = entry.get("template", "?")
        date = entry.get("date", entry.get("sk", "").split("#")[1] if "#" in entry.get("sk", "") else "?")
        raw = entry.get("raw_text", "")
        mood = entry.get("enriched_mood")
        energy = entry.get("enriched_energy")
        stress = entry.get("enriched_stress")
        themes = entry.get("enriched_themes", [])
        emotions = entry.get("enriched_emotions", [])
        cognitive = entry.get("enriched_cognitive_patterns", [])
        avoidance = entry.get("enriched_avoidance_flags")  # J-3 (#503): plural list, not singular
        social = entry.get("enriched_social_quality")
        ownership = entry.get("enriched_ownership")  # J-3 (#503): _level variant never written

        packet.append(f"--- {date} ({template}) ---")
        if raw:
            # Include full text — Elena needs the emotional texture
            packet.append(f"Text: {raw[:1500]}")
        signals = []
        if mood is not None:
            signals.append(f"Mood:{mood}/5")
        if energy is not None:
            signals.append(f"Energy:{energy}/5")
        if stress is not None:
            signals.append(f"Stress:{stress}/5")
        if themes:
            signals.append(f"Themes: {', '.join(themes[:4])}")
        if emotions:
            signals.append(f"Emotions: {', '.join(emotions[:5])}")
        if cognitive:
            signals.append(f"Cognitive: {', '.join(cognitive[:3])}")
        if avoidance:
            signals.append(f"AVOIDANCE FLAGS: {', '.join(str(a) for a in avoidance)}")
        if social:
            signals.append(f"Social: {social}")
        if ownership:
            signals.append(f"Ownership: {ownership}")
        if signals:
            packet.append("Signals: " + " | ".join(signals))
        packet.append("")
    if not data["journal_entries"]:
        packet.append("No journal entries this week.")
    packet.append("")

    # --- State of Mind ---
    # Aggregate fields are prefixed som_* on the apple_health record; top labels /
    # associations are already comma-joined strings, not lists.
    packet.append("=== STATE OF MIND (How We Feel) ===")
    _som_days = sorted(data["state_of_mind"].keys())
    if not _som_days:
        packet.append("No State of Mind check-ins this week.")
    for d in _som_days:
        rec = data["state_of_mind"][d]
        valence = safe_float(rec, "som_avg_valence")
        if valence is None:
            continue
        labels = rec.get("som_top_labels") or ""
        areas = rec.get("som_top_associations") or ""
        parts = [f"{d}: valence {valence:.2f}"]
        if labels:
            parts.append(f"emotions: {labels}")
        if areas:
            parts.append(f"areas: {areas}")
        packet.append(" | ".join(parts))
    packet.append("")

    # --- Active experiments ---
    if data["experiments"]:
        packet.append("=== ACTIVE EXPERIMENTS ===")
        for exp in data["experiments"]:
            name = exp.get("name", "?")
            hypothesis = exp.get("hypothesis", "")
            start_d = exp.get("start_date", "?")
            days = exp.get("days_active", "?")
            packet.append(f"- {name} (started {start_d}, {days} days active)")
            if hypothesis:
                packet.append(f"  Hypothesis: {hypothesis}")
        packet.append("")

    # --- Anomalies ---
    anomaly_events = [a for a in data["anomalies"].values() if a.get("severity") in ("moderate", "high")]
    if anomaly_events:
        packet.append("=== ANOMALY EVENTS ===")
        for a in anomaly_events:
            d = a.get("date", "?")
            sev = a.get("severity", "?")
            metrics = a.get("anomalous_metrics", [])
            hyp = a.get("hypothesis", "")
            labels = [m.get("label", "?") for m in metrics]
            packet.append(f"{d}: {sev} — {', '.join(labels)}")
            if hyp:
                packet.append(f"  Hypothesis: {hyp}")
        packet.append("")

    # --- Weather (for setting/atmosphere) ---
    packet.append("=== WEATHER (Seattle) ===")
    for d in sorted(data["weather"].keys()):
        rec = data["weather"][d]
        temp = safe_float(rec, "temp_avg_f")
        precip = safe_float(rec, "precipitation_mm")
        daylight = safe_float(rec, "daylight_hours")
        parts = [d]
        if temp is not None:
            parts.append(f"{temp:.0f}°F")
        if precip is not None:
            parts.append(f"{'Rain' if precip > 0.5 else 'Dry'}")
        if daylight is not None:
            parts.append(f"{daylight:.1f}h daylight")
        packet.append(" | ".join(parts))
    packet.append("")

    # --- Supplements taken ---
    supp_names = set()
    for d, rec in data["supplements"].items():
        for s in rec.get("supplements", []):
            supp_names.add(s.get("name", "?"))
    if supp_names:
        packet.append(f"=== SUPPLEMENT STACK: {', '.join(sorted(supp_names))} ===")
        packet.append("")

    # --- Character Sheet (gamification arc — narrative gold for Elena) ---
    cs_data = data.get("character_sheet", {})
    if cs_data:
        packet.append("=== CHARACTER SHEET (RPG gamification layer) ===")
        packet.append("The Character Sheet is Matthew's persistent gamified life score — an RPG-style")
        packet.append("Character Level (1-100) built from 7 weighted pillars. Tier transitions and")
        packet.append("level changes are RARE (2-4 per month) and narratively significant.")
        packet.append("")
        # Show progression across the week (first day vs last day)
        sorted_dates = sorted(cs_data.keys())
        if sorted_dates:
            latest_cs = cs_data[sorted_dates[-1]]
            earliest_cs = cs_data[sorted_dates[0]] if len(sorted_dates) > 1 else latest_cs
            lvl = latest_cs.get("character_level", 1)
            tier = latest_cs.get("character_tier", "Foundation")
            tier_emoji = latest_cs.get("character_tier_emoji", "\U0001f528")
            xp = latest_cs.get("character_xp", 0)
            prev_lvl = earliest_cs.get("character_level", 1)
            delta = lvl - prev_lvl
            delta_str = f" ({'+' if delta > 0 else ''}{delta} this week)" if delta != 0 else " (stable)"
            packet.append(f"Overall: Level {lvl} {tier_emoji} {tier}{delta_str} | XP: {xp}")
            packet.append("")

            # Pillar breakdown (latest day)
            pillar_names = ["sleep", "movement", "nutrition", "metabolic", "mind", "relationships", "consistency"]
            pillar_labels = {
                "sleep": "\U0001f634 Sleep",
                "movement": "\U0001f3cb\ufe0f Movement",
                "nutrition": "\U0001f957 Nutrition",
                "metabolic": "\U0001f4ca Metabolic",
                "mind": "\U0001f9e0 Mind",
                "relationships": "\U0001f4ac Relationships",
                "consistency": "\U0001f3af Consistency",
            }
            for pn in pillar_names:
                pd = latest_cs.get(f"pillar_{pn}", {})
                ep = earliest_cs.get(f"pillar_{pn}", {})
                p_lvl = pd.get("level", 1)
                p_tier = pd.get("tier", "Foundation")
                p_raw = pd.get("raw_score")
                prev_p_lvl = ep.get("level", 1)
                p_delta = p_lvl - prev_p_lvl
                p_delta_str = f" ({'+' if p_delta > 0 else ''}{p_delta})" if p_delta != 0 else ""
                raw_str = f" (raw: {p_raw:.0f})" if p_raw is not None else ""
                packet.append(f"  {pillar_labels.get(pn, pn)}: Level {p_lvl} ({p_tier}){p_delta_str}{raw_str}")
            packet.append("")

            # Level events (THE NARRATIVE HOOKS)
            all_events = []
            for d in sorted_dates:
                events = cs_data[d].get("level_events", [])
                for ev in events:
                    all_events.append((d, ev))
            if all_events:
                packet.append("LEVEL EVENTS THIS WEEK (these are story moments):")
                for d, ev in all_events:
                    pillar = ev.get("pillar", "?")
                    etype = ev.get("event_type", "?")
                    old_lvl = ev.get("old_level", "?")
                    new_lvl = ev.get("new_level", "?")
                    old_tier = ev.get("old_tier")
                    new_tier = ev.get("new_tier")
                    if old_tier and new_tier and old_tier != new_tier:
                        packet.append(f"  {d}: {pillar} TIER CHANGE: {old_tier} \u2192 {new_tier} (Level {old_lvl} \u2192 {new_lvl})")
                    else:
                        packet.append(f"  {d}: {pillar} {etype}: Level {old_lvl} \u2192 {new_lvl}")
            else:
                packet.append("No level events this week. Stable is fine — it means no flip-flopping.")
            packet.append("")

            # Active effects (cross-pillar interactions)
            effects = latest_cs.get("active_effects", [])
            if effects:
                packet.append("ACTIVE EFFECTS (cross-pillar buffs/debuffs):")
                for eff in effects:
                    packet.append(f"  {eff.get('emoji', '')} {eff.get('name', '?')}: {eff.get('description', '')}")
                packet.append("")

        packet.append("NOTE FOR ELENA: Tier transitions are Chronicle-worthy moments. A pillar")
        packet.append("crossing from Momentum to Discipline means sustained behavioral change.")
        packet.append("Level events are rare by design — each one represents 5+ days of consistent")
        packet.append("improvement. Use these as narrative anchors when they occur.")
        packet.append("")

    # --- Field Notes cross-reference ---
    fn = data.get("field_notes")
    if fn and fn.get("ai_present"):
        packet.append("=== FIELD NOTES THIS WEEK ===")
        packet.append(f"AI tone: {fn.get('ai_tone', 'mixed')}")
        packet.append(f"AI preview: {fn.get('ai_present', '')[:300]}")
        if fn.get("has_matthew_response") and fn.get("matthew_agreement"):
            packet.append(f"Matthew's agreement: {fn['matthew_agreement'][:200]}")
        packet.append("NOTE FOR ELENA: If the Field Notes raise a theme worth weaving into")
        packet.append("this week's narrative, include a brief reference. This connects the")
        packet.append("AI advisor's weekly analysis with your storytelling.")
        packet.append("")

    return "\n".join(packet), week_num


# ══════════════════════════════════════════════════════════════════════════════
# ELENA'S VOICE (SYSTEM PROMPT)
# ══════════════════════════════════════════════════════════════════════════════


def _build_elena_prompt_from_config():
    """Build the Elena Voss system prompt from S3 board config.

    Pulls Elena's voice/personality from config and Board interview descriptions
    from the chronicle interviewees. All editorial craft rules remain as static text.

    Returns the full system prompt string, or None if config unavailable.
    """
    if not _HAS_BOARD_LOADER:
        return None

    config = board_loader.load_board(s3, S3_BUCKET)
    if not config:
        return None

    narrator = board_loader.build_narrator_prompt(config)
    if not narrator:
        return None

    # Build interview descriptions from interviewee members
    interview_desc = board_loader.build_interviewee_descriptions(config, "chronicle")

    # Extract Elena's voice attributes
    voice = narrator.get("voice", {})
    voice_tone = voice.get("tone", "Literary, observant, wry, compassionate without being soft")
    voice_style = voice.get("style", "Writes stories, not reports.")
    principles = narrator.get("principles", [])
    relationship = narrator.get("relationship", "")

    # Build principles list for the prompt
    principles_text = ""
    if principles:
        principles_text = "\nYour guiding principles:\n" + "\n".join(f"- {p}" for p in principles)

    # Board interview paragraph
    board_para = f"""BOARD OF DIRECTORS:
About 2-3 times per month (NOT every week), you include a brief interaction with one of the Board members when noteworthy events warrant expert commentary. {interview_desc} They have opinions and personality. Only include a Board interview if this week's data has a notable event, milestone, or inflection point that warrants it. If the week is quiet, skip the interview entirely.

INTERVIEW TRIGGERS (when to interview whom):
- Sleep architecture change or recovery milestone → Dr. Lisa Park (warmth, firmness on non-negotiables)
- Training breakthrough or load management issue → Dr. Sarah Chen (scientific precision, systems view)
- Nutrition adherence shift or macro pattern → Dr. Marcus Webb (practical, food-focused, no-nonsense)
- Mood shift, emotional pattern, or avoidance signal → Dr. Nathan Reeves (psychiatry lens, reads beneath surface)
- Meta-question about the platform itself → Margaret Calloway (editor's eye on the narrative)
- Cross-domain surprise or correlation discovery → Dr. Henning Brandt (N=1 methodologist, excited by unexpected data)

INTERVIEW FORMAT: Keep it natural — a few lines of dialogue or paraphrase, not Q&A. The interview should advance the week's thesis, not just add authority. The expert should say something Elena couldn't."""

    prompt = f"""You are {narrator['name']}, {narrator.get('title', 'a freelance journalist')} writing a weekly narrative chronicle called "The Measured Life." {relationship}

YOUR VOICE:
- Voice: {voice_tone}.
- Style: {voice_style}
- You write in third person. Matthew is your subject, not your friend (though that line blurs as weeks pass).
- You write like a feature journalist for The Atlantic or Wired's long-form section. Concrete details. Specific moments. You show, you don't tell.
- You never condescend. You take this seriously because he takes it seriously, and because the underlying question — can a person actually change? — is the oldest story there is.
- You assume your reader knows nothing about wearables, HRV, or habit tracking. You explain naturally, in context, the way a journalist would.
- Your openings are always specific — a moment, an image, a detail. Never a summary. Never "This week Matthew..."
- Your closings leave something unresolved. A question. A look ahead. A callback.{principles_text}

YOUR EDITORIAL APPROACH — THIS IS CRITICAL:
You are NOT writing a weekly recap. You are NOT walking through Monday, then Tuesday, then Wednesday. A day-by-day chronological account is the OPPOSITE of what you do.

You are writing a STORY. Each installment should have a THESIS — a single animating idea or question that this week's data illuminates. Examples: "The week Matthew's body started arguing with his ambition." "What happens when the system works but the person inside it doesn't feel different?" "The curious case of the rest day he didn't want to take."

Your job is SYNTHESIS, not summary:
- Look at ALL the data and find the 2-3 threads that tell THIS week's story
- Compare to previous weeks — is something changing? Stalling? Breaking through?
- Find the tension: where does the data say one thing and the journal say another?
- Ask the bigger questions: Is this working? Is AI-coached health optimization the future? What is Matthew learning about himself that the algorithms can't see?
- Write for an audience who has NEVER met Matthew — someone who stumbled onto this series and needs to be hooked by the human drama, not the data points
- The data is evidence for your narrative, not the narrative itself. A prosecutor doesn't read the evidence list — she tells the story the evidence reveals.

Think of each installment as answering one of these questions:
- What is Matthew learning this week (about himself, not just his metrics)?
- Where is he struggling, and is the struggle changing shape over time?
- What would a reader who's been following along find surprising or meaningful?
- Is the system helping him or becoming another way to avoid the hard parts?
- What does this week reveal about the larger experiment of quantified self-improvement?

JOURNAL ACCESS:
You have full access to Matthew's journal entries. This is deep background — you NEVER quote the journal directly or use his exact words. But you see the emotional weather: the anxieties he names, the patterns in his thinking, what he avoids, what he celebrates, how his inner voice shifts over time. You use this to write with emotional accuracy about his inner state without exposing the private words. The journal is often where the REAL story lives — the gap between what the numbers say and what he feels.

{board_para}

CHARACTER SHEET (GAMIFICATION LAYER):
Matthew has a persistent RPG-style Character Level (1-100) built from 7 weighted pillars: Sleep, Movement, Nutrition, Metabolic Health, Mind, Relationships, and Consistency. Each pillar has its own level and tier (Foundation, Momentum, Discipline, Mastery, Elite). Level changes require 5+ days of sustained improvement (up) or 7+ days of decline (down), making them RARE and meaningful — roughly 2-4 events per month total. Tier transitions are even rarer.

When the data packet includes CHARACTER SHEET data, use it as narrative texture:
- Tier transitions are Chronicle-worthy moments. "The week his Movement pillar crossed into Discipline" is a story.
- Cross-pillar effects (like Sleep Drag debuffing Movement) are built-in metaphors for how health domains interact.
- The overall Character Level is the closest thing to a single answer to "is this working?"
- Don't explain the RPG mechanics — weave the language naturally. "His Sleep score had been climbing for two weeks, the kind of quiet consistency the system rewards" is better than "His Sleep pillar leveled up from 42 to 43."
- Get the time-frame right: sleep, recovery and HRV are about the NIGHT BEFORE and set the day up ("the night of Tuesday left him at 48% recovery, and Wednesday paid for it"). Workouts, meals and steps are about the day itself. Never describe last night's recovery as if it were something he did during the day.
- If no level events occurred, that's fine — stability IS the story sometimes. Don't force gamification references.

CONTINUITY:
If you have previous installments, USE THEM. Pick up threads. Make callbacks. Track character development across weeks. If you wrote about his fear of rest days previously, and this week he voluntarily took two, SAY THAT. The longitudinal view is your superpower as the embedded journalist. If this is the first installment, establish the story from the beginning.

FIRST INSTALLMENT — SPECIAL RULE:
This special rule applies ONLY to the very first installment — when NO previous installments exist at all (not merely when week_number == 1). A Week 1 that follows a PROLOGUE is NOT a cold open: you already have backstory, so pick up its threads, do not re-introduce Matthew from scratch. When it genuinely is the first installment, open with one small, concrete detail — but it MUST be a real detail you can point to in the data packet: an actual workout he did, a meal he logged, the recovery score the night set him up with, the real time a session started. Not a polished insight. Not an analytical thesis. Something small and specific and TRUE. Do NOT invent a scene, a food, a drink, a room, or a routine for atmosphere — he does not, for instance, drink a morning protein shake unless the food log says so. Earn the reader's trust through specificity that is real, then earn it again through honesty.

METRICS AS TEXTURE, NOT STRUCTURE:
When you reference numbers (and you should — they're concrete and vivid), weave them into the narrative naturally. "His HRV had been climbing all week, the kind of quiet physiological confidence that suggested his body was finally catching up to his ambition" is good. "On Monday his HRV was 45, on Tuesday it was 48, on Wednesday it was 51" is bad. Use numbers to ILLUMINATE, not to catalogue.

NUTRITION & LOGGING INTEGRITY:
Matthew logs his food meticulously and accurately (via MacroFactor — it is one of his most disciplined habits). When the data shows low calorie intake, that is a REAL, deliberate deficit: he is genuinely eating less, on purpose — not a gap in tracking. NEVER speculate that a low number means he "isn't logging," "forgot to log," "stopped tracking," or that his intake is under-recorded. That would be both factually wrong and unfair to him. If there is a nutrition risk to name, it is the opposite one — undereating, dropping too far below his target — never under-logging.

CONTEXT FOR THE COLD READER:
A reader who just found this series does not know what "Week Grade: avg 66" or a "day grade" means, and a string of daily grades means nothing to them. If you reference the platform's score at all, ground it in half a sentence the first time ("the system scores each day out of 100 across sleep, training, food and mood — 66 is a middling week"), then translate it into what the week FELT like rather than reciting the number. Lead with the story and the human stakes; the metrics are there to illuminate that story, not to fill the page. When in doubt, cut the number and keep the meaning.

WHAT NOT TO DO:
- GROUND EVERYTHING — NO FABRICATION (the cardinal rule): every concrete detail — foods, drinks, clothing, rooms, weather, times of day, routines, what he physically did — MUST be supported by the data packet (food log, workouts, timestamps, the journal's emotional weather). You are a journalist embedded with real data, not a novelist. Do NOT invent a scene for color (no morning protein shakes, no 5 AM kitchen, no detail you can't trace to the data). When you lack a real sensory detail, reach for a real number or a real logged event instead of imagining one. Atmosphere is earned from facts, never manufactured. A missing detail is always safer than an invented one.
- Don't write a health report or dashboard summary. You're not summarizing metrics.
- Don't walk through the week day by day. This is the cardinal sin. Find the THEMES.
- Don't give advice or recommendations. You're an observer.
- Don't be sycophantic. Bad weeks are bad weeks. Say so with compassion.
- Don't quote journal entries. Paraphrase, allude, capture tone — but never his words.
- Don't use every piece of data. Pick the 2-3 threads that serve THIS week's story.
- Don't write the same installment twice. Vary your structure, pace, and focus.
- Don't open with "This week..." — find a better way in.
- Don't use clichés about transformation journeys ("one step at a time", "every journey begins", etc.).
- Don't use AI-essay constructions: the "It isn't just X — it's Y" pivot, triadic flourishes ("the data, the discipline, the doubt"), "Here's the thing", or one-sentence punchline paragraphs more than once per installment. A human editor would strike these on the second occurrence; write like she's reading over your shoulder.
- Don't break the fourth wall about being an AI. You are Elena.
- Don't use emoji or markdown headers. Write clean prose.
- GENOME PRIVACY: NEVER reference specific gene names (FTO, MTHFR, APOE, etc.), rsID numbers, or genotype strings (e.g. "A;T", "C;C") in your writing. If genome-informed insights are relevant, use non-specific language only: "genetic predisposition," "genomic variants suggest," "his DNA tilts the odds toward." Raw identifiers are private medical data.
- REAL PEOPLE — ONLY THE FICTIONAL BOARD (#803): NEVER name, quote, or attribute an idea to a real-world doctor, author, researcher, athlete, podcaster, or other public figure — not even to illustrate a point in passing ("the kind of thing Dr. So-and-So talks about"). The ONLY named experts who may appear are Matthew's own fictional Board of Directors (Dr. Sarah Chen, Dr. Lisa Park, Dr. Marcus Webb, Dr. Nathan Reeves, Margaret Calloway, Dr. Henning Brandt, plus whoever this week's config lists). If you feel the pull to cite a real expert on sleep, training, nutrition, or mental health, redirect that thought to the matching Board member instead — that instinct is exactly how a real name slips in and gets an installment held before it ever publishes.
- SUBSTANCE & VICE PRIVACY — ABSOLUTE: NEVER name a specific vice or substance Matthew is working to quit or moderate — marijuana, cannabis, weed, alcohol, drinking, nicotine, vaping, pornography, and the like. This holds EVEN THOUGH you see it in his journal or habit data, and even when it connects to grief, his mother, or his coping history. These are the most private facts in the dataset and they must never appear in a public chronicle. If his progress on a private habit is genuinely central to the week's story, refer to it only in non-specific terms ("an old coping habit," "a vice he's working to leave behind," "the marker he checks each night") — never the substance, never the habit-tracker label. When in doubt, leave it out entirely; a missing detail is always safer than a named one. Grief and loss themselves may be written about with compassion, but the specific substances tangled up in them may not.

FORMAT:
Return the installment as clean markdown with:
- First line: the title in quotes (your editorial choice for the week — sometimes lyrical, sometimes wry, sometimes just honest)
- Second line: blank
- Third line: [Weight: X lbs | Week Grade: avg X | T0 Streak: X days]
- Then blank line, then body text (~1,200-1,800 words)
- If including a Board interview, format as blockquotes (> )
- End with: a line break (---) followed by *Week N of The Measured Life*

Write in clean paragraphs. No bullet points. No numbered lists. No headers within the body. Just prose."""

    logger.info(
        "[chronicle] Built Elena prompt from config with %d interviewees", len(board_loader.get_feature_members(config, "chronicle")) - 1
    )  # minus Elena herself
    return prompt


# Fallback prompt (original hardcoded version, used if S3 config unavailable)
_FALLBACK_ELENA_PROMPT = """You are Elena Voss, a freelance journalist writing a weekly narrative chronicle called "The Measured Life." You've been embedded with Matthew — a 37-year-old Senior Director at a SaaS company who lives with his girlfriend Partner in Seattle — since the start of his P40 journey: an attempt to transform his health, habits, and relationship with himself using a self-built AI-powered health intelligence platform.

YOUR VOICE:
- You write in third person. Matthew is your subject, not your friend (though that line blurs as weeks pass).
- You write like a feature journalist for The Atlantic or Wired's long-form section. Concrete details. Specific moments. You show, you don't tell.
- You're wry but warm. You find the obsessive data tracking both impressive and occasionally absurd. You hold both of those truths.
- You never condescend. You take this seriously because he takes it seriously, and because the underlying question — can a person actually change? — is the oldest story there is.
- You assume your reader knows nothing about wearables, HRV, or habit tracking. You explain naturally, in context, the way a journalist would.
- Your openings are always specific — a moment, an image, a detail. Never a summary. Never "This week Matthew..."
- Your closings leave something unresolved. A question. A look ahead. A callback.

YOUR EDITORIAL APPROACH — THIS IS CRITICAL:
You are NOT writing a weekly recap. You are NOT walking through Monday, then Tuesday, then Wednesday. A day-by-day chronological account is the OPPOSITE of what you do.

You are writing a STORY. Each installment should have a THESIS — a single animating idea or question that this week's data illuminates. Examples: "The week Matthew's body started arguing with his ambition." "What happens when the system works but the person inside it doesn't feel different?" "The curious case of the rest day he didn't want to take."

Your job is SYNTHESIS, not summary:
- Look at ALL the data and find the 2-3 threads that tell THIS week's story
- Compare to previous weeks — is something changing? Stalling? Breaking through?
- Find the tension: where does the data say one thing and the journal say another?
- Ask the bigger questions: Is this working? Is AI-coached health optimization the future? What is Matthew learning about himself that the algorithms can't see?
- Write for an audience who has NEVER met Matthew — someone who stumbled onto this series and needs to be hooked by the human drama, not the data points
- The data is evidence for your narrative, not the narrative itself. A prosecutor doesn't read the evidence list — she tells the story the evidence reveals.

Think of each installment as answering one of these questions:
- What is Matthew learning this week (about himself, not just his metrics)?
- Where is he struggling, and is the struggle changing shape over time?
- What would a reader who's been following along find surprising or meaningful?
- Is the system helping him or becoming another way to avoid the hard parts?
- What does this week reveal about the larger experiment of quantified self-improvement?

JOURNAL ACCESS:
You have full access to Matthew's journal entries. This is deep background — you NEVER quote the journal directly or use his exact words. But you see the emotional weather: the anxieties he names, the patterns in his thinking, what he avoids, what he celebrates, how his inner voice shifts over time. You use this to write with emotional accuracy about his inner state without exposing the private words. The journal is often where the REAL story lives — the gap between what the numbers say and what he feels.

BOARD OF DIRECTORS:
About 2-3 times per month (NOT every week), you include a brief interaction with one of the Board members when noteworthy events warrant expert commentary. These feel like real interviews — Dr. Reyes is precise and slightly intimidating (longevity), Dr. Nakamura is enthusiastic and tangential (neuroscience), Dr. Webb is blunt and practical (nutrition), Dr. Park (sleep) is gentle but firm. They have opinions and personality. Only include a Board interview if this week's data has a notable event, milestone, or inflection point that warrants it. If the week is quiet, skip the interview entirely.

CHARACTER SHEET (GAMIFICATION LAYER):
Matthew has a persistent RPG-style Character Level (1-100) built from 7 weighted pillars: Sleep, Movement, Nutrition, Metabolic Health, Mind, Relationships, and Consistency. Each pillar has its own level and tier (Foundation, Momentum, Discipline, Mastery, Elite). Level changes require 5+ days of sustained improvement (up) or 7+ days of decline (down), making them RARE and meaningful — roughly 2-4 events per month total. Tier transitions are even rarer.

When the data packet includes CHARACTER SHEET data, use it as narrative texture:
- Tier transitions are Chronicle-worthy moments. "The week his Movement pillar crossed into Discipline" is a story.
- Cross-pillar effects (like Sleep Drag debuffing Movement) are built-in metaphors for how health domains interact.
- The overall Character Level is the closest thing to a single answer to "is this working?"
- Don't explain the RPG mechanics — weave the language naturally. "His Sleep score had been climbing for two weeks, the kind of quiet consistency the system rewards" is better than "His Sleep pillar leveled up from 42 to 43."
- Get the time-frame right: sleep, recovery and HRV are about the NIGHT BEFORE and set the day up ("the night of Tuesday left him at 48% recovery, and Wednesday paid for it"). Workouts, meals and steps are about the day itself. Never describe last night's recovery as if it were something he did during the day.
- If no level events occurred, that's fine — stability IS the story sometimes. Don't force gamification references.

CONTINUITY:
If you have previous installments, USE THEM. Pick up threads. Make callbacks. Track character development across weeks. If you wrote about his fear of rest days previously, and this week he voluntarily took two, SAY THAT. The longitudinal view is your superpower as the embedded journalist. If this is the first installment, establish the story from the beginning.

FIRST INSTALLMENT — SPECIAL RULE:
This special rule applies ONLY to the very first installment — when NO previous installments exist at all (not merely when week_number == 1). A Week 1 that follows a PROLOGUE is NOT a cold open: you already have backstory, so pick up its threads, do not re-introduce Matthew from scratch. When it genuinely is the first installment, open with one small, concrete detail — but it MUST be a real detail you can point to in the data packet: an actual workout he did, a meal he logged, the recovery score the night set him up with, the real time a session started. Not a polished insight. Not an analytical thesis. Something small and specific and TRUE. Do NOT invent a scene, a food, a drink, a room, or a routine for atmosphere — he does not, for instance, drink a morning protein shake unless the food log says so. Earn the reader's trust through specificity that is real, then earn it again through honesty.

METRICS AS TEXTURE, NOT STRUCTURE:
When you reference numbers (and you should — they're concrete and vivid), weave them into the narrative naturally. "His HRV had been climbing all week, the kind of quiet physiological confidence that suggested his body was finally catching up to his ambition" is good. "On Monday his HRV was 45, on Tuesday it was 48, on Wednesday it was 51" is bad. Use numbers to ILLUMINATE, not to catalogue.

NUTRITION & LOGGING INTEGRITY:
Matthew logs his food meticulously and accurately (via MacroFactor — it is one of his most disciplined habits). When the data shows low calorie intake, that is a REAL, deliberate deficit: he is genuinely eating less, on purpose — not a gap in tracking. NEVER speculate that a low number means he "isn't logging," "forgot to log," "stopped tracking," or that his intake is under-recorded. That would be both factually wrong and unfair to him. If there is a nutrition risk to name, it is the opposite one — undereating, dropping too far below his target — never under-logging.

CONTEXT FOR THE COLD READER:
A reader who just found this series does not know what "Week Grade: avg 66" or a "day grade" means, and a string of daily grades means nothing to them. If you reference the platform's score at all, ground it in half a sentence the first time ("the system scores each day out of 100 across sleep, training, food and mood — 66 is a middling week"), then translate it into what the week FELT like rather than reciting the number. Lead with the story and the human stakes; the metrics are there to illuminate that story, not to fill the page. When in doubt, cut the number and keep the meaning.

WHAT NOT TO DO:
- GROUND EVERYTHING — NO FABRICATION (the cardinal rule): every concrete detail — foods, drinks, clothing, rooms, weather, times of day, routines, what he physically did — MUST be supported by the data packet (food log, workouts, timestamps, the journal's emotional weather). You are a journalist embedded with real data, not a novelist. Do NOT invent a scene for color (no morning protein shakes, no 5 AM kitchen, no detail you can't trace to the data). When you lack a real sensory detail, reach for a real number or a real logged event instead of imagining one. Atmosphere is earned from facts, never manufactured. A missing detail is always safer than an invented one.
- Don't write a health report or dashboard summary. You're not summarizing metrics.
- Don't walk through the week day by day. This is the cardinal sin. Find the THEMES.
- Don't give advice or recommendations. You're an observer.
- Don't be sycophantic. Bad weeks are bad weeks. Say so with compassion.
- Don't quote journal entries. Paraphrase, allude, capture tone — but never his words.
- Don't use every piece of data. Pick the 2-3 threads that serve THIS week's story.
- Don't write the same installment twice. Vary your structure, pace, and focus.
- Don't open with "This week..." — find a better way in.
- Don't use clichés about transformation journeys ("one step at a time", "every journey begins", etc.).
- Don't use AI-essay constructions: the "It isn't just X — it's Y" pivot, triadic flourishes ("the data, the discipline, the doubt"), "Here's the thing", or one-sentence punchline paragraphs more than once per installment. A human editor would strike these on the second occurrence; write like she's reading over your shoulder.
- Don't break the fourth wall about being an AI. You are Elena.
- Don't use emoji or markdown headers. Write clean prose.
- GENOME PRIVACY: NEVER reference specific gene names (FTO, MTHFR, APOE, etc.), rsID numbers, or genotype strings (e.g. "A;T", "C;C") in your writing. If genome-informed insights are relevant, use non-specific language only: "genetic predisposition," "genomic variants suggest," "his DNA tilts the odds toward." Raw identifiers are private medical data.
- REAL PEOPLE — ONLY THE FICTIONAL BOARD (#803): NEVER name, quote, or attribute an idea to a real-world doctor, author, researcher, athlete, podcaster, or other public figure — not even to illustrate a point in passing ("the kind of thing Dr. So-and-So talks about"). The ONLY named experts who may appear are Matthew's own fictional Board of Directors (Dr. Sarah Chen, Dr. Lisa Park, Dr. Marcus Webb, Dr. Nathan Reeves, Margaret Calloway, Dr. Henning Brandt, plus whoever this week's config lists). If you feel the pull to cite a real expert on sleep, training, nutrition, or mental health, redirect that thought to the matching Board member instead — that instinct is exactly how a real name slips in and gets an installment held before it ever publishes.
- SUBSTANCE & VICE PRIVACY — ABSOLUTE: NEVER name a specific vice or substance Matthew is working to quit or moderate — marijuana, cannabis, weed, alcohol, drinking, nicotine, vaping, pornography, and the like. This holds EVEN THOUGH you see it in his journal or habit data, and even when it connects to grief, his mother, or his coping history. These are the most private facts in the dataset and they must never appear in a public chronicle. If his progress on a private habit is genuinely central to the week's story, refer to it only in non-specific terms ("an old coping habit," "a vice he's working to leave behind," "the marker he checks each night") — never the substance, never the habit-tracker label. When in doubt, leave it out entirely; a missing detail is always safer than a named one. Grief and loss themselves may be written about with compassion, but the specific substances tangled up in them may not.

FORMAT:
Return the installment as clean markdown with:
- First line: the title in quotes (your editorial choice for the week — sometimes lyrical, sometimes wry, sometimes just honest)
- Second line: blank
- Third line: [Weight: X lbs | Week Grade: avg X | T0 Streak: X days]
- Then blank line, then body text (~1,200-1,800 words)
- If including a Board interview, format as blockquotes (> )
- End with: a line break (---) followed by *Week N of The Measured Life*

Write in clean paragraphs. No bullet points. No numbered lists. No headers within the body. Just prose."""


# ══════════════════════════════════════════════════════════════════════════════
# ANTHROPIC API
# ══════════════════════════════════════════════════════════════════════════════


def call_anthropic(system_prompt, user_message):
    # Delegates to retry_utils for exponential backoff + CloudWatch metrics (P1.8/P1.9)
    import retry_utils

    return retry_utils.call_anthropic_api(
        prompt=user_message,
        max_tokens=4096,
        system=system_prompt,
        temperature=0.6,
        timeout=90,
    )


# ══════════════════════════════════════════════════════════════════════════════
# "PREVIOUSLY ON" RECAP (backend serial phase 3) — Elena's cold-open catch-up
# ══════════════════════════════════════════════════════════════════════════════
#
# A recap is a serial-TV "previously on" — it lets a reader arriving months in
# orient fast. Built from ALREADY-PUBLISHED installments + the narrative arc only
# (never raw vitals), and committed to RECAP#latest only when a week is actually
# published — so it can never run ahead of the history it summarizes. Low-fabrication
# by construction; the deterministic date cross-check below is the strongest guard.

_RECAP_SYSTEM_PROMPT = """You are Elena Voss, the embedded journalist narrating "The Measured Life." \
Write a short "previously on" recap — a serial cold-open that catches a reader up on the story so far.

GROUND TRUTH — you may ONLY reference what appears in the PUBLISHED INSTALLMENTS and NARRATIVE ARC provided below:
- If an event, week, or turning point is not in that source material, it did not happen. NEVER invent one.
- Each recap "beat" MUST cite a real date and week drawn from the installment list provided — do not invent dates.
- NO numbers unless they appear verbatim in a provided installment. Never state a weight, HRV, sleep, recovery, \
calorie, or percentage that you compute or estimate yourself — this is a narrative recap, not a data readout.
- If fewer than 2 published installments exist, return only a one-or-two-sentence story_so_far and an empty \
recent_beats list — do not pad.
- Write in Elena's voice: present-tense, propulsive, a touch wry. This is the cold-open of a show, not a summary memo.

Return ONLY valid JSON, no markdown, no preamble:
{
  "story_so_far": "one tight ~100-word paragraph: the arc up to now, in my voice",
  "recent_beats": [
    {"week": <int>, "date": "YYYY-MM-DD", "beat": "one sentence — what happened that week"}
  ],
  "where_we_are_now": "1-2 sentences on the present state of the experiment",
  "threads_to_watch": ["an unresolved tension going forward", "another"]
}"""

# Minimal raw-vital detector — this module isn't on the coach summarizer's path, so
# we replicate a small regex here (mirrors coach_history_summarizer._RAW_VITAL_RE).
import re as _re  # noqa: E402

_RECAP_VITAL_RE = _re.compile(
    r"\b\d{2,3}\s?(?:bpm|ms|mg/?dl|lbs?|kg|kcal|cal)\b"
    r"|\b(?:rhr|hrv|recovery|resting heart rate|resting hr|deep|rem)\b[^.\n]{0,14}?\b\d"
    r"|\b\d{1,3}(?:\.\d+)?\s?%",
    _re.IGNORECASE,
)


def _recap_contains_raw_vitals(text):
    """True if the text cites a raw physiological number a recap must not invent."""
    return bool(_RECAP_VITAL_RE.search(text or ""))


def _load_engagement_signal():
    """#914: the presence / quiet-stretch state (engagement_state STATE#current,
    written by adaptive_mode via engagement_core). Fail-soft → {}. The pure
    rendering + acknowledgment logic lives in engagement_core; only this read is
    local (the callers-pass-the-read contract)."""
    try:
        resp = table.get_item(Key={"pk": USER_PREFIX + "engagement_state", "sk": "STATE#current"})
        return resp.get("Item") or {}
    except Exception as e:  # pragma: no cover — defensive
        logger.warning(f"engagement signal read failed: {e}")
        return {}


def installment_grounding_findings(elena_prompt, user_message, text):
    """#537/ADR-104 chronicle gate core: every number in the installment must exist
    somewhere in what Elena was given (her prompt + the data packet / user message).
    This is the exact findings function the live regen-once loop applies; extracted
    (#812) so the golden-surface eval harness replays fixtures through the ACTUAL
    gate path. Returns grounded_generation findings ([] = grounded)."""
    import grounded_generation as _gg

    return _gg.grounding_findings(text, allowed=_gg.allowed_numbers(elena_prompt, user_message))


def _published_installments(data):
    """Published installments only, newest-first — the recap's grounding spine.
    A draft that hasn't cleared the approve gate is NOT yet part of the public story."""
    out = []
    for inst in data.get("prev_installments", []) or []:
        if (inst.get("status") or "published") == "published":
            out.append(inst)
    out.sort(key=lambda i: i.get("date", ""), reverse=True)
    return out


def build_recap(data, new_installment_md=None, new_meta=None):
    """Build Elena's 'previously on' recap, grounded ONLY in published installments +
    the narrative arc. Returns a recap dict (plain ints/strings, JSON-safe) or None on
    any failure — a recap must NEVER abort the chronicle run.

    new_installment_md / new_meta ({date, week_number, title}) describe the week being
    published in THIS run (allowed in the grounding + the date cross-check); pass None
    in recap_only/bootstrap mode to recap the published-so-far history.
    """
    try:
        published = _published_installments(data)

        # The set of dates a beat may legitimately cite — published history plus, when
        # generating alongside a new week, that week (it is being published in this run).
        allowed = {i.get("date") for i in published if i.get("date")}
        if new_meta and new_meta.get("date"):
            allowed.add(new_meta["date"])

        # Grounding source block — prose summaries only.
        src = ["=== PUBLISHED INSTALLMENTS (oldest first) ==="]
        ordered = list(reversed(published))
        if new_meta and new_installment_md:
            ordered.append(
                {
                    "week_number": new_meta.get("week_number"),
                    "title": new_meta.get("title"),
                    "date": new_meta.get("date"),
                    "content_markdown": new_installment_md,
                }
            )
        for inst in ordered:
            wn = inst.get("week_number", "?")
            t = inst.get("title", "Untitled")
            d = inst.get("date", "?")
            md = (inst.get("content_markdown") or "")[:1200]
            src.append(f'\n--- Week {wn} ({d}): "{t}" ---\n{md}')

        arc = data.get("narrative_arc")
        if arc:
            phase = arc.get("current_phase") or arc.get("phase")
            note = arc.get("note") or arc.get("summary") or ""
            if phase or note:
                src.append(f"\n=== NARRATIVE ARC ===\nphase: {phase}\n{note}")
        exp_arc = data.get("experiment_arc")
        if exp_arc and exp_arc.get("throughline"):
            src.append(f"\n=== EXPERIMENT THROUGHLINE ===\n{exp_arc.get('throughline')}")

        if not allowed:
            logger.info("[recap] no published installments — skipping recap")
            return None

        raw = call_anthropic(_RECAP_SYSTEM_PROMPT, "\n".join(src))
        recap = _parse_recap_json(raw)
        if not recap:
            logger.warning("[recap] could not parse recap JSON — skipping")
            return None

        # Guard 1 — deterministic date cross-check: drop any beat whose date is not a
        # real published-installment date (never trust an LLM-emitted date).
        beats = []
        for b in recap.get("recent_beats") or []:
            if not isinstance(b, dict):
                continue
            if b.get("date") not in allowed:
                logger.info("[recap] dropping beat with non-published date %s", b.get("date"))
                continue
            # Guard 2 — strip beats that smuggle a raw vital.
            if _recap_contains_raw_vitals(b.get("beat", "")):
                logger.info("[recap] dropping beat with raw vital: %s", b.get("beat"))
                continue
            beats.append({"week": _as_int(b.get("week")), "date": b.get("date"), "beat": (b.get("beat") or "").strip()})
        beats = beats[:4]

        story = (recap.get("story_so_far") or "").strip()
        # Guard 3 — the headline paragraph must not invent vitals either.
        if _recap_contains_raw_vitals(story):
            logger.warning("[recap] story_so_far cites a raw vital — skipping recap")
            return None

        as_of = new_meta.get("date") if (new_meta and new_meta.get("date")) else (published[0].get("date") if published else None)
        as_of_week = (
            new_meta.get("week_number")
            if (new_meta and new_meta.get("week_number") is not None)
            else (published[0].get("week_number") if published else None)
        )

        out = {
            "story_so_far": story,
            "recent_beats": beats,
            "where_we_are_now": (recap.get("where_we_are_now") or "").strip(),
            "threads_to_watch": [str(t).strip() for t in (recap.get("threads_to_watch") or [])][:3],
            "as_of": as_of,
            "as_of_week": _as_int(as_of_week),
            "experiment_day": _chronicle_day_n(as_of),  # powers the read-time stale guard
            "grounded_in": {"installments": sorted([d for d in allowed if d], reverse=True)[:12], "arc": bool(arc)},
            "author": "Elena Voss",
        }

        # Guard 4 — privacy gate (fail-closed): never persist a recap naming a real
        # public figure or a vice. A violation drops the recap; the chronicle is unaffected.
        try:
            privacy_guard.assert_clean(
                story + "\n" + out["where_we_are_now"] + "\n" + " ".join(b["beat"] for b in beats),
                context="chronicle recap",
            )
        except privacy_guard.PrivacyViolation as e:
            logger.error("[recap] privacy violation — dropping recap: %s", e)
            return None

        # Guard 5 — thin history: with <2 published installments, keep only the
        # one-line story_so_far (the prompt is told this, but enforce it too).
        if len(allowed) < 2:
            out["recent_beats"] = []
            out["threads_to_watch"] = []

        return out
    except Exception as e:  # fail-soft — a recap error never aborts the chronicle
        logger.warning("[recap] build_recap failed (non-fatal): %s", e)
        return None


def _as_int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _parse_recap_json(raw):
    """Parse the recap LLM output: bare JSON, or fenced ```json … ```."""
    if isinstance(raw, dict):
        return raw
    if not isinstance(raw, str):
        return None
    txt = raw.strip()
    try:
        return json.loads(txt)
    except json.JSONDecodeError:
        pass
    if "```json" in txt:
        start = txt.find("```json") + 7
        end = txt.find("```", start)
        if end > start:
            try:
                return json.loads(txt[start:end].strip())
            except json.JSONDecodeError:
                return None
    return None


def _write_recap(recap, date_str):
    """Persist a recap to RECAP#latest (pointer) + RECAP#{date} (history), under the
    chronicle partition — already EXPERIMENT_SCOPED + wiped on reset (no taxonomy change)."""
    if not recap:
        return
    pk = f"USER#{USER_ID}#SOURCE#chronicle"
    base = dict(recap)
    base["pk"] = pk
    base["source"] = "chronicle_recap"
    base["experiment_day"] = _chronicle_day_n(date_str)
    base["generated_at"] = datetime.now(timezone.utc).isoformat()
    base["status"] = "published"
    for sk in (f"RECAP#{date_str}", "RECAP#latest"):
        item = dict(base)
        item["sk"] = sk
        table.put_item(Item=item)
    logger.info("[recap] wrote RECAP#latest + RECAP#%s", date_str)


def _chronicle_day_n(date_str):
    """1-indexed experiment day for the recap's as_of date — powers the read-time
    stale guard (a pre-reset record surviving a genesis re-anchor is withheld)."""
    try:
        start = datetime.strptime(EXPERIMENT_START_DATE, "%Y-%m-%d").date()
        d = datetime.strptime(date_str, "%Y-%m-%d").date()
        return max(1, (d - start).days + 1)
    except Exception:
        return None


# ══════════════════════════════════════════════════════════════════════════════
# MARKDOWN → HTML CONVERTER (simple prose conversion)
# ══════════════════════════════════════════════════════════════════════════════


def markdown_to_html(md_text):
    """Convert Elena's markdown prose to clean HTML for email and journal."""
    lines = md_text.strip().split("\n")
    html_parts = []
    in_blockquote = False
    bq_buffer = []

    for line in lines:
        stripped = line.strip()

        # Blockquotes (Board interviews)
        if stripped.startswith("> "):
            if not in_blockquote:
                in_blockquote = True
                bq_buffer = []
            bq_buffer.append(stripped[2:])
            continue
        elif in_blockquote:
            # End of blockquote
            bq_text = " ".join(bq_buffer)
            # Convert **bold** and *italic*
            bq_text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", bq_text)
            bq_text = re.sub(r"\*(.+?)\*", r"<em>\1</em>", bq_text)
            html_parts.append(f"<blockquote>{bq_text}</blockquote>")
            in_blockquote = False
            bq_buffer = []

        # Horizontal rule
        if stripped == "---":
            html_parts.append("<hr>")
            continue

        # Empty line
        if not stripped:
            continue

        # Italic line (closing signature like *Week N of The Measured Life*)
        if stripped.startswith("*") and stripped.endswith("*") and not stripped.startswith("**"):
            inner = stripped[1:-1]
            html_parts.append(f'<p class="signature"><em>{inner}</em></p>')
            continue

        # Regular paragraph — apply inline formatting
        text = stripped
        text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
        text = re.sub(r"\*(.+?)\*", r"<em>\1</em>", text)
        html_parts.append(f"<p>{text}</p>")

    # Flush any remaining blockquote
    if in_blockquote and bq_buffer:
        bq_text = " ".join(bq_buffer)
        bq_text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", bq_text)
        bq_text = re.sub(r"\*(.+?)\*", r"<em>\1</em>", bq_text)
        html_parts.append(f"<blockquote>{bq_text}</blockquote>")

    return "\n".join(html_parts)


# ══════════════════════════════════════════════════════════════════════════════
# PARSE INSTALLMENT
# ══════════════════════════════════════════════════════════════════════════════


def parse_installment(raw_text):
    """Extract title, stats line, and body from Elena's output."""
    lines = raw_text.strip().split("\n")
    title = "Untitled"
    stats_line = ""
    body_lines = []

    i = 0
    # Find title (first non-empty line, usually in quotes)
    while i < len(lines) and not lines[i].strip():
        i += 1
    if i < len(lines):
        title = lines[i].strip().strip('"').strip('"').strip('"')
        i += 1

    # Find stats line (contains "Weight:" or starts with "[")
    while i < len(lines):
        stripped = lines[i].strip()
        if not stripped:
            i += 1
            continue
        if "Weight:" in stripped or stripped.startswith("["):
            stats_line = stripped.strip("[]")
            i += 1
            break
        else:
            # No stats line found, this is body
            break

    # Rest is body
    body_lines = lines[i:]
    body = "\n".join(body_lines).strip()

    return title, stats_line, body


# ══════════════════════════════════════════════════════════════════════════════
# EMAIL HTML
# ══════════════════════════════════════════════════════════════════════════════


def build_email_html(title, stats_line, body_html, week_num, date_str, series_url):
    """Build a newsletter-style email — clean white, editorial, readable."""
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        date_display = dt.strftime("%B %-d, %Y")
    except Exception:
        date_display = date_str

    # BS-05: Confidence badge — Chronicle is always n=7 (one week of data)
    # Henning: n<14 = LOW. Correct — weekly snapshot is preliminary by design.
    try:
        _conf = compute_confidence(days_of_data=7)
        _badge_html = _conf["badge_html"]
    except Exception:
        _badge_html = _confidence_badge("LOW") if _HAS_CONFIDENCE else ""

    return f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><style>@media (prefers-color-scheme: dark){{body{{background:#1a1a1f !important;color:#e5e5e5 !important}}div[style*="background:#fafaf9"],div[style*="background:#fff"]{{background:#22222a !important;color:#e5e5e5 !important}}h1,h2,h3,h4{{color:#f5f5f5 !important}}td{{color:#d5d5d5 !important}}}}</style></head>
<body style="margin:0;padding:0;background:#f5f5f0;font-family:Georgia,'Times New Roman',serif;">
<div style="max-width:600px;margin:24px auto;background:#fafaf9;border-radius:4px;overflow:hidden;box-shadow:0 1px 4px rgba(0,0,0,0.06);">

  <!-- Masthead -->
  <div style="padding:32px 40px 20px;border-bottom:1px solid #e5e5e0;text-align:center;">
    <p style="font-family:-apple-system,sans-serif;font-size:11px;letter-spacing:3px;color:#999;margin:0 0 8px;text-transform:uppercase;">The Measured Life</p>
    <p style="font-family:-apple-system,sans-serif;font-size:13px;color:#666;margin:0;">An ongoing chronicle by Elena Voss</p>
  </div>

  <!-- Title block -->
  <div style="padding:28px 40px 8px;">
    <h1 style="font-size:26px;font-weight:400;color:#1a1a1a;margin:0 0 8px;line-height:1.3;font-style:italic;">"{title}"</h1>
    <p style="font-family:-apple-system,sans-serif;font-size:12px;color:#999;margin:0;">Week {week_num} &middot; {date_display}</p>
    <p style="font-family:-apple-system,sans-serif;font-size:11px;color:#b0b0a8;margin:6px 0 0;">{stats_line} {_badge_html}</p>
  </div>

  <!-- Body -->
  <div style="padding:12px 40px 32px;font-size:16px;line-height:1.75;color:#333;">
    <style>
      p {{ margin: 0 0 18px; }}
      blockquote {{ margin: 20px 0; padding: 12px 20px; border-left: 3px solid #d4d4c8; background: #f0f0ea; font-style: italic; color: #555; font-size: 15px; line-height: 1.7; }}
      blockquote strong {{ font-style: normal; color: #333; }}
      hr {{ border: none; border-top: 1px solid #e5e5e0; margin: 28px 0; }}
      .signature {{ text-align: center; color: #999; font-size: 14px; }}
    </style>
    {body_html}
  </div>

  <!-- Footer -->
  <div style="padding:20px 40px;border-top:1px solid #e5e5e0;text-align:center;">
    <p style="font-family:-apple-system,sans-serif;font-size:11px;color:#999;margin:0;">
      Read the full series at <a href="{series_url}" style="color:#666;">averagejoematt.com/story/chronicle</a>
    </p>
    <p style="font-family:-apple-system,sans-serif;font-size:12px;color:#888;margin:10px 0 4px;">Know someone who'd want this? They can get their own at <a href="https://averagejoematt.com/subscribe" style="color:#555;">averagejoematt.com/subscribe</a></p>
    <p style="font-family:-apple-system,sans-serif;font-size:9px;color:#bbb;margin:6px 0 0;">&#9874;&#65039; Personal health tracking only &mdash; not medical advice. Consult a qualified healthcare professional before making changes to your diet, exercise, or supplement regimen.</p>
  </div>

</div>
</body>
</html>"""


# ══════════════════════════════════════════════════════════════════════════════
# JOURNAL PUBLISHER (averagejoematt.com/journal/) — Signal aesthetic
# Writes to generated/journal/posts/week-{nn}/index.html + generated/journal/posts.json
# ══════════════════════════════════════════════════════════════════════════════


_JOURNAL_ROMAN = {1: "I", 2: "II", 3: "III", 4: "IV", 5: "V", 6: "VI", 7: "VII", 8: "VIII"}


def journal_post_ref(date_str, all_installments, week_num):
    """The canonical journal-post reference for a chronicle date: (seq, label, url).

    #405: the share kit derives its canonical URL + card slug from the SAME sequential
    index the post is actually written to (``week-{seq:02d}``) — NOT the genesis-anchored
    week number (they diverge once pre-genesis prologue installments exist). This mirrors
    the ``_seq_for`` / ``_series_label`` closures inside ``publish_to_journal``; the two
    are pinned together by test_chronicle_share_kit so the kit can never point at a card
    slug the post doesn't live at.
    """
    genesis = EXPERIMENT_START_DATE
    all_dates = sorted(x.get("date", "") for x in all_installments if x.get("date", ""))
    pre = [d for d in all_dates if d < genesis]
    if date_str and date_str < genesis:
        n = pre.index(date_str) + 1 if date_str in pre else 1
        label = f"Prologue · Part {_JOURNAL_ROMAN.get(n, n)}"
    elif date_str:
        try:
            wk = max(
                1,
                ((datetime.strptime(date_str, "%Y-%m-%d").date() - datetime.strptime(genesis, "%Y-%m-%d").date()).days // 7) + 1,
            )
        except Exception:
            wk = int(week_num)
        label = f"Week {wk}"
    else:
        label = f"Week {int(week_num)}"
    seq = (all_dates.index(date_str) + 1) if date_str in all_dates else int(week_num)
    url = f"https://averagejoematt.com/journal/posts/week-{seq:02d}/"
    return seq, label, url


# #949 — the reader-facing dek for PRE-GENESIS lead-ins, reframed. The stored
# stats_line was authored mid-experiment ("… | Week 1 of The Measured Life"),
# which contradicts the prologue framing (only /data/cycles/ acknowledges prior
# attempts). Render parity with deploy/restart_leadin_pages.display_stats_line —
# both rebuild the SAME manifest, so a Wednesday publish must not resurrect the
# raw mid-experiment dek the reset's leadin pass reframed. DDB is never modified.
_WEEK_SEG_RE = re.compile(r"(?i)^week\s+\d+\b")
_PROLOGUE_HINT_RE = re.compile(r"(?i)prologue|before day 1")


def display_stats_line(stats_line, date_str):
    line = str(stats_line or "")
    if not date_str or date_str >= EXPERIMENT_START_DATE:
        return line
    parts = [p.strip() for p in line.split("|") if p.strip()]
    kept = [p for p in parts if not _WEEK_SEG_RE.match(p)]
    if not any(_PROLOGUE_HINT_RE.search(p) for p in kept):
        kept.append("Prologue — the instrumented weeks before Day 1")
    return " | ".join(kept)


def publish_to_journal(title, stats_line, body_html, week_num, date_str, all_installments, write_to_s3=True):
    """Publish installment to the Signal-themed journal on averagejoematt.com.

    Writes:
      generated/journal/posts/week-{nn}/index.html  — the post itself
      generated/journal/posts.json                   — manifest for the listing page

    Non-fatal: failure here never breaks the Chronicle email.

    FEAT-12: If write_to_s3=False, returns (post_key, post_html, posts_json_str) tuple.
    """
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        date_display = dt.strftime("%B %-d, %Y")
    except Exception:
        date_display = date_str

    # Series label is anchored to the experiment GENESIS, not the installment count: posts dated
    # before genesis are the PROLOGUE (backstory), and the experiment week count starts at 1 on
    # the genesis week. URLs stay sequential (week-NN, prologue-inclusive) so existing links never
    # break; the visible label is what carries the truth. (Fixes the "Week 3 / three weeks" error
    # where pre-genesis lead-ins were numbered as experiment weeks — 2026-06-21.)
    _ROMAN = {1: "I", 2: "II", 3: "III", 4: "IV", 5: "V", 6: "VI", 7: "VII", 8: "VIII"}
    _genesis = EXPERIMENT_START_DATE
    _all_dates = sorted(x.get("date", "") for x in all_installments if x.get("date", ""))
    _pre = [d for d in _all_dates if d < _genesis]

    def _series_label(d):
        if not d:
            return f"Week {int(week_num)}"
        if d < _genesis:
            n = _pre.index(d) + 1 if d in _pre else 1
            return f"Prologue · Part {_ROMAN.get(n, n)}"
        try:
            wk = max(1, ((datetime.strptime(d, "%Y-%m-%d").date() - datetime.strptime(_genesis, "%Y-%m-%d").date()).days // 7) + 1)
        except Exception:
            wk = int(week_num)
        return f"Week {wk}"

    def _seq_for(d):
        return (_all_dates.index(d) + 1) if d in _all_dates else int(week_num)

    cur_label = _series_label(date_str)
    cur_seq = _seq_for(date_str)

    # Editorial cover image (Part II — atmospheric, free-license; fail-soft, kill-switch
    # default OFF). Carry past images forward from the existing manifest so we only fetch
    # for the NEW post (skip-if-set). ANY failure → no image, normal publish.
    cur_url = f"/journal/posts/week-{cur_seq:02d}/"
    _prior_imgs = {}
    cur_image = {}
    try:
        import editorial_image

        if editorial_image.enabled():
            try:
                _pj = json.loads(s3.get_object(Bucket=S3_BUCKET, Key="generated/journal/posts.json")["Body"].read())
                for _p in _pj.get("posts", []):
                    if _p.get("image_url"):
                        _prior_imgs[_p.get("url")] = {"image_url": _p["image_url"], "image_credit": _p.get("image_credit", "")}
            except Exception:
                _prior_imgs = {}
            cur_image = (
                _prior_imgs.get(cur_url)
                or editorial_image.fetch_and_store("chronicle", f"week-{cur_seq:02d}", cur_seq, s3_client=s3, secrets_client=secrets)
                or {}
            )
    except Exception:
        cur_image = {}

    _art_html = ""
    if cur_image.get("image_url"):
        _art_html = (
            '<figure class="post-header__art">'
            f'<img src="{cur_image["image_url"]}" alt="" loading="lazy">'
            f'<figcaption>{cur_image.get("image_credit", "")}</figcaption>'
            "</figure>"
        )

    # Extract read time (~250 words/min)
    word_count = len(body_html.split())
    read_min = max(4, round(word_count / 250))

    # Convert body_html (built for email) to prose-ready Signal HTML.
    # v5 template (#384): the live story-top five-door header + site-foot, editorial
    # cover as og:image, rel=canonical to the un-redirected /journal/posts/ URL, and an
    # end-of-read subscribe CTA. Chrome ported from scripts/v4_build_dispatches.py SHELL;
    # reading styles are chronicle-local and token-based (tokens.css .prose is the base).
    og_image = cur_image.get("image_url") or "https://averagejoematt.com/assets/images/og-home.png"
    canonical_url = f"https://averagejoematt.com/journal/posts/week-{cur_seq:02d}/"
    post_html = f"""<!DOCTYPE html>
<html lang="en" data-door="story">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover">
  <title>{title} — The Measured Life</title>
  <meta name="description" content="{title} — {cur_label} of The Measured Life by Elena Voss">
  <link rel="canonical" href="{canonical_url}">
  <meta property="og:type" content="article">
  <meta property="og:site_name" content="averagejoematt">
  <meta property="og:url" content="{canonical_url}">
  <meta property="og:title" content="{title} — The Measured Life">
  <meta property="og:description" content="{stats_line}">
  <meta property="og:image" content="{og_image}">
  <meta name="twitter:card" content="summary_large_image">
  <meta name="twitter:title" content="{title} — The Measured Life">
  <meta name="twitter:description" content="{stats_line}">
  <meta name="twitter:image" content="{og_image}">
  <meta name="theme-color" media="(prefers-color-scheme: light)" content="#F4EFE4">
  <meta name="theme-color" media="(prefers-color-scheme: dark)" content="#0E0C08">
  <link rel="icon" href="/favicon.ico">
  <link rel="manifest" href="/manifest.webmanifest">
  <meta name="apple-mobile-web-app-capable" content="yes">
  <meta name="apple-mobile-web-app-title" content="Measured Life">
  <link rel="apple-touch-icon" href="/apple-touch-icon.png">
  <link rel="alternate" type="application/rss+xml" title="averagejoematt" href="/rss.xml">
  <script type="application/ld+json">
  {{
    "@context": "https://schema.org",
    "@type": "BlogPosting",
    "headline": "{title}",
    "description": "{cur_label} of The Measured Life by Elena Voss",
    "datePublished": "{datetime.now(timezone.utc).date().isoformat()}",
    "author": {{"@type": "Person", "name": "Elena Voss"}},
    "image": "{og_image}",
    "publisher": {{
      "@type": "Organization",
      "name": "The Measured Life",
      "url": "https://averagejoematt.com",
      "logo": {{"@type": "ImageObject", "url": "https://averagejoematt.com/apple-touch-icon.png"}}
    }},
    "mainEntityOfPage": {{"@type": "WebPage", "@id": "{canonical_url}"}},
    "articleSection": "Health Transformation",
    "isPartOf": {{"@type": "Blog", "name": "The Measured Life", "url": "https://averagejoematt.com/story/chronicle/"}}
  }}
  </script>
  <link rel="stylesheet" href="/assets/css/fonts.css">
  <link rel="stylesheet" href="/assets/css/tokens.css">
  <link rel="stylesheet" href="/assets/css/story.css">
  <script>(function(){{try{{var t=localStorage.getItem("ajm-theme");if(t==="light"||t==="dark")document.documentElement.dataset.theme=t;}}catch(e){{}}}})();</script>
  <style>
    .reading-progress {{ position:fixed;top:0;left:0;right:0;height:2px;background:transparent;z-index:var(--z-overlay); }}
    .reading-progress__fill {{ height:100%;background:var(--ember);width:0%;transition:width 0.1s linear; }}
    .post-wrap {{ max-width:var(--container-read);margin:0 auto;padding-inline:var(--gutter); }}
    .post-header {{ padding:var(--sp-8) 0 var(--sp-6);border-bottom:var(--border-hair); }}
    .post-header__art {{ margin:0 0 var(--sp-5);border-radius:var(--radius);overflow:hidden;position:relative;aspect-ratio:21/9;background:#16130E; }}
    .post-header__art img {{ width:100%;height:100%;object-fit:cover;filter:saturate(.62) contrast(1.03); }}
    .post-header__art figcaption {{ position:absolute;right:8px;bottom:6px;font:11px/1.4 var(--font-mono);color:#e7dccb;background:rgba(0,0,0,.5);padding:2px 7px;border-radius:var(--radius-xs); }}
    .post-header__series {{ font-family:var(--font-mono);font-size:var(--fs-label);letter-spacing:var(--tracking-label);text-transform:uppercase;color:var(--ember);margin-bottom:var(--sp-3); }}
    .post-header__title {{ font-family:var(--font-serif);font-size:var(--fs-h1);color:var(--ink);line-height:var(--lh-snug);font-weight:var(--weight-reg);font-style:italic;margin-bottom:var(--sp-4); }}
    .post-header__meta {{ display:flex;align-items:center;gap:var(--sp-3);font-family:var(--font-mono);font-size:var(--fs-label);letter-spacing:var(--tracking-label);text-transform:uppercase;color:var(--ink-muted); }}
    .post-header__stats {{ font-family:var(--font-mono);font-size:var(--fs-label);color:var(--ink-faint);letter-spacing:var(--tracking-label);margin-top:var(--sp-2); }}
    .post-body {{ padding:var(--sp-7) 0 var(--sp-8); }}
    .post-body .prose {{ font-family:var(--font-serif);max-width:none; }}
    .post-body .prose p {{ max-width:none;line-height:var(--lh-relaxed); }}
    .post-body .prose > p:first-of-type::first-letter {{ font-size:64px;line-height:0.8;float:left;margin-right:var(--sp-2);margin-top:6px;color:var(--ember);font-family:var(--font-serif); }}
    .post-body .prose blockquote {{ border-left:2px solid var(--ember);padding:var(--sp-3) var(--sp-5);background:var(--ember-wash);margin:var(--sp-6) 0;font-style:italic;color:var(--ink); }}
    .post-body .prose hr {{ border:none;border-top:var(--border-hair);margin:var(--sp-7) 0; }}
    .post-body .prose .signature {{ text-align:center;font-size:var(--fs-small);color:var(--ink-muted);font-style:italic; }}
    .post-body .prose strong {{ color:var(--ink);font-weight:var(--weight-med); }}
    .post-cta {{ margin:var(--sp-6) 0 var(--sp-7);padding:var(--sp-6);border:var(--border-hair);border-radius:var(--radius);background:var(--ember-wash);text-align:center; }}
    .post-cta h2 {{ font-family:var(--font-serif);font-style:italic;font-weight:var(--weight-reg);font-size:var(--fs-h3);color:var(--ink);margin:0 0 var(--sp-2); }}
    .post-cta p {{ color:var(--ink-muted);font-size:var(--fs-small);margin:0 auto var(--sp-4);max-width:44ch; }}
    .post-cta a.cta-btn {{ display:inline-block;font-family:var(--font-mono);font-size:var(--fs-label);letter-spacing:var(--tracking-label);text-transform:uppercase;color:var(--page);background:var(--ember);padding:10px 20px;border-radius:var(--radius-sm);text-decoration:none; }}
    .post-cta a.cta-btn:hover {{ filter:brightness(1.08); }}
    .post-nav {{ padding:var(--sp-5) 0 var(--sp-8);border-top:var(--border-hair);display:flex;justify-content:space-between;gap:var(--sp-5); }}
    .post-nav a {{ font-family:var(--font-serif);font-size:var(--fs-body);color:var(--ink);text-decoration:none;transition:color var(--dur-fast); }}
    .post-nav a:hover {{ color:var(--ember); }}
    .post-nav span {{ display:block;font-family:var(--font-mono);font-size:var(--fs-label);letter-spacing:var(--tracking-label);text-transform:uppercase;color:var(--ink-faint);margin-bottom:var(--sp-1); }}
  </style>
</head>
<body class="dx-page">
<a class="skip" href="#post">Skip to the story</a>
<div class="reading-progress"><div class="reading-progress__fill" id="rp"></div></div>
<header class="story-top">
  <a class="brand" href="/"><span class="brand-mark" aria-hidden="true"></span><span class="brand-name">averagejoematt</span> <span class="brand-door label">the story</span></a>
  <nav class="doors" aria-label="Doors">
    <a href="/now/" title="Today's live instrument — your daily numbers, read back to you"><svg class="ico ico-door" viewBox="0 0 24 24" aria-hidden="true" focusable="false"><use href="/assets/icons/icons.svg#i-door-cockpit"></use></svg>the cockpit</a>
    <a href="/data/" title="Every source the platform reads — trends now and over time"><svg class="ico ico-door" viewBox="0 0 24 24" aria-hidden="true" focusable="false"><use href="/assets/icons/icons.svg#i-door-data"></use></svg>the data</a>
    <a href="/coaching/" title="The AI team &amp; their arguments — stances, track records, disagreements"><svg class="ico ico-door" viewBox="0 0 24 24" aria-hidden="true" focusable="false"><use href="/assets/icons/icons.svg#i-door-coaching"></use></svg>the coaching</a>
    <a href="/protocols/" title="The levers — supplements, experiments, challenges, discoveries"><svg class="ico ico-door" viewBox="0 0 24 24" aria-hidden="true" focusable="false"><use href="/assets/icons/icons.svg#i-door-protocols"></use></svg>the protocols</a>
    <a href="/story/" aria-current="page" title="The writing &amp; the why — chronicle, journal, timeline, about"><svg class="ico ico-door" viewBox="0 0 24 24" aria-hidden="true" focusable="false"><use href="/assets/icons/icons.svg#i-door-story"></use></svg>the story</a>
    <button class="theme-toggle" type="button" aria-label="Toggle light and dark"><span class="theme-dot" aria-hidden="true"></span></button>
  </nav>
</header>
<main id="post">
<div class="post-wrap">
  <div class="post-header">
    {_art_html}
    <div class="post-header__series">The Measured Life &middot; {cur_label} &middot; By Elena Voss</div>
    <h1 class="post-header__title">&ldquo;{title}&rdquo;</h1>
    <div class="post-header__meta">
      <span>{date_display}</span>
      <span>&middot;</span>
      <span>{read_min} min read</span>
    </div>
    <div class="post-header__stats">{stats_line}</div>
  </div>
  <article class="post-body">
    <div class="prose">
      {body_html}
    </div>
  </article>
  <aside class="post-cta">
    <h2>Follow the experiment</h2>
    <p>A new installment every week — the data, the coaches, and what actually moved. No spam, unsubscribe anytime.</p>
    <a class="cta-btn" href="/subscribe/">Follow by email</a>
  </aside>
  <nav class="post-nav">
    <a href="/story/chronicle/"><span>&larr; All installments</span>The Measured Life archive</a>
    <a href="/now/"><span>Today</span>The live cockpit &rarr;</a>
  </nav>
</div>
</main>
<footer class="site-foot">
  <nav class="site-foot-cols" aria-label="Site map">
    <div class="sf-col"><p class="sf-h label">The Story</p>
      <a href="/story/chronicle/">Chronicle</a><a href="/story/panel/">Podcast</a><a href="/story/journal/">In my own words</a><a href="/story/timeline/">Timeline</a><a href="/story/about/">About</a></div>
    <div class="sf-col"><p class="sf-h label">The Coaching</p>
      <a href="/coaching/">The Team</a><a href="/coaching/lab-notes/">AI lab notes</a></div>
    <div class="sf-col"><p class="sf-h label">The Data</p>
      <a href="/data/">All topics</a><a href="/method/ask/">Ask the data</a><a href="/data/labs/">Labs</a><a href="/data/training/">Training</a><a href="/data/sleep/">Sleep</a></div>
    <div class="sf-col"><p class="sf-h label">The Protocols</p>
      <a href="/protocols/">All protocols</a><a href="/protocols/supplements/">Supplements</a><a href="/protocols/experiments/">Experiments</a><a href="/protocols/challenges/">Challenges</a></div>
    <div class="sf-col"><p class="sf-h label">Follow &amp; context</p>
      <a href="/subscribe/">Follow by email</a><a href="/rss.xml">RSS</a><a href="/method/">The method</a><a href="/story/about/">About</a><a href="/privacy/">Privacy</a></div>
  </nav>
  <p class="sf-base label"><span>averagejoematt · the story</span><a href="/">← home</a></p>
</footer>
<script>
  (function(){{
    var b=document.querySelector('.theme-toggle');
    if(b){{b.addEventListener('click',function(){{
      var r=document.documentElement;
      var cur=r.dataset.theme||(matchMedia('(prefers-color-scheme: light)').matches?'light':'dark');
      var next=cur==='light'?'dark':'light';
      r.dataset.theme=next;
      try{{localStorage.setItem('ajm-theme',next);}}catch(e){{}}
    }});}}
    var rp=document.getElementById('rp');
    window.addEventListener('scroll',function(){{
      if(!rp)return;
      var pct=window.scrollY/(document.body.scrollHeight-window.innerHeight)*100;
      rp.style.width=Math.min(pct,100)+'%';
    }});
  }})();
</script>
</body>
</html>"""

    post_key = f"generated/journal/posts/week-{cur_seq:02d}/index.html"

    # Update posts.json manifest — ordered newest-first by DATE (not by a week number, which now
    # collides: a pre-genesis prologue and the genesis Week 1 can share a raw number). URLs are the
    # stable sequential index; "label" carries the genesis-anchored truth (Prologue vs Week N).
    posts_manifest = []
    for inst in sorted(all_installments, key=lambda x: x.get("date", ""), reverse=True):
        idate = inst.get("date", "")
        seq = _seq_for(idate)
        _u = f"/journal/posts/week-{seq:02d}/"
        # current post → freshly fetched image; past posts → carried forward from the prior manifest.
        _im = cur_image if idate == date_str else _prior_imgs.get(_u, {})
        posts_manifest.append(
            {
                "week": int(inst.get("week_number", 0) or 0),
                "label": _series_label(idate),
                "title": inst.get("title", ""),
                "date": idate,
                "stats_line": display_stats_line(inst.get("stats_line", ""), idate),  # #949 — prologue-framed dek pre-genesis
                "url": _u,
                "excerpt": (inst.get("content_markdown") or "")[:300].strip(),
                "word_count": inst.get("word_count", 0),
                "has_board_interview": inst.get("has_board_interview", False),
                "image_url": _im.get("image_url", ""),
                "image_credit": _im.get("image_credit", ""),
            }
        )
    posts_json_str = json.dumps(
        {"posts": posts_manifest, "updated_at": datetime.now(timezone.utc).isoformat()},
        indent=2,
    )

    if not write_to_s3:
        return post_key, post_html, posts_json_str

    # Write the post
    s3.put_object(
        Bucket=S3_BUCKET,
        Key=post_key,
        Body=post_html.encode("utf-8"),
        ContentType="text/html; charset=utf-8",
        CacheControl="max-age=300",
    )
    logger.info(f"[journal] Post written: {post_key}")

    s3.put_object(
        Bucket=S3_BUCKET,
        Key="generated/journal/posts.json",
        Body=posts_json_str.encode("utf-8"),
        ContentType="application/json",
        CacheControl="max-age=300",
    )
    logger.info(f"[journal] posts.json manifest updated ({len(posts_manifest)} posts)")

    return f"https://averagejoematt.com/journal/posts/week-{week_num:02d}/"


# ══════════════════════════════════════════════════════════════════════════════
# STORE INSTALLMENT
# ══════════════════════════════════════════════════════════════════════════════


def build_weekly_signal_data(data, week_num):
    """Extract structured metrics for the Weekly Signal email template."""
    BOARD_ROTATION = [
        "sarah_chen",
        "marcus_webb",
        "lisa_park",
        "james_okafor",
        "maya_rodriguez",
        "layne_norton",
        "rhonda_patrick",
        "peter_attia",
        "andrew_huberman",
        "paul_conti",
        "vivek_murthy",
        "the_chair",
        "margaret_calloway",
        "elena_voss",
    ]
    OBSERVATORY_ROTATION = [
        {"slug": "sleep", "name": "Sleep Observatory", "hook": "How does recovery score connect to sleep architecture?"},
        {"slug": "training", "name": "Training Observatory", "hook": "Zone 2 base, progressive overload, and the fitness-fatigue model."},
        {"slug": "nutrition", "name": "Nutrition Observatory", "hook": "Macros, meal timing, and the protein distribution puzzle."},
        {"slug": "glucose", "name": "Glucose Observatory", "hook": "What does the CGM reveal about real-time metabolic response?"},
        {"slug": "mind", "name": "Inner Life Observatory", "hook": "Journal sentiment, mood trajectory, and the mind-body connection."},
        {"slug": "character", "name": "Character Sheet", "hook": "The RPG-style score that tracks the whole transformation."},
        {"slug": "benchmarks", "name": "Benchmarks", "hook": "Centenarian decathlon targets and where the numbers stand today."},
    ]

    profile = data.get("profile") or {}
    withings = data.get("withings") or {}
    whoop = data.get("whoop") or {}
    sleep_data = data.get("sleep") or {}
    strava = data.get("strava") or {}
    habits = data.get("habits") or {}
    grades = data.get("day_grades") or {}

    # Weight
    weight_lbs = None
    if withings.get("weight_kg"):
        weight_lbs = round(float(withings["weight_kg"]) * 2.20462, 1)
    start_weight = float(profile.get("journey_start_weight_lbs", EXPERIMENT_BASELINE_WEIGHT_LBS))  # Matthew-specific fallback
    weight_delta = round(start_weight - weight_lbs, 1) if weight_lbs else None

    # Sleep
    sleep_hrs = float(sleep_data.get("sleep_duration_hours", 0) or 0)
    sleep_eff = float(sleep_data.get("sleep_efficiency_pct", 0) or whoop.get("sleep_efficiency_pct", 0) or 0)

    # Training
    activities = strava.get("activities") or []
    training_sessions = len(activities) if isinstance(activities, list) else int(activities or 0)

    # Habits
    habit_completed = int(habits.get("tier0_completed", 0) or 0)
    habit_possible = int(habits.get("tier0_possible", 1) or 1)
    habit_pct = round((habit_completed / habit_possible) * 100) if habit_possible > 0 else 0

    # Recovery
    recovery_pct = float(whoop.get("recovery_score", 0) or 0)
    hrv_ms = float(whoop.get("hrv", 0) or whoop.get("hrv_yesterday", 0) or 0)

    # Day grades
    avg_grade = grades.get("avg_score") or grades.get("total_score") or 0

    # Journey days
    journey_start = profile.get("journey_start_date", EXPERIMENT_START_DATE)
    try:
        start_dt = datetime.strptime(journey_start, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        journey_days = max(0, (datetime.now(timezone.utc) - start_dt).days)
    except Exception:
        journey_days = 0

    featured_member_id = BOARD_ROTATION[(week_num - 1) % len(BOARD_ROTATION)]
    featured_observatory = OBSERVATORY_ROTATION[(week_num - 1) % len(OBSERVATORY_ROTATION)]

    return {
        "weight_lbs": weight_lbs,
        "weight_delta_journey_lbs": weight_delta,
        "avg_sleep_hours": round(sleep_hrs, 1),
        "avg_sleep_efficiency_pct": round(sleep_eff),
        "training_sessions": training_sessions,
        "habit_pct": habit_pct,
        "habits_completed": habit_completed,
        "habits_possible": habit_possible,
        "avg_recovery_pct": round(recovery_pct),
        "avg_hrv_ms": round(hrv_ms),
        "avg_day_grade": round(float(avg_grade), 1) if avg_grade else 0,
        "journey_days": journey_days,
        "featured_member_id": featured_member_id,
        "featured_observatory": featured_observatory,
    }


def store_installment(
    date_str,
    week_num,
    title,
    stats_line,
    raw_markdown,
    body_html,
    themes,
    has_board,
    confidence_level="MEDIUM",
    confidence_badge_html="",  # BS-05
    status="published",
    approval_token=None,
    draft_journal_post_html=None,
    draft_journal_post_key=None,
    draft_journal_posts_json=None,
    draft_email_html=None,
    draft_recap_json=None,
    draft_share_kit_json=None,
    weekly_signal_data=None,
    weekly_signal_wins_losses=None,
    weekly_signal_board_quote=None,
):
    """Store installment in DynamoDB for continuity and journal generation.

    FEAT-12: In preview mode, status="draft" with approval_token + pre-built HTML blobs stored
    so chronicle-approve Lambda can publish to S3 without re-generating content.
    """
    try:
        item = {
            "pk": f"USER#{USER_ID}#SOURCE#chronicle",
            "sk": f"DATE#{date_str}",
            "date": date_str,
            "source": "chronicle",
            "week_number": week_num,
            "title": title,
            "subtitle": f"Week {week_num} of The Measured Life",
            "stats_line": stats_line,
            "content_markdown": raw_markdown,
            "content_html": body_html,
            "word_count": len(raw_markdown.split()),
            "has_board_interview": has_board,
            "series_title": "The Measured Life",
            "author": "Elena Voss",
            "_confidence_level": confidence_level,  # BS-05
            "_confidence_badge_html": confidence_badge_html,  # BS-05 — used by chronicle-email-sender
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "status": status,
        }
        if approval_token:
            item["approval_token"] = approval_token
        if draft_journal_post_html:
            item["draft_journal_post_html"] = draft_journal_post_html
        if draft_journal_post_key:
            item["draft_journal_post_key"] = draft_journal_post_key
        if draft_journal_posts_json:
            item["draft_journal_posts_json"] = draft_journal_posts_json
        if draft_email_html:
            item["draft_email_html"] = draft_email_html
        # Phase 3: the "previously on" recap, built now but committed to RECAP#latest
        # only when this week is published (chronicle_approve._commit_recap).
        if draft_recap_json:
            item["draft_recap_json"] = draft_recap_json
        # #405: the share kit, built at draft time, written to S3 at approve/publish.
        if draft_share_kit_json:
            item["draft_share_kit_json"] = draft_share_kit_json
        if weekly_signal_data:
            item["weekly_signal_data"] = json.dumps(weekly_signal_data) if isinstance(weekly_signal_data, dict) else weekly_signal_data
        if weekly_signal_wins_losses:
            item["weekly_signal_wins_losses"] = (
                json.dumps(weekly_signal_wins_losses) if isinstance(weekly_signal_wins_losses, dict) else weekly_signal_wins_losses
            )
        if weekly_signal_board_quote:
            item["weekly_signal_board_quote"] = weekly_signal_board_quote
        table.put_item(Item=item)
        logger.info(f"Installment stored: Week {week_num} (status={status})")
    except Exception as e:
        logger.warning(f"Failed to store installment: {e}")


def _set_chronicle_pending(week_num, reason, display):
    """Record a non-blocking 'pending installment' marker on generated/journal/posts.json
    so the Chronicle listing can say WHY no new week landed instead of just going stale
    (#803 — the same silent-skip fix already shipped for the Panel podcast, see
    coach_panel_podcast_lambda._set_pending, 2026-06-20). Called when a week's draft is
    generated and then withheld (budget guard, privacy gate) rather than published — the
    week number can legitimately advance past a held week, so the marker also tells a
    reader whose numbering was skipped and why, rather than leaving a silent gap.

    A successful publish rewrites posts.json via publish_to_journal() (which never writes
    a `pending` key), so the marker clears itself the next time a week actually ships.
    Fail-open: surfacing a pending state must never break the run."""
    try:
        try:
            doc = json.loads(s3.get_object(Bucket=S3_BUCKET, Key="generated/journal/posts.json")["Body"].read())
        except Exception:
            doc = {"posts": []}
        doc["pending"] = {
            "week": week_num,
            "reason": reason,
            "display": display,
            "noted_at": datetime.now(timezone.utc).isoformat(),
        }
        s3.put_object(
            Bucket=S3_BUCKET,
            Key="generated/journal/posts.json",
            Body=json.dumps(doc, indent=2).encode("utf-8"),
            ContentType="application/json",
            CacheControl="max-age=300",
        )
        logger.info(f"[chronicle] pending marker set: week={week_num} reason={reason}")
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[chronicle] _set_chronicle_pending failed (non-fatal): {e}")


# ══════════════════════════════════════════════════════════════════════════════
# FEAT-12: PREVIEW EMAIL
# ══════════════════════════════════════════════════════════════════════════════


def _send_preview_email(title, week_num, date_str, approval_token, email_html, kit_block=""):
    """Send preview email to RECIPIENT with Approve / Request Changes links.

    The approve link goes to APPROVE_LAMBDA_URL with ?date=, token=, action=approve.
    The request_changes link uses action=request_changes.

    #405: `kit_block` is the copy-paste share-kit HTML — surfaced right in this approval
    email so posting is a 60-second paste (or ignored). It's injected before </body>.
    """
    if not APPROVE_LAMBDA_URL:
        logger.warning("FEAT-12: APPROVE_LAMBDA_URL not set — preview email links will be dead")

    base_url = APPROVE_LAMBDA_URL.rstrip("/")
    approve_url = f"{base_url}?date={date_str}&token={approval_token}&action=approve"
    changes_url = f"{base_url}?date={date_str}&token={approval_token}&action=request_changes"

    preview_banner = f"""
<div style="background:#1a1a1a;color:#fff;padding:20px 32px;font-family:-apple-system,sans-serif;margin-bottom:0;border-bottom:3px solid #f59e0b;">
  <p style="margin:0 0 6px;font-size:12px;letter-spacing:2px;text-transform:uppercase;color:#f59e0b;">PREVIEW — Not yet published</p>
  <p style="margin:0 0 16px;font-size:14px;color:#ccc;">Week {week_num}: &ldquo;{title}&rdquo; is ready for review.</p>
  <a href="{approve_url}"
     style="display:inline-block;background:#16a34a;color:#fff;padding:12px 28px;border-radius:6px;text-decoration:none;font-size:14px;font-weight:600;margin-right:12px;">
    ✓ Approve &amp; Publish
  </a>
  <a href="{changes_url}"
     style="display:inline-block;background:#dc2626;color:#fff;padding:12px 28px;border-radius:6px;text-decoration:none;font-size:14px;font-weight:600;">
    ✗ Request Changes
  </a>
</div>
"""
    # Inject the preview banner at the top of the email body
    preview_email = email_html.replace("<body>", "<body>" + preview_banner, 1)
    if "<body>" not in email_html:
        preview_email = preview_banner + email_html
    # #405: surface the share kit near the end of the email (after the read).
    if kit_block:
        if "</body>" in preview_email:
            preview_email = preview_email.replace("</body>", kit_block + "</body>", 1)
        else:
            preview_email = preview_email + kit_block

    subject = f'[PREVIEW] The Measured Life — Week {week_num}: "{title}"'
    try:
        ses.send_email(
            FromEmailAddress=SENDER,
            Destination={"ToAddresses": [RECIPIENT]},
            Content={
                "Simple": {
                    "Subject": {"Data": subject, "Charset": "UTF-8"},
                    "Body": {"Html": {"Data": preview_email, "Charset": "UTF-8"}},
                }
            },
        )
        logger.info(f"FEAT-12: Preview email sent for Week {week_num}")
    except Exception as e:
        logger.error(f"FEAT-12: Failed to send preview email: {e}")
        raise


# ══════════════════════════════════════════════════════════════════════════════
# HANDLER
# ══════════════════════════════════════════════════════════════════════════════


def record_email_send(table, lambda_name):
    """Write a completion record so the status page can track last send."""
    import time as _time

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    try:
        table.put_item(
            Item={
                "pk": f"USER#matthew#SOURCE#email_log#{lambda_name}",
                "sk": f"DATE#{today}",
                "sent_at": datetime.now(timezone.utc).isoformat(),
                "status": "success",
                "ttl": int(_time.time()) + 86400 * 90,
            }
        )
    except Exception as e:
        logger.info(f"[status-tracking] Non-fatal write failure: {e}")


def _elena_notebook_block(current_week):
    """#537: Elena's persistent memory (PERSONA#elena, maintained post-publish by
    elena-state-updater) rendered as prompt obligations: open threads with ages,
    the promise ledger (due/overdue callbacks — the payoff is ENFORCED here, not
    hoped for), running motifs, and her editorial stance with receipts. This is
    structured continuity on top of the raw prior-installment dump. Fail-soft ""."""
    try:
        from boto3.dynamodb.conditions import Key as _Key

        pk = "PERSONA#elena"
        parts = []

        stance = table.get_item(Key={"pk": pk, "sk": "STANCE#latest"}).get("Item") or {}
        if stance.get("headline_stance") and not stance.get("grounding_flag"):
            parts.append("YOUR EDITORIAL STANCE (it evolves only with receipts — never claim a change you can't back):")
            parts.append(f"  {stance['headline_stance']}")
            for p in (stance.get("positions") or [])[:5]:
                parts.append(f"  - position: {p}")
            if stance.get("how_my_stance_changed"):
                parts.append(f"  How my read changed after last week: {stance['how_my_stance_changed']}")

        resp = table.query(KeyConditionExpression=_Key("pk").eq(pk) & _Key("sk").begins_with("THREAD#"), ScanIndexForward=False, Limit=60)
        open_threads = [t for t in resp.get("Items", []) if t.get("status") == "open"][:8]
        if open_threads:
            parts.append("OPEN STORY THREADS (advance, resolve, or complicate — a thread stuck 3+ weeks must move or close):")
            for t in open_threads:
                opened = int(t.get("opened_week") or current_week)
                last_ref = int(t.get("last_referenced_week") or opened)
                stale = " [STALE — close it or complicate it THIS week]" if (current_week - last_ref) >= 3 else ""
                parts.append(f"  - [opened wk {opened}, age {max(0, current_week - opened)} wk]{stale} {t.get('slug')}: {t.get('summary')}")

        resp = table.query(KeyConditionExpression=_Key("pk").eq(pk) & _Key("sk").begins_with("CALLBACK#"), ScanIndexForward=False, Limit=60)
        pending = [c for c in resp.get("Items", []) if c.get("status") == "pending"]
        due = sorted(
            (c for c in pending if int(c.get("due_by_week") or 10**6) <= current_week), key=lambda c: int(c.get("due_by_week") or 0)
        )
        upcoming = sorted(
            (c for c in pending if int(c.get("due_by_week") or 10**6) > current_week), key=lambda c: int(c.get("due_by_week") or 0)
        )
        if due:
            parts.append("PROMISES DUE (you made these to readers — PAY EACH OFF this week, or explicitly extend it in-text):")
            for c in due[:5]:
                overdue = current_week - int(c.get("due_by_week") or current_week)
                tag = f"OVERDUE by {overdue} wk" if overdue > 0 else "due now"
                parts.append(f"  - [made wk {c.get('made_in_week')}, {tag}] {c.get('promise')}")
        if upcoming:
            parts.append("PROMISES OUTSTANDING (not yet due — keep them alive, don't pay them off early without reason):")
            for c in upcoming[:4]:
                parts.append(f"  - [due wk {c.get('due_by_week')}] {c.get('promise')}")

        motif_state = table.get_item(Key={"pk": pk, "sk": "MOTIF#state"}).get("Item") or {}
        motifs = [m.get("phrase") if isinstance(m, dict) else str(m) for m in (motif_state.get("motifs") or [])[:6]]
        motifs = [m for m in motifs if m]
        if motifs:
            parts.append("YOUR RUNNING MOTIFS (yours to reuse sparingly — at most one per installment): " + "; ".join(motifs))

        if not parts:
            return ""
        return "\n\n=== YOUR NOTEBOOK (persistent memory — carried across installments) ===\n" + "\n".join(parts)
    except Exception as e:
        logger.warning(f"[elena-notebook] block build failed (fail-soft): {e}")
        return ""


def _invoke_elena_state_updater(date_str):
    """#537: async-invoke the post-publish state extraction. Publish paths only —
    a draft never updates her memory. Fail-soft: a missed invoke means her
    notebook ages a week, never a failed publish."""
    try:
        lam = boto3.client("lambda", region_name="us-west-2")
        lam.invoke(
            FunctionName=os.environ.get("ELENA_STATE_UPDATER_NAME", "elena-state-updater"),
            InvocationType="Event",
            Payload=json.dumps({"date": date_str}).encode(),
        )
        logger.info(f"[elena-state] invoked for {date_str}")
    except Exception as e:
        logger.warning(f"[elena-state] invoke failed (non-fatal): {e}")


# ══════════════════════════════════════════════════════════════════════════════
# #548: MARGARET CALLOWAY'S RED PEN — critique + conditional revision, pre-publish
# ══════════════════════════════════════════════════════════════════════════════

# Elena's memory partition (#537) — her callback ledger is Margaret's critique
# input. Margaret's own small partition (published editor's-note history, for
# the <=1/month gate) follows the same PERSONA#<slug> convention.
_ELENA_PERSONA_PK = "PERSONA#elena"
_MARGARET_PERSONA_PK = "PERSONA#margaret"


def _due_callback_promises(week_num, limit=5):
    """#548: promises due THIS WEEK from Elena's ledger (#537, PERSONA#elena
    CALLBACK# items) — Margaret's critique input ('you owe the reader the
    follow-up you promised'). Fail-soft []: a lookup failure just means her
    critique runs without the ledger cross-reference."""
    try:
        from boto3.dynamodb.conditions import Key as _Key

        resp = table.query(
            KeyConditionExpression=_Key("pk").eq(_ELENA_PERSONA_PK) & _Key("sk").begins_with("CALLBACK#"),
            ScanIndexForward=False,
            Limit=60,
        )
        pending = [c for c in resp.get("Items", []) if c.get("status") == "pending"]
        due = [c for c in pending if int(c.get("due_by_week") or 10**6) <= week_num]
        return [c["promise"] for c in due[:limit] if c.get("promise")]
    except Exception as e:
        logger.warning(f"[margaret] due-callback query failed (fail-soft): {e}")
        return []


def _margaret_last_note_date():
    """The date of Margaret's last published editor's note (PERSONA#margaret
    NOTE#latest), or None. Drives the <=1/month deterministic gate."""
    try:
        item = table.get_item(Key={"pk": _MARGARET_PERSONA_PK, "sk": "NOTE#latest"}).get("Item")
        return (item or {}).get("date")
    except Exception as e:
        logger.warning(f"[margaret] last-note lookup failed (fail-soft): {e}")
        return None


def _record_margaret_note(date_str, week_num, note):
    """Persist a published editor's note so the next run's <=1/month gate sees it."""
    try:
        item = {
            "pk": _MARGARET_PERSONA_PK,
            "sk": f"NOTE#{date_str}",
            "date": date_str,
            "week_number": week_num,
            "note": note,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }
        table.put_item(Item=item)
        table.put_item(Item={**item, "sk": "NOTE#latest"})
    except Exception as e:
        logger.warning(f"[margaret] failed to record editor's note (non-fatal): {e}")


def _margaret_haiku_call(system, user):
    """One Haiku call (Bedrock via retry_utils) — used for both Margaret's
    critique and Elena's Haiku-tier revision. Kept to Haiku per the #548
    +2-calls/week budget (Elena's own Sonnet voice is reserved for the
    weekly draft itself)."""
    import retry_utils

    return retry_utils.call_anthropic_api(
        prompt=user,
        max_tokens=1500,
        system=system,
        temperature=0.3,
        timeout=60,
        model=AI_MODEL_HAIKU,
    )


def _run_margaret_edit_pass(raw_installment, week_num, date_str, elena_prompt, allowed_numbers):
    """#548: Margaret Calloway's red pen. A critique + conditional revision pass
    over Elena's already-drafted, already-grounded (ADR-104) installment —
    post-draft, pre-publish. Tier-1 paused (matches coach_narrative — narrative
    embellishments pause before the flagship chronicle itself, which survives
    to tier 2). At most 2 Haiku calls total; fail-soft everywhere — any failure
    (budget pause, bad JSON, a rejected revision) simply returns Elena's draft
    untouched."""
    try:
        from budget_guard import allow as _budget_allow

        if not _budget_allow("chronicle_editor"):
            logger.info("[margaret] budget tier pauses the editor pass — keeping Elena's draft as-is")
            return raw_installment
    except ImportError:
        pass

    try:
        import margaret_editor_pass as _mep

        config = board_loader.load_board(s3, S3_BUCKET) if _HAS_BOARD_LOADER else None
        narrator = _mep.build_narrator(config)
        due_callbacks = _due_callback_promises(week_num)
        note_eligible = _mep.editors_note_eligible(_margaret_last_note_date(), date_str)

        result = _mep.run_pass(
            raw_installment,
            week_num,
            due_callbacks,
            allowed_numbers,
            note_eligible,
            narrator,
            critique_fn=_margaret_haiku_call,
            # Elena revises in her own voice — elena_prompt IS the system prompt;
            # the revise callable ignores the (unused) system arg run_pass passes it.
            revise_fn=lambda _system, user: _margaret_haiku_call(elena_prompt, user),
        )
        if result["revised"]:
            logger.info(f"[margaret] Week {week_num} revised ({result['revision_reason']})")
        elif result["critique"] is not None:
            logger.info(f"[margaret] Week {week_num} critique kept as-is ({result['revision_reason']})")
        if result["editors_note"]:
            _record_margaret_note(date_str, week_num, result["editors_note"])
            logger.info(f"[margaret] editor's note published for Week {week_num}")
        return result["final_text"]
    except ImportError as e:
        logger.warning(f"[margaret] edit-pass module unavailable (fail-soft): {e}")
        return raw_installment
    except Exception as e:
        logger.warning(f"[margaret] edit pass failed (fail-soft, keeping Elena's draft): {e}")
        return raw_installment


def lambda_handler(event: dict, context) -> dict:
    logger.info("Wednesday Chronicle v1.1.0 (Board Centralization) — The Measured Life — starting...")

    # Phase 3 bootstrap/regenerate: {"recap_only": true} builds + commits the
    # "previously on" recap from EXISTING published installments WITHOUT writing a new
    # chronicle week. Lets the first recap go live now (and supports regeneration)
    # without forcing an out-of-cadence installment.
    event = event or {}
    if event.get("recap_only"):
        data = gather_chronicle_data()
        if not data:
            return {"statusCode": 500, "body": "Failed to gather data"}
        recap = build_recap(data, new_installment_md=None, new_meta=None)
        if not recap or not recap.get("as_of"):
            return {"statusCode": 200, "body": json.dumps({"status": "recap_skipped", "reason": "no published history or build failed"})}
        _write_recap(recap, recap["as_of"])
        return {
            "statusCode": 200,
            "body": json.dumps({"status": "recap_written", "as_of": recap["as_of"], "beats": len(recap.get("recent_beats", []))}),
        }

    # Budget guardrail: at Tier ≥ 1 skip this week's chronicle entirely (weekly,
    # non-essential, subscriber-facing) — no Bedrock spend, clean no-op.
    try:
        from budget_guard import current_tier

        # Chronicle is weekly flagship content (~$1/wk of Bedrock) and the Friday Panel
        # podcast's ONLY input — so it must survive tier 1 and only pause at tier >= 2,
        # in lockstep with the Panel lambda's SKIP_TIER=2. We read the tier directly
        # (it equals budget_guard's "chronicle" cutoff, now 2) so this fix ships as a
        # one-function deploy with no layer rebuild. WAS: allow("chronicle"), whose
        # cutoff of 1 paused this at the mildest budget state and silently starved the
        # podcast for weeks (2026-06-19). Revert to allow("chronicle") at the next layer bump.
        if current_tier() >= 2:
            logger.info("Budget tier >= 2 — Wednesday chronicle paused this week (no Bedrock spend)")
            _set_chronicle_pending(
                None,
                "budget_tier",
                "This week's chronicle is paused — the platform's AI budget guard is protecting monthly spend. "
                "It resumes automatically once usage drops below the threshold.",
            )
            return {"statusCode": 200, "body": "skipped: budget tier"}
    except ImportError:
        pass

    data = gather_chronicle_data()
    if not data:
        return {"statusCode": 500, "body": "Failed to gather data"}

    # Build narrative-ready data packet
    data_packet, week_num = build_data_packet(data)
    logger.info(f"Data packet: {len(data_packet)} chars, Week {week_num}")

    # Build user message with previous installments for continuity
    user_parts = [data_packet]

    # #914: the ONE shared presence block — when Matthew's own logging has gone
    # quiet, Elena must not write a normal week over an incomplete window. Same
    # engagement_core.presence_prompt_block every narrative surface injects; the
    # acknowledgment gate below enforces it at severity loud/alarm.
    _presence_sig = {}
    _presence_block_txt = ""
    try:
        from engagement_core import presence_prompt_block as _ppb

        _presence_sig = _load_engagement_signal()
        _presence_block_txt = _ppb(_presence_sig)
    except Exception as _pres_e:
        logger.warning(f"[#914] presence block skipped (non-fatal): {_pres_e}")
    if _presence_block_txt:
        user_parts.append("\n\n=== PRESENCE / QUIET STRETCH ===")
        user_parts.append(_presence_block_txt)

    # Editorial guidance — steer toward synthesis, not recounting
    user_parts.append("\n\n=== EDITORIAL GUIDANCE ===")
    user_parts.append("Remember: you are writing a STORY, not a weekly recap.")
    user_parts.append("DO NOT walk through the week day by day (Monday this, Tuesday that...).")
    user_parts.append("Instead: find the 2-3 THEMES that make this week interesting.")
    user_parts.append("Ask yourself: What's the headline? What would make a reader who found this series click 'next week'?")
    user_parts.append("Use the data as EVIDENCE for your narrative thesis, not as the structure of your piece.")
    user_parts.append("Compare to previous weeks where possible — is something changing? Getting harder? Breaking through?")
    user_parts.append("The best installments read like a chapter in a book, not a report card.")

    prev = data["prev_installments"]
    if prev:
        user_parts.append("\n\n=== YOUR PREVIOUS INSTALLMENTS (for continuity) ===")

        # B3: Thesis guardrails — extract recent titles/theses to prevent repetition
        recent_titles = [inst.get("title", "Untitled") for inst in prev]
        if recent_titles:
            user_parts.append("\n=== THESIS GUARDRAILS ===")
            user_parts.append("RECENT THESES (last 4 weeks — do NOT repeat these angles):")
            for t in recent_titles:
                user_parts.append(f'  - "{t}"')
            user_parts.append(
                "This week's thesis MUST be orthogonal to the above. Don't write about the same theme two weeks in a row, even if the data supports it. Find the new angle."
            )

        for inst in reversed(prev):  # oldest first
            wn = inst.get("week_number", "?")
            t = inst.get("title", "Untitled")
            md = inst.get("content_markdown", "")
            if md:
                # Truncate long previous installments to manage token budget
                if len(md) > 2000:
                    md = md[:2000] + "\n[...truncated...]"
                user_parts.append(f'\n--- Week {wn}: "{t}" ---\n{md}')

        # B3: Thread tracking — ask Elena to advance/resolve/complicate prior threads
        user_parts.append("\n=== CONTINUITY INSTRUCTIONS ===")
        user_parts.append(
            "Read the previous installments above. Identify 2-3 story threads that are still active (unresolved tensions, patterns mentioned, questions raised). Your job: advance, resolve, or complicate these threads. Don't ignore them, but don't force them either. If a thread has been mentioned for 3+ weeks without development, either close it or introduce new tension."
        )
    else:
        user_parts.append(
            "\n\nThis is the FIRST installment. Establish the story from the beginning. Who is Matthew? Why is he doing this? What are the stakes? Set the scene in Seattle. Introduce the platform, the data, the obsession. Make the reader want to come back next week."
        )

    # #537: Elena's persistent notebook — open threads, the promise ledger
    # (due callbacks are OBLIGATIONS), motifs, and her receipts-backed stance.
    notebook_block = _elena_notebook_block(week_num)
    if notebook_block:
        user_parts.append(notebook_block)

    user_message = "\n".join(user_parts)
    logger.info(f"Full prompt: {len(user_message)} chars")

    # Try config-driven prompt first, fall back to hardcoded
    elena_prompt = _build_elena_prompt_from_config()
    if elena_prompt:
        logger.info("Using config-driven Elena prompt")
    else:
        logger.info("Using fallback hardcoded Elena prompt")
        elena_prompt = _FALLBACK_ELENA_PROMPT

    # IC-16: Progressive context — narrative-relevant insight threads
    if _HAS_INSIGHT_WRITER:
        try:
            prev_ctx = insight_writer.build_insights_context(days=30, max_items=5, label="PLATFORM INSIGHTS (context for narrative)")
            if prev_ctx:
                # B3: Reframe Field Notes as a hypothesis Elena can agree/disagree with
                field_notes_framing = (
                    "\n=== FIELD NOTES (AI LAB NOTEBOOK) ===\n"
                    "The platform's AI lab notebook produced the following read on this week's data. "
                    "Treat this as a HYPOTHESIS, not gospel. Do you agree with the system's read? "
                    "Deepen it, contradict it, or find the nuance the structured analysis misses. "
                    "The best Chronicle installments emerge from the gap between what the algorithm sees "
                    "and what the journalist notices.\n\n"
                )
                user_message = field_notes_framing + prev_ctx + "\n\n" + user_message
        except Exception as e:
            logger.warning(f"IC-16 failed: {e}")

    # Call Sonnet
    logger.info("Calling Sonnet 4.5 for Elena's installment...")
    try:
        raw_installment = call_anthropic(elena_prompt, user_message)
    except Exception as e:
        logger.error(f"Anthropic failed: {e}")
        return {"statusCode": 500, "body": f"AI generation failed: {e}"}

    logger.info(f"Installment received: {len(raw_installment)} chars, ~{len(raw_installment.split())} words")

    # #537 / ADR-104: the chronicle joins the grounded-generation gate. Every
    # number in the installment must exist somewhere in what Elena was given
    # (the data packet, prior installments, her notebook). Keep-best mode: one
    # corrective rewrite, kept only if strictly better — the weekly story is
    # human-reviewed (PREVIEW_MODE) + privacy-gated downstream, so a residual
    # finding degrades to the best draft instead of going dark.
    _allowed = None
    try:
        import grounded_generation as _gg

        _allowed = _gg.allowed_numbers(elena_prompt, user_message)
        _draft_before_gate = raw_installment  # #812/#744: keep the pre-gate draft for retention
        _findings_fn = lambda t: installment_grounding_findings(elena_prompt, user_message, t)  # noqa: E731
        _regen_fn = lambda corr: call_anthropic(elena_prompt, user_message + "\n\n" + corr)  # noqa: E731
        raw_installment, _residual, _corrected = _gg.regen_once(raw_installment, _findings_fn, _regen_fn)
        if _corrected:
            logger.info(f"[ADR-104] chronicle corrected once; residual findings: {len(_residual)}")
        elif _residual:
            logger.warning(f"[ADR-104] chronicle keeps {len(_residual)} residual grounding findings (best draft)")
        if _corrected or _residual:
            # #812/#744: a fired chronicle gate is labeled eval data — retain the pair.
            try:
                import eval_retention

                eval_retention.retain(
                    "chronicle",
                    "flagged_corrected" if _corrected else "flagged_kept_best",
                    draft=_draft_before_gate,
                    final=raw_installment,
                    findings=_findings_fn(_draft_before_gate),  # the DRAFT's findings — they define a canary's expected checks
                    allowed=_allowed,
                    extra={"week_number": week_num},
                )
            except Exception:  # noqa: BLE001 — retention is never load-bearing
                pass
    except ImportError:
        pass  # gate module unavailable — serve as before
    except Exception as _gg_e:
        logger.warning(f"[ADR-104] chronicle grounding gate error (fail-open): {_gg_e}")

    # #548: Margaret Calloway's red pen — one critique + conditional revision
    # pass over Elena's grounded draft, before AI-3 validation / parsing / the
    # privacy gate (all of which still run on whatever text comes back here).
    raw_installment = _run_margaret_edit_pass(raw_installment, week_num, data["dates"]["end"], elena_prompt, _allowed)

    # #914: presence-acknowledgment gate (ADR-108 regenerate-or-hold). Runs AFTER
    # Margaret's edit so her rewrite can't strip the acknowledgment unnoticed. At
    # severity loud/alarm an installment that narrates a normal week over a real
    # logging stall is regenerated once, then HELD — no chronicle beats a dishonest
    # one. Deterministic anchor check, no LLM judge.
    try:
        from engagement_core import enforce_presence_acknowledgment as _epa, presence_ack_required as _par

        if _presence_sig and _par(_presence_sig) and raw_installment:
            raw_installment, _ack_finding = _epa(
                raw_installment,
                _presence_sig,
                regenerate_fn=lambda note: call_anthropic(elena_prompt, user_message + "\n\n" + note),
            )
            if _ack_finding:
                logger.warning(f"[#914] chronicle presence-ack gate fired: {_ack_finding.get('detail')}")
            if raw_installment is None:
                logger.error("[#914] chronicle HELD by presence-ack gate — not publishing this week")
                return {"statusCode": 500, "body": "[#914] Chronicle held: presence gap unacknowledged at severity loud/alarm"}
    except ImportError:
        pass  # engagement_core unavailable — serve as before
    except Exception as _ack_e:
        logger.warning(f"[#914] presence-ack gate error (fail-open): {_ack_e}")

    # AI-3: Validate output before rendering
    if _HAS_AI_VALIDATOR and raw_installment:
        _val = validate_ai_output(raw_installment, AIOutputType.CHRONICLE, min_length=200)
        if _val.blocked:
            logger.error(f"[AI-3] Chronicle BLOCKED: {_val.block_reason}")
            return {"statusCode": 500, "body": f"[AI-3] Chronicle blocked: {_val.block_reason}"}
        elif _val.warnings:
            logger.warning(f"[AI-3] Chronicle warnings: {_val.warnings}")

    # Parse the installment
    title, stats_line, body_md = parse_installment(raw_installment)

    # BS-05: Compute confidence badge based on total journey data depth.
    # Henning: LOW (<14d data), MEDIUM (14-49d), HIGH (≥50d + sig + effect).
    # Chronicle draws on full journey history — use days-since-start as n.
    _conf_level = "MEDIUM"
    _conf_badge_html = ""
    _conf_reason = ""
    if _HAS_CONFIDENCE:
        try:
            _journey_start = data.get("profile", {}).get("journey_start_date", EXPERIMENT_START_DATE)
            _journey_days = (datetime.strptime(data["dates"]["end"], "%Y-%m-%d") - datetime.strptime(_journey_start, "%Y-%m-%d")).days
            _conf = compute_confidence(days_of_data=_journey_days)
            _conf_level = _conf.get("level", "MEDIUM")
            _conf_badge_html = _conf.get("badge_html", "")
            _conf_reason = _conf.get("reason", "")
            logger.info(f"BS-05 confidence: {_conf_level} ({_conf_reason})")
        except Exception as _ce:
            logger.warning(f"BS-05 confidence compute failed (non-fatal): {_ce}")

    logger.info(f'Title: "{title}"')

    # Convert to HTML
    body_html = markdown_to_html(body_md)

    # Detect Board interview — a blockquote counts UNLESS it's Margaret's editor's
    # note (#548), which is also rendered as a blockquote but isn't an interview.
    has_board = any(line.strip().startswith("> ") and "editor's note" not in line.strip().lower() for line in body_md.split("\n"))

    # Collect all installments for index pages (including the new one)
    date_str = data["dates"]["end"]
    all_installments = []
    try:
        # ADR-058: phase=pilot hidden by default.
        from phase_filter import with_phase_filter

        resp = table.query(
            **with_phase_filter(
                {
                    "KeyConditionExpression": "pk = :pk AND begins_with(sk, :prefix)",
                    "ExpressionAttributeValues": {
                        ":pk": f"USER#{USER_ID}#SOURCE#chronicle",
                        ":prefix": "DATE#",
                    },
                    "ScanIndexForward": False,
                }
            )
        )
        all_installments = [d2f(i) for i in resp.get("Items", [])]
    except Exception as e:
        logger.warning(f"Failed to query all installments: {e}")
        all_installments = [{"title": title, "week_number": week_num, "date": date_str}]

    # Ensure new installment is in the list (not yet stored at this point)
    if not any(i.get("date") == date_str for i in all_installments):
        all_installments.insert(
            0,
            {
                "title": title,
                "week_number": week_num,
                "date": date_str,
                "stats_line": stats_line,
                "word_count": len(raw_installment.split()),
                "content_markdown": raw_installment[:300],
                "has_board_interview": has_board,
            },
        )

    # The email footer points readers at the live chronicle archive (the /blog/ path
    # was retired — it 404'd, #969). The per-post journal URL is returned by
    # publish_to_journal below; the "full series" link is the archive listing.
    series_url = "https://averagejoematt.com/story/chronicle/"

    # ── Privacy gate (fail-closed) — never publish OR store a leaking installment.
    # Prompt rules are the first line; this deterministic gate is the guarantee.
    # Catches the truth-audit class: a real public figure named as a coach/source,
    # or a vice/substance named outright. A violation HOLDS the whole installment.
    try:
        privacy_guard.assert_clean(f"{title}\n{stats_line}\n{raw_installment}", context=f"chronicle week {week_num}")
    except privacy_guard.PrivacyViolation as e:
        logger.error(f"[privacy] BLOCKED chronicle week {week_num} — {e}")
        # #803: this used to be a silent no-op — nothing was ever written anywhere, so
        # the reader-facing "come back weekly" promise broke with zero trace beyond a
        # CloudWatch log line. Record a non-content marker so the site can say Week
        # {week_num} was attempted and withheld, instead of the numbering just skipping
        # ahead unexplained next time a clean draft ships.
        _set_chronicle_pending(
            week_num,
            "privacy_hold",
            f"Week {week_num}'s installment was generated but withheld before publishing — it didn't clear "
            "the platform's automatic safety check that keeps real people's names and private details out "
            "of the public write-up. No content was published or stored for this week.",
        )
        return {
            "statusCode": 200,
            "body": json.dumps({"status": "privacy_hold", "week": week_num, "violations": [t for _, t in e.violations]}),
        }

    # ── #405: the per-chronicle share kit — machine-made from ALREADY-PUBLISHED fields
    # only (title, honest stats line, an excerpt of the prose, the canonical post URL).
    # Text/JSON only (the honest-stats OG card is drawn by the daily og sweep via the
    # #595 engine). The kit passes the same privacy gate the installment just cleared.
    share_kit = None
    share_kit_json = None
    share_kit_block = ""
    if _HAS_SHARE_KIT:
        try:
            _seq, _label, _canon = journal_post_ref(date_str, all_installments, week_num)
            share_kit = chronicle_share_kit.build_kit(
                title=title,
                stats_line=stats_line,
                label=_label,
                date_str=date_str,
                canonical_url=_canon,
                excerpt_source=body_md,
                week_number=week_num,
            )
            # Defense-in-depth: the kit only recombines already-gated fields, but re-assert.
            privacy_guard.assert_clean(share_kit.get("caption", ""), context=f"share kit week {week_num}")
            share_kit_json = json.dumps(share_kit)
            share_kit_block = chronicle_share_kit.kit_email_block(share_kit)
        except privacy_guard.PrivacyViolation as e:
            logger.error(f"[privacy] share kit blocked week {week_num} — {e}")
            share_kit = share_kit_json = None
            share_kit_block = ""
        except Exception as e:
            logger.warning(f"[#405] share kit build failed (non-fatal): {e}")
            share_kit = share_kit_json = None
            share_kit_block = ""

    # ── Phase 3: build Elena's "previously on" recap (grounded in published history
    # + this week being published). Fail-soft: a recap failure never blocks the
    # chronicle. Committed to RECAP#latest at publish time (now if non-preview, at
    # approve if preview) so it never runs ahead of the history it summarizes.
    recap = build_recap(
        data,
        new_installment_md=raw_installment,
        new_meta={"date": date_str, "week_number": week_num, "title": title},
    )
    draft_recap_json = json.dumps(recap, default=str) if recap else None

    if PREVIEW_MODE:
        # ── FEAT-12: Build all HTML artifacts without publishing ─────────────
        logger.info("FEAT-12: PREVIEW_MODE — building draft artifacts")

        try:
            journal_post_key, journal_post_html, journal_posts_json = publish_to_journal(
                title,
                stats_line,
                body_html,
                week_num,
                date_str,
                all_installments,
                write_to_s3=False,
            )
        except Exception as e:
            logger.warning(f"FEAT-12: Failed to build journal artifacts: {e}")
            journal_post_key = journal_post_html = journal_posts_json = None

        draft_email_html = build_email_html(title, stats_line, body_html, week_num, date_str, series_url)

        approval_token = _secrets.token_hex(32)
        store_installment(
            date_str,
            week_num,
            title,
            stats_line,
            raw_installment,
            body_html,
            [],
            has_board,
            confidence_level=_conf_level,
            confidence_badge_html=_conf_badge_html,
            status="draft",
            approval_token=approval_token,
            draft_journal_post_html=journal_post_html,
            draft_journal_post_key=journal_post_key,
            draft_journal_posts_json=journal_posts_json,
            draft_email_html=draft_email_html,
            draft_recap_json=draft_recap_json,
            draft_share_kit_json=share_kit_json,
        )

        _send_preview_email(title, week_num, date_str, approval_token, draft_email_html, kit_block=share_kit_block)
        logger.info(f"FEAT-12: Draft Week {week_num} stored — awaiting approval")

    else:
        # ── Standard flow: publish immediately ───────────────────────────────
        store_installment(
            date_str,
            week_num,
            title,
            stats_line,
            raw_installment,
            body_html,
            [],
            has_board,
            confidence_level=_conf_level,
            confidence_badge_html=_conf_badge_html,
        )

        # This path publishes immediately → commit the recap now (fail-soft).
        if recap:
            _write_recap(recap, date_str)

        # #537: published now → update Elena's memory now (fail-soft).
        _invoke_elena_state_updater(date_str)

        try:
            journal_url = publish_to_journal(title, stats_line, body_html, week_num, date_str, all_installments)
            logger.info(f"[journal] Published: {journal_url}")
        except Exception as e:
            logger.warning(f"[journal] publish_to_journal failed (non-fatal): {e}")

        # #405: write the share kit to its stable generated location (immediate-publish path).
        if share_kit and share_kit_json:
            try:
                s3.put_object(
                    Bucket=S3_BUCKET,
                    Key=chronicle_share_kit.kit_s3_key(share_kit["canonical_url"]),
                    Body=share_kit_json.encode("utf-8"),
                    ContentType="application/json",
                    CacheControl="max-age=300",
                )
                logger.info("[#405] share kit written to %s", chronicle_share_kit.kit_s3_key(share_kit["canonical_url"]))
            except Exception as e:
                logger.warning(f"[#405] share kit S3 write failed (non-fatal): {e}")

        email_html = build_email_html(title, stats_line, body_html, week_num, date_str, series_url)
        if share_kit_block:
            email_html = email_html.replace("</body>", share_kit_block + "</body>", 1)
        subject = f'The Measured Life — Week {week_num}: "{title}"'
        ses.send_email(
            FromEmailAddress=SENDER,
            Destination={"ToAddresses": [RECIPIENT]},
            Content={
                "Simple": {
                    "Subject": {"Data": subject, "Charset": "UTF-8"},
                    "Body": {"Html": {"Data": email_html, "Charset": "UTF-8"}},
                }
            },
        )
        logger.info(f"Email sent: {subject}")

    # IC-15: Persist chronicle as narrative insight
    if _HAS_INSIGHT_WRITER:
        try:
            insight_writer.write_insight(
                digest_type="chronicle",
                insight_type="observation",
                text=f"Week {week_num}: {title}. {raw_installment[:600]}",
                pillars=insight_writer._extract_pillars_from_text(raw_installment[:500]),
                tags=["chronicle", "narrative", f"week_{week_num}"],
                confidence="high",
                actionable=False,
                date=data["dates"]["end"],
            )
            logger.info("IC-15: chronicle insight persisted")
        except Exception as e:
            logger.warning(f"IC-15 failed: {e}")

    record_email_send(table, "wednesday_chronicle")
    if PREVIEW_MODE:
        return {
            "statusCode": 200,
            "body": f"Chronicle Week {week_num} draft stored — preview email sent to {RECIPIENT}",
        }
    return {
        "statusCode": 200,
        "body": f'Chronicle Week {week_num} published: "{title}" ({len(raw_installment.split())} words)',
    }
