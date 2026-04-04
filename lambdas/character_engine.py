"""
character_engine.py — Character Sheet scoring engine for the Life Platform.

Computes 7 weighted pillar scores, applies EMA smoothing, manages level/tier
transitions with anti-flip-flop rules, and applies cross-pillar effects.

Bundled alongside Lambda handlers (same pattern as board_loader.py).

Config: s3://{bucket}/config/character_sheet.json
DynamoDB: USER#matthew#SOURCE#character_sheet / DATE#YYYY-MM-DD

Usage:
    from character_engine import load_character_config, compute_character_sheet

v1.0.0 — 2026-03-02
v1.1.0 — 2026-03-30  (Statistical review: F-01 through F-15)
"""
import json
import logging
import math
import time
from datetime import datetime, timedelta, timezone
from decimal import Decimal

logger = logging.getLogger(__name__)

# ── In-memory cache (survives Lambda warm starts) ──
_config_cache = {"data": None, "ts": 0}
_CONFIG_TTL_S = 300  # 5 minutes

ENGINE_VERSION = "1.1.0"

# ── XP defaults (also in config) [F-02] ──
DEFAULT_XP_PER_LEVEL = 100
DEFAULT_DAILY_XP_DECAY = 2
DEFAULT_XP_BUFFER_THRESHOLD = 20

# ── Tier definitions (also in config, but hardcoded as fallback) ──
_DEFAULT_TIERS = [
    {"name": "Foundation", "emoji": "🔨", "min_level": 1,  "max_level": 20},
    {"name": "Momentum",   "emoji": "🔥", "min_level": 21, "max_level": 40},
    {"name": "Discipline", "emoji": "⚔️", "min_level": 41, "max_level": 60},
    {"name": "Mastery",    "emoji": "🏆", "min_level": 61, "max_level": 80},
    {"name": "Elite",      "emoji": "👑", "min_level": 81, "max_level": 100},
]


# ==============================================================================
# CONFIG LOADER
# ==============================================================================

def load_character_config(s3_client, bucket, force_refresh=False, user_id="matthew"):
    """Load character_sheet.json from S3 with warm-container caching."""
    now = time.time()
    if (not force_refresh and _config_cache["data"]
            and (now - _config_cache["ts"]) < _CONFIG_TTL_S):
        return _config_cache["data"]
    try:
        resp = s3_client.get_object(Bucket=bucket, Key=f"config/{user_id}/character_sheet.json")
        config = json.loads(resp["Body"].read().decode("utf-8"))
        _config_cache["data"] = config
        _config_cache["ts"] = now
        logger.info("[character_engine] Loaded config from S3 — %d pillars",
                    len(config.get("pillars", {})))
        return config
    except Exception as e:
        logger.warning("[character_engine] Failed to load config from S3: %s", e)
        if _config_cache["data"]:
            return _config_cache["data"]
        return None


# ==============================================================================
# UTILITY FUNCTIONS
# ==============================================================================

def _clamp(val, lo=0, hi=100):
    if val is None:
        return None
    return max(lo, min(hi, val))


def _safe_float(rec, field, default=None):
    if rec and field in rec:
        try:
            return float(rec[field])
        except (ValueError, TypeError):
            return default
    return default


def _pct_of_target(actual, target, perfect_pct=1.2):
    """Score 0-100 based on actual vs target. 100 at perfect_pct*target."""
    if actual is None or target is None or target <= 0:
        return None
    ratio = actual / target
    if ratio >= perfect_pct:
        return 100.0
    if ratio <= 0:
        return 0.0
    return round((ratio / perfect_pct) * 100, 1)


def _deviation_score(std_dev, ideal=0, worst=120):
    """Score 0-100 where lower std_dev is better."""
    if std_dev is None:
        return None
    if std_dev <= ideal:
        return 100.0
    if std_dev >= worst:
        return 0.0
    return round(100.0 * (1.0 - (std_dev - ideal) / (worst - ideal)), 1)


def _in_range_score(value, low, high, buffer=0.1):
    """Score 0-100 for value within range. 100 if in range, drops outside. [F-13]"""
    if value is None:
        return None
    if low <= value <= high:
        return 100.0
    range_span = max(high - low, 1)  # avoid division by zero
    if value < low:
        dist = (low - value) / (range_span * buffer)
        return _clamp(100.0 - dist * 100)
    dist = (value - high) / (range_span * buffer)
    return _clamp(100.0 - dist * 100)


def _trend_score(values, higher_is_better=True):
    """Score 0-100 based on linear trend direction."""
    if not values or len(values) < 3:
        return None
    n = len(values)
    x_mean = (n - 1) / 2.0
    y_mean = sum(values) / n
    num = sum((i - x_mean) * (v - y_mean) for i, v in enumerate(values))
    den = sum((i - x_mean) ** 2 for i in range(n))
    if den == 0:
        return 50.0
    slope = num / den
    if y_mean == 0:
        rel_slope = slope
    else:
        rel_slope = slope / abs(y_mean)
    if higher_is_better:
        score = 50.0 + rel_slope * 500
    else:
        score = 50.0 - rel_slope * 500
    return round(_clamp(score), 1)


def get_tier(level, config=None):
    """Get tier info for a given level."""
    tiers = (config or {}).get("tiers", _DEFAULT_TIERS)
    for tier in tiers:
        if tier["min_level"] <= level <= tier["max_level"]:
            return tier
    return tiers[-1] if level > 80 else tiers[0]


