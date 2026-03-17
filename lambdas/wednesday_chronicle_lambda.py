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
  2. Published to S3 blog (averagejoematt.com/blog/)
  3. Stored in DynamoDB for continuity (last 4 installments fed to AI)

AI Model: Sonnet 4.5 (temperature 0.6 for creative voice)
Cost: ~$0.04/week (~$0.16/month)

v1.1.0: Elena's persona + Board interview descriptions dynamically built from
        s3://matthew-life-platform/config/board_of_directors.json
        Falls back to hardcoded _FALLBACK_ELENA_PROMPT if S3 config unavailable.
"""

import json
import os
import logging
import time
import re
import boto3
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from collections import defaultdict

# OBS-1: Structured logger (wired below after optional imports)
_logger_std = logging.getLogger()
_logger_std.setLevel(logging.INFO)

REGION     = os.environ.get("AWS_REGION", "us-west-2")
TABLE_NAME = os.environ.get("TABLE_NAME", "life-platform")
S3_BUCKET  = os.environ["S3_BUCKET"]
USER_ID    = os.environ["USER_ID"]
RECIPIENT  = os.environ["EMAIL_RECIPIENT"]
SENDER     = os.environ["EMAIL_SENDER"]

USER_PREFIX = f"USER#{USER_ID}#SOURCE#"

dynamodb = boto3.resource("dynamodb", region_name=REGION)
table    = dynamodb.Table(TABLE_NAME)
ses      = boto3.client("sesv2", region_name=REGION)
s3       = boto3.client("s3", region_name=REGION)
secrets  = boto3.client("secretsmanager", region_name=REGION)

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
    from ai_output_validator import validate_ai_output, AIOutputType
    _HAS_AI_VALIDATOR = True
except ImportError:
    _HAS_AI_VALIDATOR = False

# BS-05: Confidence badge
try:
    from digest_utils import compute_confidence, _confidence_badge
    _HAS_CONFIDENCE = True
except ImportError:
    _HAS_CONFIDENCE = False
    def _confidence_badge(level):
        return ""

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

def get_anthropic_key():
    secret_name = os.environ.get("ANTHROPIC_SECRET", "life-platform/ai-keys")
    secret = secrets.get_secret_value(SecretId=secret_name)
    return json.loads(secret["SecretString"])["anthropic_api_key"]

def d2f(obj):
    if isinstance(obj, list):    return [d2f(i) for i in obj]
    if isinstance(obj, dict):    return {k: d2f(v) for k, v in obj.items()}
    if isinstance(obj, Decimal): return float(obj)
    return obj

def safe_float(rec, field, default=None):
    if rec and field in rec:
        try: return float(rec[field])
        except Exception: return default
    return default

def query_range(source, start_date, end_date):
    pk = f"USER#{USER_ID}#SOURCE#{source}"
    records = {}
    kwargs = {
        "KeyConditionExpression": "pk = :pk AND sk BETWEEN :s AND :e",
        "ExpressionAttributeValues": {
            ":pk": pk, ":s": f"DATE#{start_date}", ":e": f"DATE#{end_date}",
        },
    }
    while True:
        resp = table.query(**kwargs)
        for item in resp.get("Items", []):
            date_str = item.get("date") or item["sk"].replace("DATE#", "")
            records[date_str] = d2f(item)
        if "LastEvaluatedKey" not in resp:
            break
        kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
    return records

def query_range_list(source, start_date, end_date):
    """Like query_range but returns a list, preserving duplicates (for journal)."""
    pk = f"USER#{USER_ID}#SOURCE#{source}"
    items = []
    kwargs = {
        "KeyConditionExpression": "pk = :pk AND sk BETWEEN :s AND :e",
        "ExpressionAttributeValues": {
            ":pk": pk, ":s": f"DATE#{start_date}", ":e": f"DATE#{end_date}~",
        },
    }
    while True:
        resp = table.query(**kwargs)
        items.extend(d2f(resp.get("Items", [])))
        if "LastEvaluatedKey" not in resp:
            break
        kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
    return items

def fetch_profile():
    try:
        r = table.get_item(Key={"pk": f"USER#{USER_ID}", "sk": "PROFILE#v1"})
        return d2f(r.get("Item", {}))
    except Exception as e:
        logger.error(f"fetch_profile: {e}")
        return {}


# ══════════════════════════════════════════════════════════════════════════════
# DATA GATHERING
# ══════════════════════════════════════════════════════════════════════════════

def gather_chronicle_data():
    """Gather all data Elena needs for this week's installment."""
    today = datetime.now(timezone.utc).date()
    end = (today - timedelta(days=1)).isoformat()      # yesterday
    start = (today - timedelta(days=7)).isoformat()     # 7 days back
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
    journal_entries = [e for e in journal_entries
                       if "#journal#" in e.get("sk", "")]
    logger.info(f"Journal entries: {len(journal_entries)}")

    # --- Day grades + habit scores ---
    day_grades = query_range("day_grade", start, end)
    habit_scores = query_range("habit_scores", start, end)

    # --- Habits raw (for specific habit names) ---
    habitify = query_range("habitify", start, end)

    # --- State of Mind ---
    state_of_mind = query_range("state_of_mind", start, end)

    # --- Supplements ---
    supplements = query_range("supplements", start, end)

    # --- Active experiments ---
    experiments = []
    try:
        resp = table.query(
            KeyConditionExpression="pk = :pk AND begins_with(sk, :prefix)",
            ExpressionAttributeValues={
                ":pk": f"USER#{USER_ID}#SOURCE#experiments",
                ":prefix": "EXP#",
            },
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
        resp = table.query(
            KeyConditionExpression="pk = :pk AND begins_with(sk, :prefix)",
            ExpressionAttributeValues={
                ":pk": f"USER#{USER_ID}#SOURCE#chronicle",
                ":prefix": "DATE#",
            },
            ScanIndexForward=False, Limit=4,
        )
        prev_installments = [d2f(i) for i in resp.get("Items", [])]
        logger.info(f"Previous installments: {len(prev_installments)}")
    except Exception as e:
        logger.warning(f"Previous installments: {e}")

    return {
        "whoop": whoop, "eightsleep": eightsleep, "garmin": garmin,
        "strava": strava, "withings": withings, "macrofactor": macrofactor,
        "apple_health": apple_health, "journal_entries": journal_entries,
        "day_grades": day_grades, "habit_scores": habit_scores,
        "habitify": habitify, "state_of_mind": state_of_mind,
        "supplements": supplements, "experiments": experiments,
        "anomalies": anomalies, "weather": weather,
        "character_sheet": character_sheet,
        "prev_installments": prev_installments, "profile": profile,
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

    # --- Compute week number from journey start ---
    journey_start = profile.get("journey_start_date", "2026-02-22")
    try:
        js = datetime.strptime(journey_start, "%Y-%m-%d").date()
        end_date = datetime.strptime(dates["end"], "%Y-%m-%d").date()
        week_num = max(1, ((end_date - js).days // 7) + 1)
    except Exception:
        week_num = 1
    packet.append(f"Week number: {week_num}")
    packet.append(f"Journey start: {journey_start}")
    packet.append(f"Journey start weight: {profile.get('journey_start_weight_lbs', 302)} lbs")
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
        journey_start_w = profile.get("journey_start_weight_lbs", 302)
        total_lost = journey_start_w - latest[1]
        packet.append(f"Total journey loss: {total_lost:.1f} lbs")
    packet.append("")

    # --- Recovery & physiology ---
    packet.append("=== RECOVERY & PHYSIOLOGY ===")
    for d in sorted(data["whoop"].keys()):
        rec = data["whoop"][d]
        hrv = safe_float(rec, "hrv")
        recovery = safe_float(rec, "recovery_score")
        rhr = safe_float(rec, "resting_heart_rate")
        strain = safe_float(rec, "strain")
        parts = [f"{d}:"]
        if recovery is not None: parts.append(f"Recovery {recovery:.0f}%")
        if hrv is not None: parts.append(f"HRV {hrv:.0f}ms")
        if rhr is not None: parts.append(f"RHR {rhr:.0f}")
        if strain is not None: parts.append(f"Strain {strain:.1f}")
        packet.append(" | ".join(parts))
    packet.append("")

    # --- Sleep (Whoop — SOT for duration, stages, score — captures all sleep) ---
    packet.append("=== SLEEP (Whoop — source of truth) ===")
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
        if score is not None: parts.append(f"Score {score:.0f}")
        if dur is not None: parts.append(f"{dur:.1f}h")
        if eff is not None: parts.append(f"Eff {eff:.0f}%")
        if deep_pct is not None: parts.append(f"Deep {deep_pct:.0f}%")
        if rem_pct is not None: parts.append(f"REM {rem_pct:.0f}%")
        packet.append(" | ".join(parts))
    packet.append("")

    # --- Sleep Environment (Eight Sleep — bed temp, room temp, presence) ---
    packet.append("=== SLEEP ENVIRONMENT (Eight Sleep) ===")
    for d in sorted(data["eightsleep"].keys()):
        rec = data["eightsleep"][d]
        bed_temp = safe_float(rec, "bed_temp_f")
        room_temp = safe_float(rec, "room_temp_f")
        toss = safe_float(rec, "toss_and_turns") or safe_float(rec, "toss_turn_count")
        parts = [f"{d}:"]
        if bed_temp is not None: parts.append(f"Bed {bed_temp:.0f}°F")
        if room_temp is not None: parts.append(f"Room {room_temp:.0f}°F")
        if toss is not None: parts.append(f"Tosses {toss:.0f}")
        if len(parts) > 1:
            packet.append(" | ".join(parts))
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
            if dist_mi > 0: line += f", {dist_mi}mi"
            if avg_hr: line += f", HR {avg_hr:.0f}"
            if elev and elev > 100: line += f", {elev:.0f}ft gain"
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
        avoidance = entry.get("enriched_avoidance_flag")
        social = entry.get("enriched_social_quality")
        ownership = entry.get("enriched_ownership_level")

        packet.append(f"--- {date} ({template}) ---")
        if raw:
            # Include full text — Elena needs the emotional texture
            packet.append(f"Text: {raw[:1500]}")
        signals = []
        if mood is not None: signals.append(f"Mood:{mood}/5")
        if energy is not None: signals.append(f"Energy:{energy}/5")
        if stress is not None: signals.append(f"Stress:{stress}/5")
        if themes: signals.append(f"Themes: {', '.join(themes[:4])}")
        if emotions: signals.append(f"Emotions: {', '.join(emotions[:5])}")
        if cognitive: signals.append(f"Cognitive: {', '.join(cognitive[:3])}")
        if avoidance: signals.append(f"AVOIDANCE FLAG: {avoidance}")
        if social: signals.append(f"Social: {social}")
        if ownership: signals.append(f"Ownership: {ownership}")
        if signals:
            packet.append("Signals: " + " | ".join(signals))
        packet.append("")
    if not data["journal_entries"]:
        packet.append("No journal entries this week.")
    packet.append("")

    # --- State of Mind ---
    packet.append("=== STATE OF MIND (How We Feel) ===")
    for d in sorted(data["state_of_mind"].keys()):
        rec = data["state_of_mind"][d]
        valence = safe_float(rec, "valence")
        labels = rec.get("emotion_labels", [])
        areas = rec.get("life_areas", [])
        parts = [f"{d}: valence {valence:.2f}" if valence is not None else f"{d}"]
        if labels: parts.append(f"emotions: {', '.join(labels[:3])}")
        if areas: parts.append(f"areas: {', '.join(areas[:2])}")
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
    anomaly_events = [a for a in data["anomalies"].values()
                      if a.get("severity") in ("moderate", "high")]
    if anomaly_events:
        packet.append("=== ANOMALY EVENTS ===")
        for a in anomaly_events:
            d = a.get("date", "?")
            sev = a.get("severity", "?")
            metrics = a.get("anomalous_metrics", [])
            hyp = a.get("hypothesis", "")
            labels = [m.get("label", "?") for m in metrics]
            packet.append(f"{d}: {sev} — {', '.join(labels)}")
            if hyp: packet.append(f"  Hypothesis: {hyp}")
        packet.append("")

    # --- Weather (for setting/atmosphere) ---
    packet.append("=== WEATHER (Seattle) ===")
    for d in sorted(data["weather"].keys()):
        rec = data["weather"][d]
        temp = safe_float(rec, "temp_avg_f")
        precip = safe_float(rec, "precipitation_mm")
        daylight = safe_float(rec, "daylight_hours")
        parts = [d]
        if temp is not None: parts.append(f"{temp:.0f}°F")
        if precip is not None: parts.append(f"{'Rain' if precip > 0.5 else 'Dry'}")
        if daylight is not None: parts.append(f"{daylight:.1f}h daylight")
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
            pillar_labels = {"sleep": "\U0001f634 Sleep", "movement": "\U0001f3cb\ufe0f Movement",
                            "nutrition": "\U0001f957 Nutrition", "metabolic": "\U0001f4ca Metabolic",
                            "mind": "\U0001f9e0 Mind", "relationships": "\U0001f4ac Relationships",
                            "consistency": "\U0001f3af Consistency"}
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
About 2-3 times per month (NOT every week), you include a brief interaction with one of the Board members when noteworthy events warrant expert commentary. {interview_desc} They have opinions and personality. Only include a Board interview if this week's data has a notable event, milestone, or inflection point that warrants it. If the week is quiet, skip the interview entirely."""

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
- If no level events occurred, that's fine — stability IS the story sometimes. Don't force gamification references.

CONTINUITY:
If you have previous installments, USE THEM. Pick up threads. Make callbacks. Track character development across weeks. If you wrote about his fear of rest days previously, and this week he voluntarily took two, SAY THAT. The longitudinal view is your superpower as the embedded journalist. If this is the first installment, establish the story from the beginning.

METRICS AS TEXTURE, NOT STRUCTURE:
When you reference numbers (and you should — they're concrete and vivid), weave them into the narrative naturally. "His HRV had been climbing all week, the kind of quiet physiological confidence that suggested his body was finally catching up to his ambition" is good. "On Monday his HRV was 45, on Tuesday it was 48, on Wednesday it was 51" is bad. Use numbers to ILLUMINATE, not to catalogue.

WHAT NOT TO DO:
- Don't write a health report or dashboard summary. You're not summarizing metrics.
- Don't walk through the week day by day. This is the cardinal sin. Find the THEMES.
- Don't give advice or recommendations. You're an observer.
- Don't be sycophantic. Bad weeks are bad weeks. Say so with compassion.
- Don't quote journal entries. Paraphrase, allude, capture tone — but never his words.
- Don't use every piece of data. Pick the 2-3 threads that serve THIS week's story.
- Don't write the same installment twice. Vary your structure, pace, and focus.
- Don't open with "This week..." — find a better way in.
- Don't use clichés about transformation journeys ("one step at a time", "every journey begins", etc.).
- Don't break the fourth wall about being an AI. You are Elena.
- Don't use emoji or markdown headers. Write clean prose.

FORMAT:
Return the installment as clean markdown with:
- First line: the title in quotes (your editorial choice for the week — sometimes lyrical, sometimes wry, sometimes just honest)
- Second line: blank
- Third line: [Weight: X lbs | Week Grade: avg X | T0 Streak: X days]
- Then blank line, then body text (~1,200-1,800 words)
- If including a Board interview, format as blockquotes (> )
- End with: a line break (---) followed by *Week N of The Measured Life*

Write in clean paragraphs. No bullet points. No numbered lists. No headers within the body. Just prose."""

    logger.info("[chronicle] Built Elena prompt from config with %d interviewees",
                len(board_loader.get_feature_members(config, 'chronicle')) - 1)  # minus Elena herself
    return prompt


# Fallback prompt (original hardcoded version, used if S3 config unavailable)
_FALLBACK_ELENA_PROMPT = """You are Elena Voss, a freelance journalist writing a weekly narrative chronicle called "The Measured Life." You've been embedded with Matthew — a 37-year-old Senior Director at a SaaS company who lives with his girlfriend Brittany in Seattle — since the start of his P40 journey: an attempt to transform his health, habits, and relationship with himself using a self-built AI-powered health intelligence platform.

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
About 2-3 times per month (NOT every week), you include a brief interaction with one of the Board members when noteworthy events warrant expert commentary. These feel like real interviews — Attia is precise and slightly intimidating, Huberman is enthusiastic and tangential, Norton is blunt and practical, Walker (sleep) is gentle but firm. They have opinions and personality. Only include a Board interview if this week's data has a notable event, milestone, or inflection point that warrants it. If the week is quiet, skip the interview entirely.

CHARACTER SHEET (GAMIFICATION LAYER):
Matthew has a persistent RPG-style Character Level (1-100) built from 7 weighted pillars: Sleep, Movement, Nutrition, Metabolic Health, Mind, Relationships, and Consistency. Each pillar has its own level and tier (Foundation, Momentum, Discipline, Mastery, Elite). Level changes require 5+ days of sustained improvement (up) or 7+ days of decline (down), making them RARE and meaningful — roughly 2-4 events per month total. Tier transitions are even rarer.

When the data packet includes CHARACTER SHEET data, use it as narrative texture:
- Tier transitions are Chronicle-worthy moments. "The week his Movement pillar crossed into Discipline" is a story.
- Cross-pillar effects (like Sleep Drag debuffing Movement) are built-in metaphors for how health domains interact.
- The overall Character Level is the closest thing to a single answer to "is this working?"
- Don't explain the RPG mechanics — weave the language naturally. "His Sleep score had been climbing for two weeks, the kind of quiet consistency the system rewards" is better than "His Sleep pillar leveled up from 42 to 43."
- If no level events occurred, that's fine — stability IS the story sometimes. Don't force gamification references.

CONTINUITY:
If you have previous installments, USE THEM. Pick up threads. Make callbacks. Track character development across weeks. If you wrote about his fear of rest days previously, and this week he voluntarily took two, SAY THAT. The longitudinal view is your superpower as the embedded journalist. If this is the first installment, establish the story from the beginning.

METRICS AS TEXTURE, NOT STRUCTURE:
When you reference numbers (and you should — they're concrete and vivid), weave them into the narrative naturally. "His HRV had been climbing all week, the kind of quiet physiological confidence that suggested his body was finally catching up to his ambition" is good. "On Monday his HRV was 45, on Tuesday it was 48, on Wednesday it was 51" is bad. Use numbers to ILLUMINATE, not to catalogue.

WHAT NOT TO DO:
- Don't write a health report or dashboard summary. You're not summarizing metrics.
- Don't walk through the week day by day. This is the cardinal sin. Find the THEMES.
- Don't give advice or recommendations. You're an observer.
- Don't be sycophantic. Bad weeks are bad weeks. Say so with compassion.
- Don't quote journal entries. Paraphrase, allude, capture tone — but never his words.
- Don't use every piece of data. Pick the 2-3 threads that serve THIS week's story.
- Don't write the same installment twice. Vary your structure, pace, and focus.
- Don't open with "This week..." — find a better way in.
- Don't use clichés about transformation journeys ("one step at a time", "every journey begins", etc.).
- Don't break the fourth wall about being an AI. You are Elena.
- Don't use emoji or markdown headers. Write clean prose.

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

def call_anthropic(system_prompt, user_message, api_key):
    # Delegates to retry_utils for exponential backoff + CloudWatch metrics (P1.8/P1.9)
    import retry_utils
    return retry_utils.call_anthropic_api(
        prompt=user_message,
        api_key=api_key,
        max_tokens=4096,
        system=system_prompt,
        temperature=0.6,
        timeout=90,
    )


# ══════════════════════════════════════════════════════════════════════════════
# MARKDOWN → HTML CONVERTER (simple prose conversion)
# ══════════════════════════════════════════════════════════════════════════════

def markdown_to_html(md_text):
    """Convert Elena's markdown prose to clean HTML for email and blog."""
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
            bq_text = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', bq_text)
            bq_text = re.sub(r'\*(.+?)\*', r'<em>\1</em>', bq_text)
            html_parts.append(f'<blockquote>{bq_text}</blockquote>')
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
        text = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', text)
        text = re.sub(r'\*(.+?)\*', r'<em>\1</em>', text)
        html_parts.append(f"<p>{text}</p>")

    # Flush any remaining blockquote
    if in_blockquote and bq_buffer:
        bq_text = " ".join(bq_buffer)
        bq_text = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', bq_text)
        bq_text = re.sub(r'\*(.+?)\*', r'<em>\1</em>', bq_text)
        html_parts.append(f'<blockquote>{bq_text}</blockquote>')

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

def build_email_html(title, stats_line, body_html, week_num, date_str, blog_url):
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

    return f'''<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
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
      Read the full series at <a href="{blog_url}" style="color:#666;">averagejoematt.com/blog</a>
    </p>
    <p style="font-family:-apple-system,sans-serif;font-size:12px;color:#888;margin:10px 0 4px;">Know someone who'd want this? They can get their own at <a href="https://averagejoematt.com/subscribe" style="color:#555;">averagejoematt.com/subscribe</a></p>
    <p style="font-family:-apple-system,sans-serif;font-size:9px;color:#bbb;margin:6px 0 0;">&#9874;&#65039; Personal health tracking only &mdash; not medical advice. Consult a qualified healthcare professional before making changes to your diet, exercise, or supplement regimen.</p>
  </div>

</div>
</body>
</html>'''


# ══════════════════════════════════════════════════════════════════════════════
# BLOG HTML
# ══════════════════════════════════════════════════════════════════════════════

# ══════════════════════════════════════════════════════════════════════════════
# JOURNAL PUBLISHER (averagejoematt.com/journal/) — Signal aesthetic
# Writes to site/journal/posts/week-{nn}/index.html + site/journal/posts.json
# ══════════════════════════════════════════════════════════════════════════════

def publish_to_journal(title, stats_line, body_html, week_num, date_str, all_installments):
    """Publish installment to the Signal-themed journal on averagejoematt.com.

    Writes:
      site/journal/posts/week-{nn}/index.html  — the post itself
      site/journal/posts.json                   — manifest for the listing page

    Non-fatal: failure here never breaks the Chronicle email.
    """
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        date_display = dt.strftime("%B %-d, %Y")
        date_mono = date_str
    except Exception:
        date_display = date_str
        date_mono = date_str

    # Extract read time (~250 words/min)
    word_count = len(body_html.split())
    read_min = max(4, round(word_count / 250))

    # Convert blog body_html (built for email) to prose-ready Signal HTML
    # Remap email-style <p> to prose <p> — classes already handled by Signal serif
    post_html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <meta name="description" content="{title} — Week {week_num} of The Measured Life by Elena Voss">
  <meta property="og:title" content="{title} — The Measured Life">
  <meta property="og:description" content="{stats_line}">
  <meta property="og:type" content="article">
  <title>{title} — The Measured Life</title>
  <link rel="stylesheet" href="/assets/css/tokens.css">
  <link rel="stylesheet" href="/assets/css/base.css">
  <style>
    :root {{
      --accent: var(--c-amber-500);
      --accent-dim: var(--c-amber-300);
      --accent-bg: var(--c-amber-100);
      --accent-bg-subtle: var(--c-amber-050);
      --border: rgba(200,132,58,0.15);
    }}
    .reading-progress {{ position:fixed;top:var(--nav-height);left:0;right:0;height:2px;background:var(--border-subtle);z-index:var(--z-overlay); }}
    .reading-progress__fill {{ height:100%;background:var(--accent);width:0%;transition:width 0.1s linear; }}
    .post-header {{ padding:calc(var(--nav-height) + var(--space-16)) var(--page-padding) var(--space-10);border-bottom:1px solid var(--border);max-width:calc(var(--prose-width) + var(--page-padding) * 2);margin:0 auto; }}
    .post-header__series {{ font-size:var(--text-2xs);letter-spacing:var(--ls-tag);text-transform:uppercase;color:var(--accent-dim);margin-bottom:var(--space-3); }}
    .post-header__title {{ font-family:var(--font-serif);font-size:clamp(28px,4vw,46px);color:var(--text);line-height:1.15;font-weight:400;font-style:italic;margin-bottom:var(--space-5); }}
    .post-header__meta {{ display:flex;align-items:center;gap:var(--space-5);font-size:var(--text-xs);letter-spacing:var(--ls-tag);text-transform:uppercase;color:var(--text-muted); }}
    .post-header__stats {{ font-size:var(--text-xs);color:var(--text-faint);letter-spacing:var(--ls-tag);margin-top:var(--space-3); }}
    .post-body {{ max-width:calc(var(--prose-width) + var(--page-padding) * 2);margin:0 auto;padding:var(--space-10) var(--page-padding) var(--space-20); }}
    .prose {{ font-family:var(--font-serif); }}
    .prose p {{ font-size:18px;line-height:1.85;color:var(--text);margin-bottom:var(--space-6); }}
    .prose p:first-child::first-letter {{ font-size:64px;line-height:0.8;float:left;margin-right:var(--space-3);margin-top:8px;color:var(--accent);font-family:var(--font-serif); }}
    .prose blockquote {{ border-left:2px solid var(--accent);padding:var(--space-4) var(--space-6);background:var(--accent-bg-subtle);margin:var(--space-8) 0;font-style:italic;font-size:17px;color:var(--text);line-height:1.7; }}
    .prose hr {{ border:none;border-top:1px solid var(--border);margin:var(--space-10) 0; }}
    .prose .signature {{ text-align:center;font-size:14px;color:var(--text-muted);font-style:italic; }}
    .prose strong {{ color:var(--text);font-weight:700; }}
    .post-nav {{ max-width:calc(var(--prose-width) + var(--page-padding) * 2);margin:0 auto;padding:var(--space-6) var(--page-padding) var(--space-16);border-top:1px solid var(--border);display:flex;justify-content:space-between;gap:var(--space-6); }}
    .post-nav a {{ font-family:var(--font-serif);font-size:17px;color:var(--text);text-decoration:none;transition:color var(--dur-fast); }}
    .post-nav a:hover {{ color:var(--accent); }}
    .post-nav span {{ display:block;font-family:var(--font-mono);font-size:var(--text-2xs);letter-spacing:var(--ls-tag);text-transform:uppercase;color:var(--text-muted);margin-bottom:var(--space-1); }}
  </style>
</head>
<body>
<div class="reading-progress"><div class="reading-progress__fill" id="rp"></div></div>
<nav class="nav">
  <a href="/" class="nav__brand">AMJ</a>
  <div class="nav__links">
    <a href="/#experiment" class="nav__link">The experiment</a>
    <a href="/platform/" class="nav__link">The platform</a>
    <a href="/journal/" class="nav__link active">Journal</a>
    <a href="/character/" class="nav__link">Character</a>
  </div>
  <div class="nav__status"><div class="pulse" style="background:var(--accent)"></div><span>The Measured Life</span></div>
</nav>
<div class="post-header">
  <div class="post-header__series">The Measured Life &middot; Week {week_num} &middot; By Elena Voss</div>
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
<div class="post-nav">
  <a href="/journal/"><span>&larr; All installments</span>The Measured Life archive</a>
  <a href="/"><span>The experiment</span>averagejoematt.com &rarr;</a>
</div>
<footer class="footer">
  <div class="footer__brand" style="color:var(--accent)">AMJ</div>
  <div class="footer__links">
    <a href="/" class="footer__link">Home</a>
    <a href="/character/" class="footer__link">Character</a>
  </div>
  <div class="footer__copy">// words when there's something worth saying</div>
</footer>
<script>
  const rp = document.getElementById('rp');
  window.addEventListener('scroll', () => {{
    const pct = window.scrollY / (document.body.scrollHeight - window.innerHeight) * 100;
    rp.style.width = Math.min(pct, 100) + '%';
  }});
</script>
</body>
</html>"""

    # Write the post
    post_key = f"site/journal/posts/week-{week_num:02d}/index.html"
    s3.put_object(
        Bucket=S3_BUCKET, Key=post_key,
        Body=post_html.encode("utf-8"),
        ContentType="text/html; charset=utf-8",
        CacheControl="max-age=300",
    )
    logger.info(f"[journal] Post written: {post_key}")

    # Update posts.json manifest
    posts_manifest = []
    for inst in sorted(all_installments, key=lambda x: x.get("week_number", 0), reverse=True):
        wn = inst.get("week_number", 0)
        posts_manifest.append({
            "week": wn,
            "title": inst.get("title", ""),
            "date": inst.get("date", ""),
            "stats_line": inst.get("stats_line", ""),
            "url": f"/journal/posts/week-{wn:02d}/",
            "excerpt": (inst.get("content_markdown") or "")[:300].strip(),
            "word_count": inst.get("word_count", 0),
            "has_board_interview": inst.get("has_board_interview", False),
        })

    s3.put_object(
        Bucket=S3_BUCKET, Key="site/journal/posts.json",
        Body=json.dumps({"posts": posts_manifest, "updated_at": datetime.now(timezone.utc).isoformat()}, indent=2).encode("utf-8"),
        ContentType="application/json",
        CacheControl="max-age=300",
    )
    logger.info(f"[journal] posts.json manifest updated ({len(posts_manifest)} posts)")

    return f"https://averagejoematt.com/journal/posts/week-{week_num:02d}/"


BLOG_POST_TEMPLATE = '''<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>{title} — The Measured Life</title>
  <link rel="stylesheet" href="style.css">
</head>
<body>
  <header>
    <a href="index.html" class="series-title">The Measured Life</a>
    <p class="byline">An ongoing chronicle by Elena Voss</p>
    <nav class="site-nav"><a href="index.html">Archive</a><a href="about.html">About</a></nav>
  </header>
  <main>
    <article>
      <h1>"{title}"</h1>
      <p class="meta">Week {week_num} &middot; {date_display}</p>
      <p class="stats">{stats_line}</p>
      <div class="body">
        {body_html}
      </div>
    </article>
    <nav class="post-nav">
      {prev_link}
      <a href="index.html">All installments</a>
      {next_link}
    </nav>
  </main>
  <footer>
    <p>&copy; 2026 The Measured Life. A chronicle of one man's attempt to change.</p>
  </footer>
</body>
</html>'''

BLOG_CSS = '''/* The Measured Life — Blog Styles */
* { margin: 0; padding: 0; box-sizing: border-box; }

body {
  font-family: Georgia, 'Times New Roman', serif;
  background: #fafaf9;
  color: #333;
  line-height: 1.75;
}

header {
  max-width: 680px;
  margin: 48px auto 0;
  padding: 0 24px 20px;
  border-bottom: 1px solid #e5e5e0;
  text-align: center;
}

.series-title {
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
  font-size: 12px;
  letter-spacing: 3px;
  text-transform: uppercase;
  color: #999;
  text-decoration: none;
}

.series-title:hover { color: #666; }

.byline {
  font-family: -apple-system, sans-serif;
  font-size: 13px;
  color: #999;
  margin-top: 6px;
}

.site-nav {
  margin-top: 12px;
  font-family: -apple-system, sans-serif;
  font-size: 12px;
}

.site-nav a {
  color: #bbb;
  text-decoration: none;
  margin: 0 10px;
  letter-spacing: 0.5px;
}

.site-nav a:hover { color: #666; }

main {
  max-width: 680px;
  margin: 0 auto;
  padding: 0 24px;
}

article { padding: 32px 0; }

h1 {
  font-size: 28px;
  font-weight: 400;
  font-style: italic;
  color: #1a1a1a;
  line-height: 1.3;
  margin-bottom: 8px;
}

.meta {
  font-family: -apple-system, sans-serif;
  font-size: 13px;
  color: #999;
}

.stats {
  font-family: -apple-system, sans-serif;
  font-size: 12px;
  color: #b0b0a8;
  margin-top: 4px;
  margin-bottom: 24px;
}

.body p {
  margin-bottom: 18px;
  font-size: 17px;
}

.body blockquote {
  margin: 24px 0;
  padding: 16px 24px;
  border-left: 3px solid #d4d4c8;
  background: #f0f0ea;
  font-style: italic;
  color: #555;
  font-size: 16px;
  line-height: 1.7;
}

.body blockquote strong {
  font-style: normal;
  color: #333;
}

.body hr {
  border: none;
  border-top: 1px solid #e5e5e0;
  margin: 32px 0;
}

.body .signature {
  text-align: center;
  color: #999;
  font-size: 14px;
}

.post-nav {
  display: flex;
  justify-content: space-between;
  padding: 20px 0;
  border-top: 1px solid #e5e5e0;
  font-family: -apple-system, sans-serif;
  font-size: 13px;
}

.post-nav a {
  color: #666;
  text-decoration: none;
}

.post-nav a:hover { color: #333; }

footer {
  max-width: 680px;
  margin: 0 auto;
  padding: 24px 24px 48px;
  text-align: center;
  font-family: -apple-system, sans-serif;
  font-size: 11px;
  color: #ccc;
}

@media (max-width: 720px) {
  header, main, footer { padding-left: 20px; padding-right: 20px; }
  h1 { font-size: 24px; }
  .body p { font-size: 16px; }
}'''


def build_blog_index(installments):
    """Generate the blog landing page from all installments."""
    # Separate latest from archive
    latest = installments[0] if installments else None
    archive = installments  # all installments including latest

    # Build featured/hero section for latest
    hero_html = ""
    if latest:
        l_title = latest.get("title", "Untitled")
        l_wn = latest.get("week_number", "?")
        l_date = latest.get("date", "?")
        try:
            l_dt = datetime.strptime(l_date, "%Y-%m-%d")
            l_date_display = l_dt.strftime("%B %-d, %Y")
        except Exception:
            l_date_display = l_date
        l_filename = f"week-{int(l_wn):02d}.html" if l_wn is not None else "week-01.html"
        l_kicker = "Prologue" if l_wn == 0 else f"Week {l_wn}"
        l_stats = latest.get("stats_line", "")
        l_stats_html = f'<p style="font-family:-apple-system,sans-serif;font-size:12px;color:#bbb;margin-top:4px;">{l_stats}</p>' if l_stats else ""
        hero_html = f'''<div class="hero">
      <div class="kicker">{l_kicker} &middot; {l_date_display}</div>
      <h2><a href="{l_filename}">"{l_title}"</a></h2>
      {l_stats_html}
      <a href="{l_filename}" class="read-link">Read {l_kicker.lower()} &rarr;</a>
    </div>'''

    # Build archive list
    entries_html = ""
    for inst in archive:
        title = inst.get("title", "Untitled")
        wn = inst.get("week_number", "?")
        date = inst.get("date", "?")
        try:
            dt = datetime.strptime(date, "%Y-%m-%d")
            date_display = dt.strftime("%B %-d, %Y")
        except Exception:
            date_display = date
        filename = f"week-{int(wn):02d}.html" if wn is not None else "week-01.html"
        label = "Prologue" if wn == 0 else f"Week {wn}"
        entries_html += f'''<li>
          <a href="{filename}">\"{title}\" <span class="label">{label}</span></a>
          <span class="date">{date_display}</span>
        </li>\n'''

    return f'''<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>The Measured Life &mdash; by Elena Voss</title>
  <link rel="stylesheet" href="style.css">
  <style>
    .hero {{ padding: 48px 0 40px; border-bottom: 1px solid #e5e5e0; }}
    .hero .kicker {{ font-family: -apple-system, sans-serif; font-size: 11px; letter-spacing: 2px; text-transform: uppercase; color: #999; margin-bottom: 16px; }}
    .hero h2 {{ font-size: 32px; font-weight: 400; font-style: italic; color: #1a1a1a; line-height: 1.3; margin: 0 0 16px; }}
    .hero h2 a {{ color: inherit; text-decoration: none; }}
    .hero h2 a:hover {{ color: #444; }}
    .hero .read-link {{ font-family: -apple-system, sans-serif; font-size: 13px; color: #333; text-decoration: none; letter-spacing: 0.5px; border-bottom: 1px solid #ccc; padding-bottom: 2px; }}
    .hero .read-link:hover {{ color: #000; border-color: #333; }}
    .series-intro {{ padding: 32px 0; font-size: 16px; color: #777; line-height: 1.7; border-bottom: 1px solid #e5e5e0; }}
    .archive-section {{ padding: 28px 0 0; }}
    .archive-label {{ font-family: -apple-system, sans-serif; font-size: 11px; letter-spacing: 2px; text-transform: uppercase; color: #bbb; margin-bottom: 16px; }}
    .archive-list {{ list-style: none; padding: 0; }}
    .archive-list li {{ padding: 14px 0; border-bottom: 1px solid #f0f0ea; display: flex; justify-content: space-between; align-items: baseline; }}
    .archive-list li a {{ color: #333; text-decoration: none; font-size: 17px; }}
    .archive-list li a:hover {{ color: #000; }}
    .archive-list .date {{ font-family: -apple-system, sans-serif; font-size: 12px; color: #bbb; white-space: nowrap; margin-left: 16px; }}
    .archive-list .label {{ font-family: -apple-system, sans-serif; font-size: 11px; letter-spacing: 0.5px; color: #999; text-transform: uppercase; }}
  </style>
</head>
<body>
  <header>
    <span class="series-title">The Measured Life</span>
    <p class="byline">An ongoing chronicle by Elena Voss</p>
    <nav class="site-nav"><a href="index.html">Archive</a><a href="about.html">About</a></nav>
  </header>
  <main>
    {hero_html}
    <div class="series-intro">
      What happens when a 37-year-old tech executive decides to transform his health using a custom-built AI platform that tracks everything his body produces? "The Measured Life" is an ongoing chronicle following one man's attempt to change &mdash; tracked by 19 data sources, coached by artificial intelligence, and observed by a journalist who's seen it all. New installments every Wednesday.
    </div>
    <div class="archive-section">
      <div class="archive-label">All Installments</div>
      <ul class="archive-list">
        {entries_html}
      </ul>
    </div>
  </main>
  <footer>
    The Measured Life &middot; A chronicle by Elena Voss &middot; Est. 2026
  </footer>
</body>
</html>'''


# ══════════════════════════════════════════════════════════════════════════════
# S3 BLOG PUBLISHING
# ══════════════════════════════════════════════════════════════════════════════

def publish_to_blog(title, stats_line, body_html, week_num, date_str, all_installments):
    """Write blog post HTML, CSS, and updated index to S3."""
    blog_prefix = "blog/"

    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        date_display = dt.strftime("%B %-d, %Y")
    except Exception:
        date_display = date_str

    # Navigation links
    prev_link = ""
    if week_num > 1:
        prev_wn = week_num - 1
        prev_link = f'<a href="week-{prev_wn:02d}.html">&larr; Week {prev_wn}</a>'
    next_link = ""  # current post is always latest

    post_html = BLOG_POST_TEMPLATE.format(
        title=title, week_num=week_num, date_display=date_display,
        stats_line=stats_line, body_html=body_html,
        prev_link=prev_link, next_link=next_link,
    )

    filename = f"week-{week_num:02d}.html"

    # Write post
    s3.put_object(
        Bucket=S3_BUCKET, Key=blog_prefix + filename,
        Body=post_html, ContentType="text/html",
        CacheControl="max-age=3600",
    )
    logger.info(f"Blog post written: {filename}")

    # Write/update CSS
    s3.put_object(
        Bucket=S3_BUCKET, Key=blog_prefix + "style.css",
        Body=BLOG_CSS, ContentType="text/css",
        CacheControl="max-age=86400",
    )

    # Rebuild index with all installments (newest first)
    index_html = build_blog_index(all_installments)
    s3.put_object(
        Bucket=S3_BUCKET, Key=blog_prefix + "index.html",
        Body=index_html, ContentType="text/html",
        CacheControl="max-age=300",
    )
    logger.info("Blog index updated")

    return f"https://averagejoematt.com/blog/{filename}"


# ══════════════════════════════════════════════════════════════════════════════
# STORE INSTALLMENT
# ══════════════════════════════════════════════════════════════════════════════

def store_installment(date_str, week_num, title, stats_line, raw_markdown,
                      body_html, themes, has_board):
    """Store installment in DynamoDB for continuity and blog generation."""
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
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }
        table.put_item(Item=item)
        logger.info(f"Installment stored: Week {week_num}")
    except Exception as e:
        logger.warning(f"Failed to store installment: {e}")


# ══════════════════════════════════════════════════════════════════════════════
# HANDLER
# ══════════════════════════════════════════════════════════════════════════════

def lambda_handler(event, context):
    logger.info("Wednesday Chronicle v1.1.0 (Board Centralization) — The Measured Life — starting...")

    data = gather_chronicle_data()
    if not data:
        return {"statusCode": 500, "body": "Failed to gather data"}

    # Build narrative-ready data packet
    data_packet, week_num = build_data_packet(data)
    logger.info(f"Data packet: {len(data_packet)} chars, Week {week_num}")

    # Build user message with previous installments for continuity
    user_parts = [data_packet]

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
        for inst in reversed(prev):  # oldest first
            wn = inst.get("week_number", "?")
            t = inst.get("title", "Untitled")
            md = inst.get("content_markdown", "")
            if md:
                # Truncate long previous installments to manage token budget
                if len(md) > 2000:
                    md = md[:2000] + "\n[...truncated...]"
                user_parts.append(f"\n--- Week {wn}: \"{t}\" ---\n{md}")
    else:
        user_parts.append("\n\nThis is the FIRST installment. Establish the story from the beginning. Who is Matthew? Why is he doing this? What are the stakes? Set the scene in Seattle. Introduce the platform, the data, the obsession. Make the reader want to come back next week.")

    user_message = "\n".join(user_parts)
    logger.info(f"Full prompt: {len(user_message)} chars")

    # Try config-driven prompt first, fall back to hardcoded
    elena_prompt = _build_elena_prompt_from_config()
    if elena_prompt:
        print("[INFO] Using config-driven Elena prompt")
    else:
        print("[INFO] Using fallback hardcoded Elena prompt")
        elena_prompt = _FALLBACK_ELENA_PROMPT

    # IC-16: Progressive context — narrative-relevant insight threads
    if _HAS_INSIGHT_WRITER:
        try:
            prev_ctx = insight_writer.build_insights_context(
                days=30, max_items=5, label="PLATFORM INSIGHTS (context for narrative)")
            if prev_ctx:
                user_message = prev_ctx + "\n\n" + user_message
        except Exception as e:
            print(f"[WARN] IC-16 failed: {e}")

    # Call Sonnet
    api_key = get_anthropic_key()
    logger.info("Calling Sonnet 4.5 for Elena's installment...")
    try:
        raw_installment = call_anthropic(elena_prompt, user_message, api_key)
    except Exception as e:
        logger.error(f"Anthropic failed: {e}")
        return {"statusCode": 500, "body": f"AI generation failed: {e}"}

    logger.info(f"Installment received: {len(raw_installment)} chars, ~{len(raw_installment.split())} words")

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
    logger.info(f"Title: \"{title}\"")

    # Convert to HTML
    body_html = markdown_to_html(body_md)

    # Detect Board interview
    has_board = ">" in body_md  # blockquotes indicate Board interview

    # Store in DynamoDB
    date_str = data["dates"]["end"]
    store_installment(date_str, week_num, title, stats_line, raw_installment,
                      body_html, [], has_board)

    # Publish to blog
    # Get all installments for index (including this new one)
    all_installments = []
    try:
        resp = table.query(
            KeyConditionExpression="pk = :pk AND begins_with(sk, :prefix)",
            ExpressionAttributeValues={
                ":pk": f"USER#{USER_ID}#SOURCE#chronicle",
                ":prefix": "DATE#",
            },
            ScanIndexForward=False,
        )
        all_installments = [d2f(i) for i in resp.get("Items", [])]
    except Exception as e:
        logger.warning(f"Failed to query all installments: {e}")
        all_installments = [{
            "title": title, "week_number": week_num, "date": date_str,
        }]

    try:
        blog_url = publish_to_blog(title, stats_line, body_html, week_num,
                                   date_str, all_installments)
    except Exception as e:
        logger.warning(f"Blog publish failed: {e}")
        blog_url = "https://averagejoematt.com/blog/"

    # Publish to Signal-themed journal on averagejoematt.com (non-fatal)
    try:
        journal_url = publish_to_journal(title, stats_line, body_html, week_num,
                                         date_str, all_installments)
        logger.info(f"[journal] Published: {journal_url}")
    except Exception as e:
        logger.warning(f"[journal] publish_to_journal failed (non-fatal): {e}")

    # Send email
    email_html = build_email_html(title, stats_line, body_html, week_num,
                                  date_str, blog_url)
    subject = f'The Measured Life — Week {week_num}: "{title}"'

    ses.send_email(
        FromEmailAddress=SENDER,
        Destination={"ToAddresses": [RECIPIENT]},
        Content={"Simple": {
            "Subject": {"Data": subject, "Charset": "UTF-8"},
            "Body":    {"Html": {"Data": email_html, "Charset": "UTF-8"}},
        }},
    )
    logger.info(f"Email sent: {subject}")

    # IC-15: Persist chronicle as narrative insight
    if _HAS_INSIGHT_WRITER:
        try:
            insight_writer.write_insight(
                digest_type="chronicle", insight_type="observation",
                text=f"Week {week_num}: {title}. {raw_installment[:600]}",
                pillars=insight_writer._extract_pillars_from_text(raw_installment[:500]),
                tags=["chronicle", "narrative", f"week_{week_num}"],
                confidence="high", actionable=False,
                date=data["dates"]["end"])
            print("[INFO] IC-15: chronicle insight persisted")
        except Exception as e:
            print(f"[WARN] IC-15 failed: {e}")

    return {
        "statusCode": 200,
        "body": f"Chronicle Week {week_num} published: \"{title}\" ({len(raw_installment.split())} words)",
    }
