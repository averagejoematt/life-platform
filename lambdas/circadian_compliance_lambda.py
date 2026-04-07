"""
Circadian Compliance Score Lambda — v1.0.0
BS-SL2: Pre-sleep behavioral score from light exposure, meal timing,
screen-free wind-down, and sleep onset vs inferred circadian phase.

Output: score 0-100 + "tonight you're set up for good/mediocre/poor sleep"
Surface in Evening Nudge (7 PM PT trigger).
Written BEFORE the night — predictive, not retrospective.

Schedule: daily at 7:00 PM PT (cron(0 2 * * ? *) UTC)

Scoring components (Huberman):
  1. Morning light exposure    (0-25 pts)  — journal entry or Apple Health UV
  2. Last meal timing          (0-25 pts)  — MacroFactor last food timestamp
  3. Screen-free wind-down     (0-25 pts)  — journal evening entry check
  4. Consistent sleep timing   (0-25 pts)  — SD of recent sleep onset times

Output: score 0-100, category (optimal/good/fair/poor), component breakdown,
        Huberman prescription for tonight.

Writes to: SOURCE#circadian | DATE#<today>

v1.0.0 — 2026-03-17 (BS-SL2)
"""

import json
import os
import time
import logging
import math
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import boto3

try:
    from platform_logger import get_logger
    logger = get_logger("circadian-compliance")
except ImportError:
    logger = logging.getLogger("circadian-compliance")
    logger.setLevel(logging.INFO)

# ── Config ─────────────────────────────────────────────────────────────────────
_REGION    = os.environ.get("AWS_REGION", "us-west-2")
TABLE_NAME = os.environ.get("TABLE_NAME", "life-platform")
USER_ID    = os.environ.get("USER_ID", "matthew")
USER_PREFIX = f"USER#{USER_ID}#SOURCE#"

dynamodb = boto3.resource("dynamodb", region_name=_REGION)
table    = dynamodb.Table(TABLE_NAME)

# Target sleep onset window (Huberman: 10–11 PM optimal for most adults)
TARGET_SLEEP_ONSET_HOUR = float(os.environ.get("TARGET_SLEEP_ONSET_HOUR", "22.5"))  # 10:30 PM
# Minimum hours before bed that last meal should finish
MEAL_CUTOFF_HOURS_BEFORE_BED = float(os.environ.get("MEAL_CUTOFF_HOURS_BEFORE_BED", "3.0"))
# Morning light window: first 60 min after wake for full credit
MORNING_LIGHT_WINDOW_MINUTES = int(os.environ.get("MORNING_LIGHT_WINDOW_MINUTES", "60"))


# ==============================================================================
# HELPERS
# ==============================================================================

def _sf(rec, field, default=None):
    if not rec or field not in rec:
        return default
    try:
        return float(rec[field])
    except (TypeError, ValueError):
        return default


def _to_dec(val):
    if val is None:
        return None
    try:
        return Decimal(str(round(float(val), 4)))
    except Exception:
        return None


def d2f(obj):
    if isinstance(obj, list):    return [d2f(i) for i in obj]
    if isinstance(obj, dict):    return {k: d2f(v) for k, v in obj.items()}
    if isinstance(obj, Decimal): return float(obj)
    return obj


def fetch_source_date(source, date_str):
    try:
        r = table.get_item(Key={"pk": USER_PREFIX + source, "sk": "DATE#" + date_str})
        return d2f(r.get("Item"))
    except Exception as e:
        logger.warning("fetch(%s, %s): %s", source, date_str, e)
        return None


def fetch_range(source, start, end):
    try:
        records, kwargs = [], {
            "KeyConditionExpression": "pk = :pk AND sk BETWEEN :s AND :e",
            "ExpressionAttributeValues": {
                ":pk": USER_PREFIX + source,
                ":s":  "DATE#" + start,
                ":e":  "DATE#" + end,
            },
        }
        while True:
            r = table.query(**kwargs)
            records.extend(d2f(i) for i in r.get("Items", []))
            if "LastEvaluatedKey" not in r:
                break
            kwargs["ExclusiveStartKey"] = r["LastEvaluatedKey"]
        return records
    except Exception as e:
        logger.warning("fetch_range(%s): %s", source, e)
        return []