def _compute_xp(raw_score, previous_xp, config, day_number=None):
    """Compute XP delta with daily decay. Returns (xp_earned, xp_delta, new_xp_total). [F-02]
    C2: Grace period — decay scales linearly over first 14 days to avoid
    punishing new users before data stabilizes."""
    bands = config.get("xp_bands", [
        {"min_raw_score": 80, "xp": 3},
        {"min_raw_score": 60, "xp": 2},
        {"min_raw_score": 40, "xp": 1},
        {"min_raw_score": 20, "xp": 0},
        {"min_raw_score": 0,  "xp": -1},
    ])
    leveling = config.get("leveling", {})
    daily_decay = leveling.get("daily_xp_decay", DEFAULT_DAILY_XP_DECAY)

    # C2: Grace period — scale decay linearly over first 14 days
    grace_period = leveling.get("grace_period_days", 14)
    if day_number is not None and day_number < grace_period:
        daily_decay = daily_decay * min(1.0, day_number / grace_period)

    earned = -1
    for band in bands:
        if raw_score >= band["min_raw_score"]:
            earned = band["xp"]
            break

    xp_delta = earned - daily_decay
    new_xp = max(0, (previous_xp or 0) + earned - daily_decay)

    return earned, xp_delta, new_xp


# ==============================================================================
# PILLAR RAW SCORE COMPUTATIONS
# ==============================================================================

def compute_sleep_raw(data, config):
    """Compute Sleep pillar raw_score (0-100)."""
    pillar_cfg = config.get("pillars", {}).get("sleep", {})
    components = pillar_cfg.get("components", {})

    sleep = data.get("sleep") or {}
    scores = {}

    # Duration vs target
    dur_cfg = components.get("duration_vs_target", {})
    target_hrs = dur_cfg.get("target_hours", 7.5)
    sleep_hrs = _safe_float(sleep, "sleep_duration_hours") or _safe_float(sleep, "total_sleep_seconds")
    if sleep_hrs is not None and sleep_hrs > 24:
        sleep_hrs = sleep_hrs / 3600
    scores["duration_vs_target"] = _pct_of_target(sleep_hrs, target_hrs, 1.15) if sleep_hrs else None

    # Efficiency
    eff = _safe_float(sleep, "sleep_performance") or _safe_float(sleep, "sleep_efficiency_pct")
    scores["efficiency"] = _clamp(eff) if eff is not None else None

    # Deep sleep %
    deep_cfg = components.get("deep_sleep_pct", {})
    target_deep = deep_cfg.get("target_pct", 0.15)
    deep_pct = _safe_float(sleep, "deep_sleep_pct")
    if deep_pct is None:
        deep_s = _safe_float(sleep, "deep_sleep_seconds")
        total_s = _safe_float(sleep, "total_sleep_seconds")
        if deep_s and total_s and total_s > 0:
            deep_pct = deep_s / total_s
    if deep_pct is not None:
        if deep_pct > 1:
            deep_pct = deep_pct / 100
        scores["deep_sleep_pct"] = _clamp(round((deep_pct / target_deep) * 100, 1))
    else:
        scores["deep_sleep_pct"] = None

    # REM %
    rem_cfg = components.get("rem_pct", {})
    target_rem = rem_cfg.get("target_pct", 0.20)
    rem_pct = _safe_float(sleep, "rem_sleep_pct")
    if rem_pct is None:
        rem_s = _safe_float(sleep, "rem_sleep_seconds")
        total_s = _safe_float(sleep, "total_sleep_seconds")
        if rem_s and total_s and total_s > 0:
            rem_pct = rem_s / total_s
    if rem_pct is not None:
        if rem_pct > 1:
            rem_pct = rem_pct / 100
        scores["rem_pct"] = _clamp(round((rem_pct / target_rem) * 100, 1))
    else:
        scores["rem_pct"] = None

    # Onset consistency (std dev of sleep_start over 14d)
    sleep_14d = data.get("sleep_14d", [])
    onset_minutes = []
    for s in sleep_14d:
        start = s.get("sleep_start") or s.get("start")
        if start:
            try:
                if isinstance(start, str) and "T" in start:
                    dt = datetime.fromisoformat(start.replace("Z", "+00:00"))
                    mins = dt.hour * 60 + dt.minute
                    if mins < 720:
                        mins += 1440
                    onset_minutes.append(mins)
                elif isinstance(start, (int, float)):
                    onset_minutes.append(float(start))
            except Exception:
                pass

    if len(onset_minutes) >= 3:
        import statistics
        std = statistics.stdev(onset_minutes)
        scores["onset_consistency"] = _deviation_score(std, ideal=0, worst=120)
    else:
        scores["onset_consistency"] = None

    return _weighted_pillar_score(scores, components)