def fetch_journal_today(date_str):
    """Fetch all journal entries for today."""
    pk = USER_PREFIX + "notion"
    try:
        resp = table.query(
            KeyConditionExpression="pk = :pk AND sk BETWEEN :s AND :e",
            ExpressionAttributeValues={
                ":pk": pk,
                ":s":  f"DATE#{date_str}#journal",
                ":e":  f"DATE#{date_str}#journal#~",
            },
        )
        return [d2f(i) for i in resp.get("Items", [])]
    except Exception as e:
        logger.warning("fetch_journal_today: %s", e)
        return []


def _parse_time_to_hour(time_str):
    """Parse ISO or HH:MM time string to decimal hour. Returns None on failure."""
    if not time_str:
        return None
    try:
        if "T" in str(time_str):
            dt = datetime.fromisoformat(str(time_str).replace("Z", "+00:00"))
            # Convert to local (PT) approximation: UTC-8
            local_dt = dt - timedelta(hours=8)
            return local_dt.hour + local_dt.minute / 60.0
        elif ":" in str(time_str):
            parts = str(time_str).split(":")
            return int(parts[0]) + int(parts[1]) / 60.0
    except Exception:
        pass
    return None


# ==============================================================================
# SCORING COMPONENTS
# ==============================================================================

def score_morning_light(today_str, journal_entries):
    """
    Component 1: Morning light exposure (0-25 pts).
    Huberman: 10-30 min of outdoor light within 60 min of waking is the #1
    circadian anchor. Sets cortisol peak timing, which determines sleep onset
    ~14-16 hours later.

    Signals checked (in priority):
      (a) Journal entry containing keywords for morning light / sunlight walk
      (b) Strava activity in first 2h of day with sport type Walk/Run
      (c) Apple Health UV/light exposure (if available)

    Scoring:
      Clear morning light evidence     → 25 pts
      Probable (walk but no light mention) → 15 pts
      No evidence                      → 5 pts (can't confirm, not penalized heavily)
    """
    score    = 5  # default: unknown
    evidence = "No morning light signal found — unable to confirm"

    # Check journal for morning light keywords
    light_keywords = ["morning light", "sunlight", "sunrise", "outside", "walk", "outdoor", "sun exposure"]
    for entry in journal_entries:
        raw_text = (entry.get("raw_text") or entry.get("content") or "").lower()
        template = (entry.get("template") or "").lower()
        if template == "morning" or "morning" in raw_text[:50]:
            if any(kw in raw_text for kw in light_keywords):
                score    = 25
                evidence = "Journal confirms morning light exposure"
                return score, evidence

    # Check Strava for early walk/run (proxy for outdoor exposure)
    strava = fetch_source_date("strava", today_str)
    if strava:
        for act in (strava.get("activities") or []):
            sport = (act.get("sport_type") or "").lower()
            start_time = act.get("start_date_local") or act.get("start_time") or ""
            hour = _parse_time_to_hour(start_time)
            if sport in ("walk", "run", "hike") and hour is not None and hour < 10.0:
                score    = 15
                evidence = f"Early {sport} detected ({start_time[:16] if start_time else 'unknown time'}) — probable outdoor light"
                return score, evidence

    return score, evidence


def score_meal_timing(today_str):
    """
    Component 2: Last meal timing vs projected sleep onset (0-25 pts).
    Huberman / Satchin Panda: last meal ≥3h before bed needed for
    core body temperature drop enabling deep sleep.

    Scoring:
      ≥4h before target sleep    → 25 pts
      3-4h                       → 18 pts
      2-3h                       → 10 pts
      <2h                        → 3 pts
      No data                    → 12 pts (neutral)
    """
    mf = fetch_source_date("macrofactor", today_str)
    if not mf:
        return 12, "No MacroFactor data for today — meal timing unknown"

    # MacroFactor stores food_log as list with timestamps
    food_log = mf.get("food_log") or mf.get("meals") or []
    if not food_log:
        return 12, "No food log entries today — meal timing unknown"

    # Find latest meal timestamp
    last_meal_hour = None
    for entry in food_log:
        ts = entry.get("logged_at") or entry.get("timestamp") or entry.get("time")
        hour = _parse_time_to_hour(ts) if ts else None
        if hour is not None:
            if last_meal_hour is None or hour > last_meal_hour:
                last_meal_hour = hour

    if last_meal_hour is None:
        return 12, "Meal times not available in food log — timing unknown"

    hours_before_bed = TARGET_SLEEP_ONSET_HOUR - last_meal_hour
    last_meal_str = f"{int(last_meal_hour):02d}:{int((last_meal_hour % 1) * 60):02d}"

    if hours_before_bed >= 4.0:
        return 25, f"Last meal ~{last_meal_str} — {hours_before_bed:.1f}h before target sleep (excellent)"
    elif hours_before_bed >= 3.0:
        return 18, f"Last meal ~{last_meal_str} — {hours_before_bed:.1f}h before target sleep (good)"
    elif hours_before_bed >= 2.0:
        return 10, f"Last meal ~{last_meal_str} — {hours_before_bed:.1f}h before target sleep (marginal)"
    else:
        return 3,  f"Last meal ~{last_meal_str} — only {max(0, hours_before_bed):.1f}h before target sleep (too close)"