def compute_movement_raw(data, config):
    """Compute Movement pillar raw_score (0-100)."""
    pillar_cfg = config.get("pillars", {}).get("movement", {})
    components = pillar_cfg.get("components", {})
    scores = {}

    # Training frequency (sessions/week)
    strava_7d = data.get("strava_7d", [])
    session_count = 0
    for day in strava_7d:
        acts = day.get("activities", [])
        if acts:
            session_count += len(acts)
        elif day.get("activity_count"):
            session_count += int(day["activity_count"])
    freq_target = components.get("training_frequency", {}).get("target_sessions_week", 5)
    scores["training_frequency"] = _pct_of_target(session_count, freq_target, 1.4)

    # Zone 2 adequacy
    z2_target = components.get("zone2_adequacy", {}).get("target_minutes", 150)
    z2_minutes = 0
    for day in strava_7d:
        z2 = _safe_float(day, "zone2_minutes") or _safe_float(day, "time_in_zone_2_minutes")
        if z2:
            z2_minutes += z2
        for act in (day.get("activities") or []):
            z2a = _safe_float(act, "zone2_minutes")
            if z2a:
                z2_minutes += z2a
    scores["zone2_adequacy"] = _pct_of_target(z2_minutes, z2_target, 1.3)

    # Training load balance (TSB)
    tsb = data.get("tsb")
    if tsb is not None and isinstance(tsb, dict):
        tsb_val = _safe_float(tsb, "tsb") or _safe_float(tsb, "value")
    elif isinstance(tsb, (int, float)):
        tsb_val = float(tsb)
    else:
        tsb_val = None
    if tsb_val is not None:
        scores["training_load_balance"] = _in_range_score(tsb_val, -10, 25, buffer=0.5)
    else:
        scores["training_load_balance"] = None

    # Progressive overload (CTL trend over 42d)
    strava_42d = data.get("strava_42d", [])
    if len(strava_42d) >= 7:
        ctl_vals = []
        for day in strava_42d:
            ctl = _safe_float(day, "training_load") or _safe_float(day, "ctl")
            if ctl is not None:
                ctl_vals.append(ctl)
        scores["progressive_overload"] = _trend_score(ctl_vals, higher_is_better=True) if len(ctl_vals) >= 7 else None
    else:
        scores["progressive_overload"] = None

    # Movement diversity
    activity_types = set()
    for day in strava_7d:
        for act in (day.get("activities") or []):
            sport = act.get("sport_type") or act.get("type", "")
            if sport:
                activity_types.add(sport.lower())
    diversity_target = components.get("movement_diversity", {}).get("target_types", 4)
    scores["movement_diversity"] = _pct_of_target(len(activity_types), diversity_target, 1.5)

    # Daily steps
    apple = data.get("apple") or {}
    steps = _safe_float(apple, "steps")
    step_target = components.get("daily_steps", {}).get("target", 8000)
    scores["daily_steps"] = _pct_of_target(steps, step_target, 1.5) if steps else None

    return _weighted_pillar_score(scores, components)


def _body_comp_score(current_weight, config):
    """Two-phase body composition scoring: sigmoid during loss, band during maintenance. [F-04]"""
    baseline = config.get("baseline", {})
    start = baseline.get("start_weight_lbs", 302)
    goal = baseline.get("goal_weight_lbs", 185)
    maintenance_band = baseline.get("maintenance_band_lbs", 3)
    phase = baseline.get("weight_phase", "loss")

    if current_weight is None:
        return None

    if phase == "maintenance":
        deviation = abs(current_weight - goal)
        if deviation <= maintenance_band:
            return 100.0
        penalty_range = 20.0 - maintenance_band
        if penalty_range <= 0:
            return 0.0
        score = 100.0 - ((deviation - maintenance_band) / penalty_range) * 100
        return round(_clamp(score), 1)

    # Loss phase: sigmoid curve
    if start == goal:
        return None
    progress = (start - current_weight) / (start - goal)
    progress = max(0, min(1.2, progress))
    # Sigmoid: steeper in middle, rewards early momentum
    score = 100 / (1 + math.exp(-8 * (progress - 0.5)))
    return round(_clamp(score), 1)


def compute_nutrition_raw(data, config):
    """Compute Nutrition pillar raw_score (0-100)."""
    pillar_cfg = config.get("pillars", {}).get("nutrition", {})
    components = pillar_cfg.get("components", {})
    baseline_cfg = config.get("baseline", {})
    scores = {}

    mf = data.get("macrofactor") or {}

    # Calorie adherence
    cals = _safe_float(mf, "calories") or _safe_float(mf, "total_calories")
    cal_target = _safe_float(mf, "calorie_target") or _safe_float(mf, "target_calories")
    if cals is not None and cal_target and cal_target > 0:
        deviation = abs(cals - cal_target) / cal_target
        scores["calorie_adherence"] = _clamp(round(100 - (deviation / 0.20) * 100, 1))
    else:
        scores["calorie_adherence"] = None

    # Protein total
    protein = _safe_float(mf, "protein") or _safe_float(mf, "total_protein")
    protein_target = components.get("protein_total", {}).get("target_grams", 190)
    scores["protein_total"] = _pct_of_target(protein, protein_target, 1.2)

    # Protein distribution
    meals = mf.get("meals") or []
    high_protein_meals = 0
    dist_threshold = components.get("protein_distribution", {}).get("threshold_grams", 30)
    dist_target = components.get("protein_distribution", {}).get("target_meals", 4)
    for meal in meals:
        mp = _safe_float(meal, "protein")
        if mp and mp >= dist_threshold:
            high_protein_meals += 1
    if meals:
        scores["protein_distribution"] = _pct_of_target(high_protein_meals, dist_target, 1.25)
    else:
        scores["protein_distribution"] = None

    # Consistency (14d)
    mf_14d = data.get("macrofactor_14d", [])
    if mf_14d:
        in_range_count = 0
        tracked_count = 0
        for day in mf_14d:
            dc = _safe_float(day, "calories") or _safe_float(day, "total_calories")
            dt_target = _safe_float(day, "calorie_target") or _safe_float(day, "target_calories") or cal_target
            if dc is not None and dt_target and dt_target > 0:
                tracked_count += 1
                if abs(dc - dt_target) / dt_target <= 0.10:
                    in_range_count += 1
        scores["consistency"] = round((in_range_count / tracked_count) * 100, 1) if tracked_count >= 3 else None
    else:
        scores["consistency"] = None

    # Body composition progress — sigmoid loss / maintenance band [F-04]
    scores["body_composition_progress"] = _body_comp_score(data.get("latest_weight"), config)

    return _weighted_pillar_score(scores, components)