def score_screen_windown(journal_entries):
    """
    Component 3: Screen-free wind-down evidence (0-25 pts).
    Huberman: blue light + dopamine-triggering content within 90 min of bed
    delays melatonin release by 1-3 hours.

    Checks evening journal for wind-down mentions.
    Keywords: reading, meditation, journaling, stretch, bath, dim lights, no screens.
    Penalty keywords: phone, screens, scrolling, netflix, tv, bright light.

    Scoring:
      Explicit wind-down mention   → 25 pts
      No signal                    → 15 pts (neutral — can't confirm either way)
      Screen use mentioned         → 5 pts
    """
    windown_positive = ["reading", "meditation", "meditat", "journal", "stretch", "bath",
                        "dim", "wind down", "wind-down", "candle", "no screen", "no phone",
                        "book", "quiet", "relaxed evening"]
    windown_negative = ["scrolling", "netflix", "youtube", "bright", "screens", "phone before bed",
                        "late night screen", "tv until", "instagram", "tiktok"]

    for entry in journal_entries:
        raw_text = (entry.get("raw_text") or entry.get("content") or "").lower()
        template = (entry.get("template") or "").lower()
        if "evening" in template or "evening" in raw_text[:50]:
            if any(kw in raw_text for kw in windown_negative):
                return 5, "Evening journal mentions screen use — blue light risk before bed"
            if any(kw in raw_text for kw in windown_positive):
                return 25, "Evening journal confirms screen-free wind-down"

    return 15, "No evening wind-down signal in journal — neutral"


def score_sleep_consistency(today_str):
    """
    Component 4: Sleep timing consistency (0-25 pts).
    Huberman: irregular sleep timing disrupts circadian phase, even with
    adequate total sleep. SD of sleep onset < 30 min = strong anchor.

    Uses 14 days of Whoop sleep_start timestamps.

    Scoring:
      SD < 20 min   → 25 pts
      SD 20-30 min  → 20 pts
      SD 30-45 min  → 12 pts
      SD 45-60 min  → 6 pts
      SD > 60 min   → 2 pts
      <7 days data  → 12 pts (insufficient)
    """
    d14 = (datetime.strptime(today_str, "%Y-%m-%d") - timedelta(days=14)).strftime("%Y-%m-%d")
    yesterday = (datetime.strptime(today_str, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")
    recs = fetch_range("whoop", d14, yesterday)

    onset_hours = []
    for rec in recs:
        onset = rec.get("sleep_start") or rec.get("bedtime_start")
        h = _parse_time_to_hour(onset)
        if h is not None:
            # Normalize: hours after midnight (e.g., 23:00 → 23.0, 00:30 → 24.5 for continuity)
            if h < 12:
                h += 24  # treat as next-day continuation (e.g., 1 AM = 25.0)
            onset_hours.append(h)

    if len(onset_hours) < 7:
        return 12, f"Only {len(onset_hours)} nights of sleep onset data — insufficient for consistency scoring"

    mean_onset = sum(onset_hours) / len(onset_hours)
    variance   = sum((h - mean_onset) ** 2 for h in onset_hours) / len(onset_hours)
    sd_hours   = math.sqrt(variance)
    sd_minutes = sd_hours * 60
    sd_str     = f"{sd_minutes:.0f} min SD over {len(onset_hours)} nights"

    if sd_minutes < 20:
        return 25, f"Excellent circadian anchor — {sd_str}"
    elif sd_minutes < 30:
        return 20, f"Good timing consistency — {sd_str}"
    elif sd_minutes < 45:
        return 12, f"Moderate variability — {sd_str} (Huberman: aim for <30 min SD)"
    elif sd_minutes < 60:
        return 6,  f"High variability — {sd_str} — inconsistent anchor weakens sleep pressure"
    else:
        return 2,  f"Very irregular bedtimes — {sd_str} — circadian rhythm likely disrupted"


# ==============================================================================
# SCORE ASSEMBLY
# ==============================================================================

def compute_circadian_score(today_str):
    """Compute all 4 components and return unified score + prescription."""
    journal = fetch_journal_today(today_str)

    light_score,  light_note   = score_morning_light(today_str, journal)
    meal_score,   meal_note    = score_meal_timing(today_str)
    screen_score, screen_note  = score_screen_windown(journal)
    consist_score, consist_note = score_sleep_consistency(today_str)

    total = light_score + meal_score + screen_score + consist_score

    if total >= 85:
        category     = "optimal"
        prescription = "Tonight you're set up for excellent sleep. All four circadian anchors are firing."
    elif total >= 65:
        category     = "good"
        prescription = "Tonight should be a good sleep night. One or two anchors could be stronger."
    elif total >= 45:
        category     = "fair"
        prescription = "Tonight's sleep setup is mediocre. Address the lowest-scoring component now."
    else:
        category     = "poor"
        prescription = "Tonight's sleep is at risk. Multiple circadian disruptions detected — act now."

    # Lowest-scoring component = tonight's priority
    components = [
        ("morning_light",     light_score,   light_note),
        ("meal_timing",       meal_score,    meal_note),
        ("screen_wind_down",  screen_score,  screen_note),
        ("sleep_consistency", consist_score, consist_note),
    ]
    weakest = min(components, key=lambda c: c[1])
    prescription += f" Priority tonight: {weakest[0].replace('_', ' ')} ({weakest[1]}/25 pts)."

    return {
        "date":        today_str,
        "score":       total,
        "category":    category,
        "prescription": prescription,
        "components": {
            "morning_light":     {"score": light_score,   "max": 25, "note": light_note},
            "meal_timing":       {"score": meal_score,    "max": 25, "note": meal_note},
            "screen_wind_down":  {"score": screen_score,  "max": 25, "note": screen_note},
            "sleep_consistency": {"score": consist_score, "max": 25, "note": consist_note},
        },
        "weakest_component": weakest[0],
        "huberman_note": (
            "Circadian compliance score is predictive, not retrospective — it tells you "
            "what tonight's sleep will likely look like based on today's behaviors. "
            "All 4 anchors must fire for consistently optimal sleep architecture."
        ),
    }


def store_circadian_score(result):
    """Write to SOURCE#circadian | DATE#<today>."""
    date_str = result["date"]
    item = {
        "pk":           USER_PREFIX + "circadian",
        "sk":           "DATE#" + date_str,
        "date":         date_str,
        "score":        _to_dec(result["score"]),
        "category":     result["category"],
        "prescription": result["prescription"],
        "weakest_component": result["weakest_component"],
        "computed_at":  datetime.now(timezone.utc).isoformat(),
    }
    # Encode components
    components_enc = {}
    for comp_name, comp_data in result["components"].items():
        components_enc[comp_name] = {
            "score": _to_dec(comp_data["score"]),
            "max":   Decimal(str(comp_data["max"])),
            "note":  comp_data["note"],
        }
    item["components"] = components_enc
    table.put_item(Item=item)
    logger.info("BS-SL2: Stored circadian score for %s: %d/100 (%s)",
                date_str, result["score"], result["category"])


# ==============================================================================
# LAMBDA HANDLER
# ==============================================================================

def lambda_handler(event, context):
    t0 = time.time()
    logger.info("Circadian Compliance Score v1.0.0 starting...")

    today_str = event.get("date") or datetime.now(timezone.utc).strftime("%Y-%m-%d")

    result  = compute_circadian_score(today_str)
    store_circadian_score(result)

    elapsed = time.time() - t0
    logger.info("Done in %.1fs — score=%d (%s)", elapsed, result["score"], result["category"])

    return {
        "statusCode":        200,
        "body":              f"Circadian score computed: {result['score']}/100 ({result['category']})",
        "date":              today_str,
        "score":             result["score"],
        "category":          result["category"],
        "weakest_component": result["weakest_component"],
        "elapsed_secs":      round(elapsed, 1),
    }