def compute_metabolic_raw(data, config):
    """Compute Metabolic Health pillar raw_score (0-100)."""
    pillar_cfg = config.get("pillars", {}).get("metabolic", {})
    components = pillar_cfg.get("components", {})
    scores = {}

    # Body fat trajectory
    withings_30d = data.get("withings_30d", [])
    bf_vals = [_safe_float(w, "body_fat_pct") or _safe_float(w, "fat_mass_pct")
               for w in withings_30d]
    bf_vals = [v for v in bf_vals if v is not None]
    scores["body_fat_trajectory"] = _trend_score(bf_vals, higher_is_better=False) if len(bf_vals) >= 3 else None

    # CGM glucose control
    apple = data.get("apple") or {}
    tir = _safe_float(apple, "glucose_time_in_range_pct")
    if tir is not None:
        scores["cgm_glucose_control"] = _clamp(tir)
    else:
        avg_glucose = _safe_float(apple, "glucose_avg") or _safe_float(apple, "blood_glucose_avg")
        scores["cgm_glucose_control"] = _in_range_score(avg_glucose, 70, 110, buffer=0.5) if avg_glucose else None

    # Lab biomarkers (with decay)
    labs_latest = data.get("labs_latest") or {}
    compute_date = data.get("date", datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    scores["lab_biomarkers"] = _compute_lab_score(labs_latest, compute_date, components.get("lab_biomarkers", {}))

    # Blood pressure
    bp = data.get("bp_data") or {}
    bp_sys = _safe_float(bp, "systolic")
    bp_dia = _safe_float(bp, "diastolic")
    if bp_sys is not None and bp_dia is not None:
        sys_score = _in_range_score(bp_sys, 90, 120, buffer=0.3)
        dia_score = _in_range_score(bp_dia, 60, 80, buffer=0.3)
        scores["blood_pressure"] = round((sys_score + dia_score) / 2, 1)
    else:
        scores["blood_pressure"] = None

    # Resting heart rate
    whoop = data.get("whoop") or data.get("sleep") or {}
    rhr = _safe_float(whoop, "resting_heart_rate")
    scores["resting_heart_rate"] = _in_range_score(rhr, 40, 65, buffer=0.4) if rhr else None

    return _weighted_pillar_score(scores, components)


def _compute_lab_score(labs, compute_date, lab_cfg):
    """Compute lab biomarker composite score with time decay."""
    if not labs:
        return None
    lab_date_str = labs.get("date") or labs.get("draw_date")
    if not lab_date_str:
        return None
    try:
        lab_date = datetime.strptime(lab_date_str[:10], "%Y-%m-%d").date()
        comp_date = datetime.strptime(compute_date[:10], "%Y-%m-%d").date()
        days_since = (comp_date - lab_date).days
    except Exception:
        return None
    if days_since < 0:
        days_since = 0

    # Decay: 1.0 for 30d, to 0.5 at 90d, to 0.0 at 180d [F-07]
    if days_since <= 30:
        decay = 1.0
    elif days_since <= 90:
        decay = 1.0 - 0.5 * ((days_since - 30) / 60)
    elif days_since <= 180:
        decay = 0.5 - 0.5 * ((days_since - 90) / 90)
    else:
        decay = 0.0  # Fully expired — no contribution from stale labs

    markers = {
        "apob": {"ideal_low": 40, "ideal_high": 90},
        "hba1c": {"ideal_low": 4.0, "ideal_high": 5.4},
        "fasting_glucose": {"ideal_low": 70, "ideal_high": 100},
        "ldl": {"ideal_low": 50, "ideal_high": 100},
        "hdl": {"ideal_low": 50, "ideal_high": 100},
        "triglycerides": {"ideal_low": 30, "ideal_high": 100},
    }
    marker_scores = []
    for marker, ranges in markers.items():
        val = _safe_float(labs, marker)
        if val is not None:
            marker_scores.append(_in_range_score(val, ranges["ideal_low"], ranges["ideal_high"], buffer=0.4))
    if not marker_scores:
        return None
    return round(sum(marker_scores) / len(marker_scores) * decay, 1)


def compute_mind_raw(data, config):
    """Compute Mind pillar raw_score (0-100)."""
    pillar_cfg = config.get("pillars", {}).get("mind", {})
    components = pillar_cfg.get("components", {})
    scores = {}

    hs = data.get("habit_scores") or {}

    # T0 habit compliance
    t0_pct = _safe_float(hs, "tier0_pct")
    if t0_pct is not None:
        scores["t0_habit_compliance"] = round(t0_pct * 100, 1) if t0_pct <= 1 else _clamp(t0_pct)
    else:
        scores["t0_habit_compliance"] = None

    # T1 habit compliance
    t1_pct = _safe_float(hs, "tier1_pct")
    if t1_pct is not None:
        scores["t1_habit_compliance"] = round(t1_pct * 100, 1) if t1_pct <= 1 else _clamp(t1_pct)
    else:
        scores["t1_habit_compliance"] = None

    # Journal consistency (14d)
    j14d_count = data.get("journal_14d_count")
    if j14d_count is not None:
        scores["journal_consistency"] = _clamp(round((j14d_count / 14) * 100, 1))
    elif data.get("journal_entries"):
        scores["journal_consistency"] = 50.0
    else:
        scores["journal_consistency"] = None

    # State of Mind valence
    som = data.get("state_of_mind") or {}
    valence = _safe_float(som, "valence") or _safe_float(som, "average_valence")
    if valence is not None:
        if -5 <= valence <= 5:
            scores["state_of_mind_valence"] = _clamp(round((valence + 3) / 6 * 100, 1))
        elif 1 <= valence <= 7:
            scores["state_of_mind_valence"] = _clamp(round((valence - 1) / 6 * 100, 1))
        else:
            scores["state_of_mind_valence"] = _clamp(valence)
    else:
        scores["state_of_mind_valence"] = None

    # Stress management
    whoop = data.get("whoop") or {}
    recovery = _safe_float(whoop, "recovery_score")
    if recovery is not None:
        scores["stress_management"] = _clamp(recovery)
    else:
        stress = _safe_float(whoop, "day_strain") or _safe_float(whoop, "strain")
        scores["stress_management"] = _in_range_score(stress, 6, 16, buffer=0.4) if stress else None

    # Vice control — logarithmic curve [F-12]
    vice_streaks = data.get("vice_streaks") or {}
    if vice_streaks:
        streaks = [v for v in vice_streaks.values() if isinstance(v, (int, float))]
        if streaks:
            avg_streak = sum(streaks) / len(streaks)
            # Log curve: day 7 ≈ 58, day 14 ≈ 77, day 30 = 100
            scores["vice_control"] = _clamp(round(
                100 * math.log(1 + avg_streak) / math.log(31), 1
            ))
        else:
            scores["vice_control"] = None
    else:
        scores["vice_control"] = None

    return _weighted_pillar_score(scores, components)


def compute_relationships_raw(data, config):
    """Compute Relationships pillar raw_score (0-100)."""
    pillar_cfg = config.get("pillars", {}).get("relationships", {})
    components = pillar_cfg.get("components", {})
    scores = {}

    journal = data.get("journal") or {}
    entries = data.get("journal_entries") or []

    # Social interaction frequency
    social_score = None
    for entry in entries:
        sc = _safe_float(entry, "social_connection_score") or _safe_float(entry, "enriched_social_connection")
        if sc is not None:
            social_score = sc
            break
    if social_score is not None:
        scores["social_interaction_frequency"] = _clamp(round(social_score * 10, 1)) if social_score <= 10 else _clamp(social_score)
    else:
        scores["social_interaction_frequency"] = None

    # Interaction quality
    themes = journal.get("themes", [])
    social_themes = [t for t in themes if any(k in t.lower() for k in ["social", "friend", "family", "partner", "relationship"])]
    if social_themes:
        scores["interaction_quality"] = min(100, len(social_themes) * 33)
    elif themes:
        scores["interaction_quality"] = 30.0
    else:
        scores["interaction_quality"] = None

    # Buddy engagement
    buddy_days = data.get("buddy_freshness_days")
    if buddy_days is not None:
        scores["buddy_engagement"] = _clamp(round(100 - (buddy_days / 7) * 100, 1))
    else:
        scores["buddy_engagement"] = None

    # Social mood correlation
    mood = _safe_float(journal, "mood_avg")
    if mood is not None and social_score is not None:
        scores["social_mood_correlation"] = _clamp(round((mood / 10) * 100, 1)) if mood <= 10 else _clamp(mood)
    else:
        scores["social_mood_correlation"] = None

    return _weighted_pillar_score(scores, components)


def compute_consistency_raw(data, config, other_pillar_raw_scores):
    """Compute Consistency meta-pillar raw_score (0-100)."""
    pillar_cfg = config.get("pillars", {}).get("consistency", {})
    components = pillar_cfg.get("components", {})
    scores = {}

    # Cross-pillar variance
    other_scores = [v for k, v in other_pillar_raw_scores.items()
                    if k != "consistency" and v is not None]
    if len(other_scores) >= 3:
        import statistics
        std = statistics.stdev(other_scores)
        scores["cross_pillar_variance"] = _deviation_score(std, ideal=0, worst=30)
    else:
        scores["cross_pillar_variance"] = None

    # Data completeness
    completeness = data.get("data_completeness_pct")
    if completeness is not None:
        scores["data_completeness"] = _clamp(completeness)
    else:
        expected = ["sleep", "macrofactor", "apple", "habitify", "strava"]
        present = sum(1 for k in expected if data.get(k))
        scores["data_completeness"] = round((present / len(expected)) * 100, 1)

    # Streak maintenance
    streak = data.get("streak_all_above_30th")
    if streak is not None:
        scores["streak_maintenance"] = _clamp(round((streak / 14) * 100, 1))
    else:
        scores["streak_maintenance"] = None

    # Weekend-weekday stability
    ww_ratio = data.get("weekend_weekday_ratio")
    if ww_ratio is not None:
        scores["weekend_weekday_stability"] = _clamp(round(100 - abs(1.0 - ww_ratio) * 200, 1))
    else:
        scores["weekend_weekday_stability"] = None

    return _weighted_pillar_score(scores, components)


def _weighted_pillar_score(component_scores, components_config):
    """Weighted average with data completeness confidence penalty. [F-01]"""
    weighted_sum = 0.0
    total_weight = 0.0
    max_possible_weight = 0.0
    details = {}

    for comp_name, score in component_scores.items():
        comp_cfg = components_config.get(comp_name, {})
        weight = comp_cfg.get("weight", 0) if isinstance(comp_cfg, dict) else comp_cfg
        max_possible_weight += weight
        details[comp_name] = {"score": score, "weight": weight}
        if score is not None and weight > 0:
            weighted_sum += score * weight
            total_weight += weight

    if total_weight == 0:
        details["_confidence"] = 0.0
        details["_data_coverage"] = 0.0
        return 50.0, details  # true neutral when no data [F-09]

    raw_score = weighted_sum / total_weight
    data_coverage = total_weight / max_possible_weight if max_possible_weight > 0 else 0
    confidence_threshold = 0.80  # full confidence at 80%+ data coverage
    confidence = min(1.0, data_coverage / confidence_threshold)

    # Blend toward neutral as confidence drops
    adjusted_score = raw_score * confidence + 50.0 * (1.0 - confidence)

    details["_confidence"] = round(confidence, 3)
    details["_data_coverage"] = round(data_coverage, 3)

    return round(_clamp(adjusted_score), 1), details


# ==============================================================================
# EMA + LEVEL COMPUTATION
# ==============================================================================

def compute_ema_level_score(raw_scores_history, config, pillar_name=None):
    """Compute EMA of raw scores. Uses per-pillar lambda if available. [F-03]"""
    leveling = config.get("leveling", {})

    # Per-pillar lambda override
    if pillar_name:
        pillar_cfg = config.get("pillars", {}).get(pillar_name, {})
        lam = pillar_cfg.get("ema_lambda", leveling.get("ema_lambda", 0.85))
    else:
        lam = leveling.get("ema_lambda", 0.85)

    window = leveling.get("ema_window_days", 21)
    recent = raw_scores_history[-window:] if len(raw_scores_history) > window else raw_scores_history
    if not recent:
        return 50.0  # [F-09]

    weights = [lam ** i for i in range(len(recent))]
    weights.reverse()

    total = sum(r * w for r, w in zip(recent, weights))
    total_w = sum(weights)
    return round(total / total_w, 1) if total_w > 0 else 50.0


def evaluate_level_changes(pillar_name, current_level_score, previous_state, config):
    """Level changes with progressive difficulty by tier. [F-15, F-10, F-11, F-02]"""
    leveling = config.get("leveling", {})

    # Progressive streak overrides by tier [F-15]
    tier_overrides = leveling.get("tier_streak_overrides", {})

    prev = previous_state or {
        "level": 1, "tier": "Foundation", "streak_above": 0,
        "streak_below": 0, "xp_total": 0
    }
    current_level = prev.get("level", 1)
    current_tier_info = get_tier(current_level, config)
    current_tier_name = current_tier_info["name"]
    streak_above = prev.get("streak_above", 0)
    streak_below = prev.get("streak_below", 0)
    xp_total = prev.get("xp_total", 0)

    # Look up streak requirements for current tier
    tier_cfg = tier_overrides.get(current_tier_name, {})
    up_streak_needed = tier_cfg.get("up", leveling.get("level_up_streak_days", 5))
    down_streak_needed = tier_cfg.get("down", leveling.get("level_down_streak_days", 7))
    tier_up_streak_needed = tier_cfg.get("tier_boundary_up", leveling.get("tier_up_streak_days", 7))
    tier_down_streak_needed = tier_cfg.get("tier_boundary_down", leveling.get("tier_down_streak_days", 10))

    # Variable step size [F-10]
    level_step_threshold = leveling.get("level_step_threshold", 10)

    # XP buffer gate for level-down [F-02]
    xp_per_level = leveling.get("xp_per_level", DEFAULT_XP_PER_LEVEL)
    xp_buffer_threshold = leveling.get("xp_buffer_threshold", DEFAULT_XP_BUFFER_THRESHOLD)
    xp_buffer = xp_total % xp_per_level if xp_per_level > 0 else 0

    target_level = max(1, min(100, round(current_level_score)))
    events = []

    if target_level > current_level:
        streak_above += 1
        streak_below = 0
        if streak_above >= up_streak_needed:
            old_tier = get_tier(current_level, config)["name"]
            new_tier = get_tier(current_level + 1, config)["name"]
            would_cross_tier = old_tier != new_tier

            if would_cross_tier and streak_above < tier_up_streak_needed:
                pass  # Hold — need longer streak for tier transition
            else:
                old_level = current_level
                delta = target_level - current_level
                step = 2 if delta > level_step_threshold else 1
                current_level = min(current_level + step, 100)
                streak_above = 0
                events.append({
                    "type": "level_up", "pillar": pillar_name,
                    "old_level": old_level, "new_level": current_level,
                })
    elif target_level < current_level:
        streak_below += 1
        streak_above = 0
        if streak_below >= down_streak_needed:
            # XP buffer gate: can't lose a level until XP buffer is depleted
            if xp_buffer >= xp_buffer_threshold:
                pass  # Buffer absorbs the pressure — hold level
            else:
                old_tier = get_tier(current_level, config)["name"]
                new_tier = get_tier(current_level - 1, config)["name"]
                would_cross_tier = old_tier != new_tier

                if would_cross_tier and streak_below < tier_down_streak_needed:
                    pass  # Hold — need longer streak for tier demotion
                else:
                    old_level = current_level
                    current_level = max(current_level - 1, 1)
                    streak_below = 0
                    events.append({
                        "type": "level_down", "pillar": pillar_name,
                        "old_level": old_level, "new_level": current_level,
                    })
    else:
        # Equal day: hold streaks constant [F-11]
        pass

    # Check tier transitions
    new_tier_info = get_tier(current_level, config)
    new_tier = new_tier_info["name"]
    current_tier = prev.get("tier", "Foundation")
    if new_tier != current_tier:
        etype = "tier_up" if current_level > prev.get("level", 1) else "tier_down"
        events.append({
            "type": etype, "pillar": pillar_name,
            "old_tier": current_tier, "new_tier": new_tier,
            "old_level": prev.get("level", 1), "new_level": current_level,
        })
        current_tier = new_tier

    return {
        "level": current_level, "tier": current_tier,
        "tier_emoji": new_tier_info.get("emoji", "🔨"),
        "streak_above": streak_above, "streak_below": streak_below,
        "xp_total": xp_total, "xp_buffer": xp_buffer, "events": events,
    }


# ==============================================================================
# CROSS-PILLAR EFFECTS
# ==============================================================================

def compute_cross_pillar_effects(pillar_levels, config):
    """Evaluate cross-pillar effects. Returns (active_effects, modifier_dict). [F-05]"""
    effects_config = config.get("cross_pillar_effects", [])
    active = []
    modifiers = {}

    for effect in effects_config:
        condition = effect.get("condition", "")
        targets = effect.get("targets", {})

        if _evaluate_condition(condition, pillar_levels):
            active.append({
                "name": effect["name"], "emoji": effect.get("emoji", ""),
                "condition": condition, "targets": targets,
            })
            for target_pillar, mod_spec in targets.items():
                # Support both old format (raw number) and new format (dict with type+value)
                if isinstance(mod_spec, dict):
                    mod_value = mod_spec.get("value", 0)
                else:
                    mod_value = mod_spec

                if target_pillar == "_all":
                    for p in pillar_levels:
                        modifiers[p] = modifiers.get(p, 0) + mod_value
                else:
                    modifiers[target_pillar] = modifiers.get(target_pillar, 0) + mod_value

    return active, modifiers


def _evaluate_condition(condition_str, pillar_levels):
    if not condition_str:
        return False
    condition_str = condition_str.strip()

    if condition_str.startswith("all_pillars"):
        parts = condition_str.split()
        if len(parts) >= 3:
            op, val = parts[1], float(parts[2])
            return all(_compare(lv, op, val) for lv in pillar_levels.values() if lv is not None)
        return False

    if "vice_streak" in condition_str:
        return False  # Handled via data

    if " AND " in condition_str:
        return all(_evaluate_condition(sc.strip(), pillar_levels) for sc in condition_str.split(" AND "))

    parts = condition_str.split()
    if len(parts) >= 3:
        pillar, op, val = parts[0].strip(), parts[1].strip(), float(parts[2])
        level = pillar_levels.get(pillar)
        return _compare(level, op, val) if level is not None else False
    return False


def _compare(a, op, b):
    if op == "<":   return a < b
    if op == "<=":  return a <= b
    if op == ">":   return a > b
    if op == ">=":  return a >= b
    if op == "==":  return a == b
    if op == "!=":  return a != b
    return False


# ==============================================================================
# MAIN ORCHESTRATOR
# ==============================================================================

PILLAR_COMPUTERS = {
    "sleep":         compute_sleep_raw,
    "movement":      compute_movement_raw,
    "nutrition":     compute_nutrition_raw,
    "metabolic":     compute_metabolic_raw,
    "mind":          compute_mind_raw,
    "relationships": compute_relationships_raw,
}


def compute_character_sheet(data, previous_day_state, raw_score_histories, config):
    """Compute the full character sheet for a single day."""
    compute_date = data.get("date", datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    experiment_start = config.get("experiment_start", "2026-04-01")
    try:
        _day_number = max(1, (datetime.strptime(compute_date, "%Y-%m-%d") - datetime.strptime(experiment_start, "%Y-%m-%d")).days + 1)
    except Exception:
        _day_number = None
    pillar_configs = config.get("pillars", {})

    # Step 1: Raw scores for 6 primary pillars
    pillar_raw_scores = {}
    pillar_details = {}
    for pillar_name, compute_fn in PILLAR_COMPUTERS.items():
        raw_score, details = compute_fn(data, config)
        pillar_raw_scores[pillar_name] = raw_score
        pillar_details[pillar_name] = details

    # Step 2: Consistency meta-pillar
    consistency_raw, consistency_details = compute_consistency_raw(data, config, pillar_raw_scores)
    pillar_raw_scores["consistency"] = consistency_raw
    pillar_details["consistency"] = consistency_details

    # Step 3: EMA level scores — per-pillar lambda [F-03]
    pillar_level_scores = {}
    for pillar_name in pillar_raw_scores:
        history = list(raw_score_histories.get(pillar_name, []))
        history.append(pillar_raw_scores[pillar_name])
        pillar_level_scores[pillar_name] = compute_ema_level_score(history, config, pillar_name)

    # Step 4: Cross-pillar effects — ALL modifiers multiplicative [F-05]
    active_effects, modifiers = compute_cross_pillar_effects(pillar_level_scores, config)
    adjusted_level_scores = {}
    for pillar_name, ls in pillar_level_scores.items():
        mod = modifiers.get(pillar_name, 0)
        if mod != 0:
            adjusted = ls * (1 + mod)
            adjusted_level_scores[pillar_name] = round(_clamp(adjusted), 1)
        else:
            adjusted_level_scores[pillar_name] = ls

    # Step 5: Level changes per pillar
    prev_pillars = {}
    if previous_day_state:
        for pn in pillar_raw_scores:
            pp = previous_day_state.get(f"pillar_{pn}") or {}
            prev_pillars[pn] = {
                "level": pp.get("level", 1), "tier": pp.get("tier", "Foundation"),
                "streak_above": pp.get("streak_above", 0),
                "streak_below": pp.get("streak_below", 0),
                "xp_total": pp.get("xp_total", 0),
            }

    all_events = []
    pillar_results = {}
    for pillar_name in pillar_raw_scores:
        prev_state = prev_pillars.get(pillar_name)
        level_state = evaluate_level_changes(
            pillar_name, adjusted_level_scores[pillar_name], prev_state, config)

        prev_xp = prev_state.get("xp_total", 0) if prev_state else 0
        xp_earned, xp_delta, new_xp = _compute_xp(pillar_raw_scores[pillar_name], prev_xp, config, day_number=_day_number)
        level_state["xp_total"] = new_xp

        pillar_results[pillar_name] = {
            "raw_score": pillar_raw_scores[pillar_name],
            "level_score": adjusted_level_scores[pillar_name],
            "level": level_state["level"], "tier": level_state["tier"],
            "tier_emoji": level_state.get("tier_emoji", "🔨"),
            "xp_total": level_state["xp_total"], "xp_delta": xp_delta,
            "xp_earned": xp_earned,
            "confidence": pillar_details[pillar_name].get("_confidence"),
            "data_coverage": pillar_details[pillar_name].get("_data_coverage"),
            "xp_buffer": level_state.get("xp_buffer", 0),
            "streak_above": level_state["streak_above"],
            "streak_below": level_state["streak_below"],
            "components": pillar_details[pillar_name],
        }
        # Annotate level events with "why" context for the event log
        for ev in level_state.get("events", []):
            ev["raw_score"] = round(pillar_raw_scores[pillar_name], 1)
            ev["level_score"] = round(adjusted_level_scores[pillar_name], 1)
            ev["xp_earned"] = xp_earned
            ev["streak_days"] = level_state.get("streak_above", 0) or level_state.get("streak_below", 0)
            # Extract top contributing component (skip private keys)
            components = {k: v for k, v in pillar_details[pillar_name].items()
                         if not k.startswith("_") and isinstance(v, (int, float)) and v > 0}
            if components:
                top = max(components, key=components.get)
                ev["top_driver"] = top.replace("_", " ").title()
                ev["top_driver_value"] = round(components[top], 1)
        all_events.extend(level_state.get("events", []))

    # Step 6: Overall Character Level — floor instead of round [F-14]
    weighted_level_sum = 0.0
    total_weight = 0.0
    for pillar_name, result in pillar_results.items():
        weight = pillar_configs.get(pillar_name, {}).get("weight", 1.0 / 7)
        weighted_level_sum += result["level"] * weight
        total_weight += weight

    character_level = max(1, min(100, int(math.floor(weighted_level_sum / total_weight)))) if total_weight > 0 else 1
    character_tier = get_tier(character_level, config)

    prev_char_level = previous_day_state.get("character_level", 1) if previous_day_state else 1
    if character_level > prev_char_level:
        all_events.append({"type": "character_level_up", "old_level": prev_char_level, "new_level": character_level})
    elif character_level < prev_char_level:
        all_events.append({"type": "character_level_down", "old_level": prev_char_level, "new_level": character_level})

    total_xp = sum(pr["xp_total"] for pr in pillar_results.values())

    # Confidence stats [F-01]
    confidences = [pr.get("confidence") for pr in pillar_results.values()
                   if pr.get("confidence") is not None]
    min_confidence = round(min(confidences), 3) if confidences else 0.0
    avg_confidence = round(sum(confidences) / len(confidences), 3) if confidences else 0.0

    record = {
        "date": compute_date,
        "character_level": character_level,
        "character_tier": character_tier["name"],
        "character_tier_emoji": character_tier.get("emoji", "🔨"),
        "character_xp": total_xp,
        "min_confidence": min_confidence,
        "avg_confidence": avg_confidence,
        "active_effects": active_effects,
        "level_events": all_events,
        "computed_at": datetime.now(timezone.utc).isoformat(),
        "engine_version": ENGINE_VERSION,
    }
    for pillar_name, result in pillar_results.items():
        record[f"pillar_{pillar_name}"] = result

    return record


# ==============================================================================
# DDB HELPERS
# ==============================================================================

def store_character_sheet(table_resource, user_prefix, record):
    """Write a character_sheet record to DynamoDB."""
    item = {"pk": user_prefix + "character_sheet", "sk": "DATE#" + record["date"]}
    item.update(_to_decimal(record))
    table_resource.put_item(Item=item)
    return item


def fetch_character_sheet(table_resource, user_prefix, date_str):
    try:
        resp = table_resource.get_item(
            Key={"pk": user_prefix + "character_sheet", "sk": "DATE#" + date_str})
        item = resp.get("Item")
        return _from_decimal(item) if item else None
    except Exception:
        return None


def fetch_character_sheet_range(table_resource, user_prefix, start_date, end_date):
    try:
        resp = table_resource.query(
            KeyConditionExpression="pk = :pk AND sk BETWEEN :start AND :end",
            ExpressionAttributeValues={
                ":pk": user_prefix + "character_sheet",
                ":start": "DATE#" + start_date, ":end": "DATE#" + end_date,
            },
        )
        items = resp.get("Items", [])
        while resp.get("LastEvaluatedKey"):
            resp = table_resource.query(
                KeyConditionExpression="pk = :pk AND sk BETWEEN :start AND :end",
                ExpressionAttributeValues={
                    ":pk": user_prefix + "character_sheet",
                    ":start": "DATE#" + start_date, ":end": "DATE#" + end_date,
                },
                ExclusiveStartKey=resp["LastEvaluatedKey"],
            )
            items.extend(resp.get("Items", []))
        return [_from_decimal(i) for i in items]
    except Exception as e:
        logger.error("[character_engine] Range query failed: %s", e)
        return []


def _to_decimal(obj):
    if isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            return None
        return Decimal(str(round(obj, 4)))
    if isinstance(obj, dict):
        return {k: _to_decimal(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_to_decimal(i) for i in obj]
    return obj


def _from_decimal(obj):
    from decimal import Decimal
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, dict):
        return {k: _from_decimal(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_from_decimal(i) for i in obj]
    return obj
