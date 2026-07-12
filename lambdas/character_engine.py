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
v1.2.0 — 2026-07-03  (ADR-104 believability: behavioral absence scores 0,
                      coverage gate on level changes, per-pillar drivers)
v1.3.0 — 2026-07-10  (#913 neglect honesty: up-gate compares raw to the TARGET
                      level (scale fix — level 8→13 climbed during a 14-day dark
                      stretch because raw 9 beat "current_level + 1"), presence-
                      driven atrophy on behavioral pillars, visible XP debt
                      instead of a silent 0-floor, deterministic character_mood)
"""

import json
import logging
import math
import time
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Optional

from constants import EXPERIMENT_BASELINE_WEIGHT_LBS, EXPERIMENT_START_DATE  # ADR-058

logger = logging.getLogger(__name__)

# ── In-memory cache (survives Lambda warm starts) ──
_config_cache = {"data": None, "ts": 0}
_CONFIG_TTL_S = 300  # 5 minutes

ENGINE_VERSION = "1.5.0"  # #956 math v2: XP zero-point at "a decent day", XP gated on instrumentation,
# modifiers/challenge XP are engine inputs, dark down-streaks persist, headline renormalized (ADR-134)

# ── ADR-104: coverage floor below which a day carries no leveling signal ──
DEFAULT_LEVEL_CHANGE_MIN_COVERAGE = 0.5

# ── XP defaults (also in config) [F-02] ──
DEFAULT_XP_PER_LEVEL = 100
DEFAULT_DAILY_XP_DECAY = 1  # #958/ADR-134: zero-point at "a decent day" (raw 40-59 nets 0, 60+ positive)
DEFAULT_XP_BUFFER_THRESHOLD = 20

# ── Tier definitions (also in config, but hardcoded as fallback) ──
_DEFAULT_TIERS = [
    {"name": "Foundation", "emoji": "🔨", "min_level": 1, "max_level": 20},
    {"name": "Momentum", "emoji": "🔥", "min_level": 21, "max_level": 40},
    {"name": "Discipline", "emoji": "⚔️", "min_level": 41, "max_level": 60},
    {"name": "Mastery", "emoji": "🏆", "min_level": 61, "max_level": 80},
    {"name": "Elite", "emoji": "👑", "min_level": 81, "max_level": 100},
]


# ==============================================================================
# CONFIG LOADER
# ==============================================================================


def load_character_config(
    s3_client: Any,
    bucket: str,
    force_refresh: bool = False,
    user_id: str = "matthew",
) -> dict[str, Any]:
    """Load character_sheet.json from S3 with warm-container caching."""
    now = time.time()
    if not force_refresh and _config_cache["data"] and (now - _config_cache["ts"]) < _CONFIG_TTL_S:
        return _config_cache["data"]
    try:
        resp = s3_client.get_object(Bucket=bucket, Key=f"config/{user_id}/character_sheet.json")
        config = json.loads(resp["Body"].read().decode("utf-8"))
        _config_cache["data"] = config
        _config_cache["ts"] = now
        logger.info("[character_engine] Loaded config from S3 — %d pillars", len(config.get("pillars", {})))
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
    """Clamp a numeric score to [lo, hi]; pass None through unchanged."""
    if val is None:
        return None
    return max(lo, min(hi, val))


def _safe_float(rec, field, default=None):
    """Return rec[field] coerced to float, or default if absent/non-numeric."""
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


def get_tier(level: int, config: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    """Get tier info for a given level."""
    tiers = (config or {}).get("tiers", _DEFAULT_TIERS)
    for tier in tiers:
        if tier["min_level"] <= level <= tier["max_level"]:
            return tier
    return tiers[-1] if level > 80 else tiers[0]


def _compute_xp(raw_score, previous_xp, config, day_number=None, previous_debt=0, bonus_xp=0):
    """Compute XP delta with daily decay.

    Returns (xp_earned, xp_delta, new_xp_total, new_xp_debt). [F-02, #913]
    C2: Grace period — decay scales linearly over first 14 days to avoid
    punishing new users before data stabilizes.

    #913 XP debt: the old ``max(0, ...)`` floor made sustained decay invisible —
    5 of 7 pillars sat at 0 XP and every further bad day looked identical. The
    signed balance is now split into xp_total (the positive part, so every
    downstream ``% xp_per_level`` consumer is untouched) and xp_debt (the hole
    dug below zero, capped at leveling.xp_debt_cap — default one level's worth —
    so a long dark stretch stays climbable). Good days pay debt down before XP
    grows again; the UI renders the debt as the visible bleed.

    #958 zero-point (ADR-134): with the config's daily_xp_decay of 1, XP breaks
    even on a 40-59 day and goes positive at 60+ — "a decent day" is the neutral
    point, not raw 80. The old decay of 2 made every realistic-good trajectory
    (slow improver, oscillator, post-dark recovery) bleed permanent debt while
    levels climbed — a 420-day simulated Mastery character wore a maxed debt
    badge forever. Debt is now a dark-stretch signal a recovery arc visibly
    repays, never a one-way ratchet.

    #961: ``bonus_xp`` (challenge completions) enters the signed balance like
    any other XP, so it pays existing debt before growing the total — it can
    never teleport past the paydown contract or perturb the demotion buffer
    behind the gates' backs the way the old post-engine ``xp_total +=`` did."""
    bands = config.get(
        "xp_bands",
        [
            {"min_raw_score": 80, "xp": 3},
            {"min_raw_score": 60, "xp": 2},
            {"min_raw_score": 40, "xp": 1},
            {"min_raw_score": 20, "xp": 0},
            {"min_raw_score": 0, "xp": -1},
        ],
    )
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

    xp_delta = earned - daily_decay + (bonus_xp or 0)
    # Signed balance: pay existing debt first, then grow XP; a shortfall deepens
    # the debt instead of vanishing under a silent 0-floor. [#913]
    debt_cap = leveling.get("xp_debt_cap", leveling.get("xp_per_level", DEFAULT_XP_PER_LEVEL))
    balance = (previous_xp or 0) - (previous_debt or 0) + xp_delta
    new_xp = max(0, balance)
    new_debt = min(debt_cap, max(0, -balance))

    return earned, xp_delta, new_xp, new_debt


def _roll_xp_buffer(prev_buffer, prev_xp, new_xp, xp_per_level, buffer_cap=None):
    """Roll the level-down XP buffer forward one day. [F-02, #954]

    The old buffer was ``xp_total % xp_per_level`` — a modulo that WRAPS UPWARD
    as XP declines: losing XP across a 100-boundary (205 → 199) re-armed
    near-maximum demotion immunity (buffer 5 → 99), so a crashed pillar with
    lucky lifetime XP fell 30→28 instead of 30→18 over 60 days. The buffer is
    now explicit state, monotone in the day's XP change: it FILLS by XP gained
    and DRAINS by XP lost, floored at 0 — a decline can only ever deplete it.
    ``prev_buffer=None`` (state stored before this fix, or the first day of a
    cycle) seeds from the legacy within-level remainder of the PREVIOUS total,
    the last honest reading before the wrap.

    #958/ADR-134 sizing: the fill caps at ``leveling.xp_buffer_cap`` (default
    one level's worth for legacy configs). With the v2 XP economy any sustained
    good stretch pins an uncapped buffer at 100, which — against the ≥20 gate
    and a −1..−2/day bleed — silently granted 40+ days of demotion immunity.
    The cap bounds the shield to the anti-flip-flop scale it was meant for
    (cap 40 ≈ 10–20 days), and a confirmed dark stretch bypasses the gate
    entirely (see evaluate_level_changes).
    """
    if xp_per_level <= 0:
        return 0
    cap = float(buffer_cap) if buffer_cap else float(xp_per_level)
    if prev_buffer is None:
        prev_buffer = min((prev_xp or 0) % xp_per_level, cap)
    return round(max(0.0, min(float(prev_buffer) + (float(new_xp) - float(prev_xp or 0)), cap)), 2)


# ==============================================================================
# PILLAR RAW SCORE COMPUTATIONS
# ==============================================================================


def compute_sleep_raw(data: dict[str, Any], config: dict[str, Any]) -> tuple[float, dict[str, Any]]:
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

    # Efficiency — v1.2.0: include the field names the Whoop v2 ingestion actually
    # writes (sleep_performance_percentage / sleep_efficiency_percentage). The old
    # names left this component permanently None → sleep stuck below the coverage
    # floor despite full data.
    eff = (
        _safe_float(sleep, "sleep_performance")
        or _safe_float(sleep, "sleep_performance_percentage")
        or _safe_float(sleep, "sleep_efficiency_pct")
        or _safe_float(sleep, "sleep_efficiency_percentage")
        or _safe_float(sleep, "sleep_quality_score")
    )
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
    if deep_pct is None:  # v1.2.0: Whoop v2 stores hours (slow-wave = deep)
        deep_h = _safe_float(sleep, "slow_wave_sleep_hours")
        total_h = _safe_float(sleep, "sleep_duration_hours")
        if deep_h and total_h and total_h > 0:
            deep_pct = deep_h / total_h
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
    if rem_pct is None:  # v1.2.0: Whoop v2 stores hours
        rem_h = _safe_float(sleep, "rem_sleep_hours")
        total_h = _safe_float(sleep, "sleep_duration_hours")
        if rem_h and total_h and total_h > 0:
            rem_pct = rem_h / total_h
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


def compute_movement_raw(data: dict[str, Any], config: dict[str, Any]) -> tuple[float, dict[str, Any]]:
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
        for act in day.get("activities") or []:
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
        for act in day.get("activities") or []:
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
    start = baseline.get("start_weight_lbs", EXPERIMENT_BASELINE_WEIGHT_LBS)
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


def compute_nutrition_raw(data: dict[str, Any], config: dict[str, Any]) -> tuple[float, dict[str, Any]]:
    """Compute Nutrition pillar raw_score (0-100)."""
    pillar_cfg = config.get("pillars", {}).get("nutrition", {})
    components = pillar_cfg.get("components", {})
    config.get("baseline", {})
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


def compute_metabolic_raw(data: dict[str, Any], config: dict[str, Any]) -> tuple[float, dict[str, Any]]:
    """Compute Metabolic Health pillar raw_score (0-100)."""
    pillar_cfg = config.get("pillars", {}).get("metabolic", {})
    components = pillar_cfg.get("components", {})
    scores = {}

    # Body fat trajectory: REMOVED (#486/B-3). The Withings scale is weight-only —
    # 0/1198 records ever carried body_fat_pct/fat_mass_pct, so the component
    # could never score and structurally capped metabolic coverage at 0.75.
    # Body composition lives in the sparse periodic `dexa` source, too infrequent
    # for a 30-day trend. The component is gone from character_sheet.json too.

    # CGM glucose control
    apple = data.get("apple") or {}
    tir = _safe_float(apple, "blood_glucose_time_in_range_pct")
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


def compute_mind_raw(data: dict[str, Any], config: dict[str, Any]) -> tuple[float, dict[str, Any]]:
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

    # State of Mind valence — HAE writes the daily aggregate as som_avg_valence
    # (-1..+1) on the apple_health record; legacy field names kept as a fallback.
    som = data.get("state_of_mind") or {}
    som_valence = _safe_float(som, "som_avg_valence")
    if som_valence is not None:
        # HealthKit valence is -1..+1 → map to 0..100.
        scores["state_of_mind_valence"] = _clamp(round((som_valence + 1) / 2 * 100, 1))
    else:
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
            scores["vice_control"] = _clamp(round(100 * math.log(1 + avg_streak) / math.log(31), 1))
        else:
            scores["vice_control"] = None
    else:
        scores["vice_control"] = None

    return _weighted_pillar_score(scores, components)


# Ordered rungs of the categorical `enriched_social_quality` field emitted by
# journal_enrichment_lambda. Rank spacing maps linearly onto the 0–10 scale.
_SOCIAL_QUALITY_RANK = {"alone": 0, "surface": 1, "meaningful": 2, "deep": 3}


def _social_quality_to_10(raw):
    """Map the categorical `enriched_social_quality`
    (`alone|surface|meaningful|deep`) onto the 0–10 scale
    `compute_relationships_raw` already handles for `social_score`.

    #910: `journal_enrichment_lambda` only ever writes the *categorical*
    `enriched_social_quality`; the numeric `social_connection_score` /
    `enriched_social_connection` fields the consumer reads are never produced by
    any code, so `social_score` was always None and both
    `social_interaction_frequency` (`social_score * 10`) and
    `social_mood_correlation` (gated on `social_score is not None`) stayed dead.

    The four ordered rungs are spread evenly across the 0–10 range by rank,
    `rank / 3 * 10`: alone→0, surface→3.33, meaningful→6.67, deep→10. The
    consumer's `social_interaction_frequency = social_score * 10` then lands them
    at the intuitive quartiles 0 / 33 / 67 / 100 %. Unknown / `null` / missing →
    None, preserving the falsy contract (a day with no recognizable social signal
    stays uninstrumented). The numeric fields remain the primary path; this is
    only the read-time fallback, mirroring #902's `enriched_mood`→`mood_avg`
    bridge. Returns None on unrecognized / non-string input.
    """
    if not isinstance(raw, str):
        return None
    rank = _SOCIAL_QUALITY_RANK.get(raw.strip().lower())
    if rank is None:
        return None
    return rank / 3 * 10


def compute_relationships_raw(data: dict[str, Any], config: dict[str, Any]) -> tuple[float, dict[str, Any]]:
    """Compute Relationships pillar raw_score (0-100)."""
    pillar_cfg = config.get("pillars", {}).get("relationships", {})
    components = pillar_cfg.get("components", {})
    scores = {}

    journal = data.get("journal") or {}
    entries = data.get("journal_entries") or []

    # Social interaction frequency.
    # Primary path: the numeric social_connection_score / enriched_social_connection
    # (future-proof — no producer writes them yet, first-found wins as before).
    # Fallback (#910): derive social_score from the categorical
    # enriched_social_quality the enrichment lambda actually emits, averaging the
    # mapped rungs across the day's entries (mirrors #902's mood_avg averaging).
    social_score = None
    quality_scores = []
    for entry in entries:
        sc = _safe_float(entry, "social_connection_score") or _safe_float(entry, "enriched_social_connection")
        if sc is not None:
            social_score = sc
            break
        mapped = _social_quality_to_10(entry.get("enriched_social_quality"))
        if mapped is not None:
            quality_scores.append(mapped)
    if social_score is None and quality_scores:
        social_score = sum(quality_scores) / len(quality_scores)
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

    # Buddy engagement: REMOVED (#962, B-3 precedent — same disease as the
    # body-fat component). No producer ever wrote buddy_freshness_days, so the
    # component could never score and structurally capped relationships
    # coverage at 0.85. Gone from character_sheet.json too; re-add via a real
    # producer + config entry if a buddy system ever ships.

    # Social mood correlation
    mood = _safe_float(journal, "mood_avg")
    if mood is not None and social_score is not None:
        scores["social_mood_correlation"] = _clamp(round((mood / 10) * 100, 1)) if mood <= 10 else _clamp(mood)
    else:
        scores["social_mood_correlation"] = None

    return _weighted_pillar_score(scores, components)


#  Primary pillars whose raw scores feed the derived consistency inputs (#962).
_STREAK_PILLARS = ("sleep", "movement", "nutrition", "metabolic", "mind")


def derive_consistency_inputs(dated_records: list[dict[str, Any]], as_of_date: str) -> dict[str, Any]:
    """#962: derive the two consistency inputs no producer ever set, from
    stored character_sheet records (each carrying ``date`` + ``pillar_*``).

    Returns {"streak_all_above_30th": int|None, "weekend_weekday_ratio": float|None}.

    - streak_all_above_30th — consecutive days ending the day before
      ``as_of_date`` where every instrumented primary pillar's raw_score held
      ≥ 30 (the "no pillar below 30" floor the consistency protocols coach).
      A missing day breaks the streak (a gap is not a floor held); pillars
      flagged not_instrumented that day are skipped, never counted against.
    - weekend_weekday_ratio — mean composite raw on weekend days / weekday
      days over the trailing 14 records; None below 2 weekend + 4 weekday
      days of data (no ratio from nothing, ADR-105).

    Pure function — the compute lambda calls it with the same 21-day record
    window it already fetches for EMA histories, so no extra reads.
    """
    by_date = {}
    for rec in dated_records or []:
        d = rec.get("date") or (rec.get("sk", "") or "").replace("DATE#", "")
        if d:
            by_date[d[:10]] = rec

    def _day_raws(rec):
        raws = []
        for p in _STREAK_PILLARS:
            pd = rec.get(f"pillar_{p}") or {}
            if pd.get("not_instrumented"):
                continue
            raw = pd.get("raw_score")
            if raw is not None:
                try:
                    raws.append(float(raw))
                except (TypeError, ValueError):
                    pass
        return raws

    try:
        as_of = datetime.strptime(as_of_date[:10], "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return {"streak_all_above_30th": None, "weekend_weekday_ratio": None}

    # ── streak: walk back day by day from yesterday; any gap or sub-30 day breaks ──
    streak = 0
    cursor = as_of - timedelta(days=1)
    while True:
        rec = by_date.get(cursor.isoformat())
        if not rec:
            break
        raws = _day_raws(rec)
        if not raws or min(raws) < 30:
            break
        streak += 1
        cursor -= timedelta(days=1)
        if streak >= 60:  # nothing downstream distinguishes past this; bound the walk
            break

    # ── weekend/weekday composite ratio over the trailing 14 days ──
    weekend, weekday = [], []
    for back in range(1, 15):
        d = as_of - timedelta(days=back)
        rec = by_date.get(d.isoformat())
        if not rec:
            continue
        raws = _day_raws(rec)
        if not raws:
            continue
        composite = sum(raws) / len(raws)
        (weekend if d.weekday() >= 5 else weekday).append(composite)

    ratio = None
    if len(weekend) >= 2 and len(weekday) >= 4:
        wk_mean = sum(weekday) / len(weekday)
        if wk_mean > 0:
            ratio = round((sum(weekend) / len(weekend)) / wk_mean, 3)

    return {"streak_all_above_30th": streak if streak > 0 else (0 if by_date else None), "weekend_weekday_ratio": ratio}


def compute_consistency_raw(
    data: dict[str, Any], config: dict[str, Any], other_pillar_raw_scores: dict[str, float]
) -> tuple[float, dict[str, Any]]:
    """Compute Consistency meta-pillar raw_score (0-100)."""
    pillar_cfg = config.get("pillars", {}).get("consistency", {})
    components = pillar_cfg.get("components", {})
    scores = {}

    # Cross-pillar variance
    other_scores = [v for k, v in other_pillar_raw_scores.items() if k != "consistency" and v is not None]
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
    """Weighted average with data completeness confidence penalty. [F-01]

    ADR-104: components flagged ``behavioral: true`` in config measure a
    behavior the owner either did or didn't do (logging, journaling, training).
    When such a component has no data, the behavior didn't happen — it scores
    0 at full weight instead of dropping out of the weight sum. Only *measured*
    components (device readings) revert toward neutral when absent; a device
    gap is not a failure, but an unlogged habit is.
    """
    weighted_sum = 0.0
    total_weight = 0.0
    max_possible_weight = 0.0
    details = {}
    absent_behaviors = []

    for comp_name, score in component_scores.items():
        comp_cfg = components_config.get(comp_name, {})
        weight = comp_cfg.get("weight", 0) if isinstance(comp_cfg, dict) else comp_cfg
        behavioral = comp_cfg.get("behavioral", False) if isinstance(comp_cfg, dict) else False
        max_possible_weight += weight
        if score is None and behavioral and weight > 0:
            score = 0.0
            absent_behaviors.append(comp_name)
            details[comp_name] = {"score": 0.0, "weight": weight, "absent": True}
        else:
            details[comp_name] = {"score": score, "weight": weight}
        if score is not None and weight > 0:
            weighted_sum += score * weight
            total_weight += weight

    details["_absent_behaviors"] = absent_behaviors

    if total_weight == 0:
        details["_confidence"] = 0.0
        details["_data_coverage"] = 0.0
        # #747: zero components had ANY value today — not a bad day for an
        # otherwise-instrumented pillar, but a literal absence of signal. The
        # 50.0 below is a mathematical placeholder (F-09's "true neutral"),
        # never a real reading; callers must not present it as one.
        details["_not_instrumented"] = True
        details["_raw_unblended"] = None  # #957: no measurement exists — nothing for the up-gate to credit
        return 50.0, details  # true neutral when no data [F-09]

    raw_score = weighted_sum / total_weight
    data_coverage = total_weight / max_possible_weight if max_possible_weight > 0 else 0
    confidence_threshold = 0.80  # full confidence at 80%+ data coverage
    confidence = min(1.0, data_coverage / confidence_threshold)

    # Blend toward neutral as confidence drops
    adjusted_score = raw_score * confidence + 50.0 * (1.0 - confidence)

    details["_confidence"] = round(confidence, 3)
    details["_data_coverage"] = round(data_coverage, 3)
    details["_not_instrumented"] = False
    # #957: what the day actually measured, BEFORE the confidence blend pulls
    # thin-data scores toward neutral 50. In total behavioral silence this is
    # exactly 0 (absent behaviors score 0, absent devices drop out) — the blend
    # is uncertainty smoothing for display/EMA, never performance, so it is the
    # unblended value the level-up gate must judge (evaluate_level_changes).
    details["_raw_unblended"] = round(_clamp(raw_score), 1)

    return round(_clamp(adjusted_score), 1), details


# ==============================================================================
# EMA + LEVEL COMPUTATION
# ==============================================================================


def compute_ema_level_score(raw_scores_history: list[float], config: dict[str, Any], pillar_name: Optional[str] = None) -> float:
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

    weights = [lam**i for i in range(len(recent))]
    weights.reverse()

    total = sum(r * w for r, w in zip(recent, weights))
    total_w = sum(weights)
    return round(total / total_w, 1) if total_w > 0 else 50.0


def _behavioral_weight_share(pillar_cfg: dict[str, Any]) -> float:
    """Fraction of a pillar's component weight that is flagged ``behavioral``.

    #913: neglect atrophy only applies to pillars that are substantially made of
    behaviors Matthew either does or doesn't do — sleep/metabolic keep their
    device-measured semantics (a wearable gap is not detraining).
    """
    components = (pillar_cfg or {}).get("components", {})
    total = 0.0
    behavioral = 0.0
    for cfg in components.values():
        if not isinstance(cfg, dict):
            continue
        w = cfg.get("weight", 0) or 0
        total += w
        if cfg.get("behavioral"):
            behavioral += w
    return behavioral / total if total > 0 else 0.0


def neglect_decay_state(engagement: Optional[dict[str, Any]], config: dict[str, Any]) -> Optional[dict[str, Any]]:
    """#913: derive the day's atrophy multiplier from the presence signal.

    Returns None when no decay applies (engaged / short gap / planned pause /
    no presence record), else {"multiplier", "gap_days", "n_grace_days", "rate"}.

    ADR-104 framing: this models real detraining and evidence loss — after a
    sustained dark stretch the platform genuinely knows less and the body
    genuinely detrains — never punishment. Knobs live in config
    leveling.neglect_decay: n_grace_days (dark days before decay starts), rate
    (per-day multiplier), floor (absolute level_score floor; the day's own
    raw_score is always a floor too), min_behavioral_share (which pillars
    qualify). A planned pause (sick/travel per engagement_core) never decays.
    """
    if not engagement:
        return None
    nd = (config.get("leveling", {}) or {}).get("neglect_decay", {}) or {}
    n_grace = nd.get("n_grace_days", 3)
    rate = nd.get("rate", 0.98)
    if engagement.get("presence_class") != "dark" or engagement.get("planned_pause"):
        return None
    gap = engagement.get("gap_days")
    try:
        gap = float(gap)
    except (TypeError, ValueError):
        return None
    if gap <= n_grace:
        return None
    multiplier = rate ** (gap - n_grace)
    return {
        "multiplier": round(multiplier, 4),
        "gap_days": gap,
        "n_grace_days": n_grace,
        "rate": rate,
    }


# #913: the four deterministic character moods, worst-first for readability.
CHARACTER_MOODS = ("dormant", "fading", "steady", "thriving")


def compute_character_mood(
    engagement: Optional[dict[str, Any]],
    pillar_raw_scores: dict[str, float],
    raw_score_histories: dict[str, list[float]],
) -> dict[str, Any]:
    """#913: one deterministic mood — thriving / steady / fading / dormant.

    Pure code, no LLM (ADR-105): f(presence gap, 7d composite raw-score trend,
    presence_class). Returns {"mood", "inputs"} where inputs carries the exact
    numbers the verdict came from.

    Rules, first match wins:
      dormant  — presence_class == "dark" (a real multi-day logging fall-off)
      fading   — presence_class == "quiet", OR the 7d composite raw trend
                 (mean of last 3 days minus mean of the 4 before) <= -5
      thriving — actively logging (present/light), trend >= +3, composite >= 55
      steady   — everything else
    """
    presence_class = (engagement or {}).get("presence_class") or "present"
    gap_days = (engagement or {}).get("gap_days")

    # 7d composite raw series: day-wise mean across pillars of the trailing
    # histories (each history already ends with today's raw score when called
    # from compute_character_sheet).
    series = []
    histories = [h for h in (raw_score_histories or {}).values() if h]
    if histories:
        depth = min(7, min(len(h) for h in histories))
        for i in range(-depth, 0):
            vals = [h[i] for h in histories if h[i] is not None]
            if vals:
                series.append(sum(vals) / len(vals))
    trend = None
    if len(series) >= 5:
        recent = series[-3:]
        prior = series[:-3]
        trend = round(sum(recent) / len(recent) - sum(prior) / len(prior), 1)
    composite = None
    scores = [v for v in (pillar_raw_scores or {}).values() if v is not None]
    if scores:
        composite = round(sum(scores) / len(scores), 1)

    if presence_class == "dark":
        mood = "dormant"
    elif presence_class == "quiet" or (trend is not None and trend <= -5):
        mood = "fading"
    elif presence_class in ("present", "light") and trend is not None and trend >= 3 and composite is not None and composite >= 55:
        mood = "thriving"
    else:
        mood = "steady"

    return {
        "mood": mood,
        "inputs": {
            "presence_class": presence_class,
            "gap_days": gap_days,
            "trend_7d": trend,
            "composite_raw": composite,
        },
    }


def _level_step(delta: float, leveling: dict[str, Any]) -> int:
    """Step size for a level move given the gap between target and current.

    ADR-104: graduated bands (config leveling.level_step_bands) let a pillar
    with a large honest gap converge faster than the old fixed 1/2 step —
    post-reset, levels should differentiate by performance, not march in
    lockstep at one shared pace. Falls back to the v1.1 threshold rule.
    """
    bands = leveling.get("level_step_bands")
    if bands:
        for band in sorted(bands, key=lambda b: -b.get("min_delta", 0)):
            if delta > band.get("min_delta", 0):
                return int(band.get("step", 1))
        return 1
    return 2 if delta > leveling.get("level_step_threshold", 10) else 1


def evaluate_level_changes(
    pillar_name: str,
    current_level_score: float,
    previous_state: dict[str, Any],
    config: dict[str, Any],
    data_coverage: Optional[float] = None,
    raw_score: Optional[float] = None,
    unadjusted_level_score: Optional[float] = None,
    raw_score_unblended: Optional[float] = None,
    presence_dark: bool = False,
) -> dict[str, Any]:
    """Level changes with progressive difficulty by tier. [F-15, F-10, F-11, F-02]

    ADR-104 believability rules:
    - a day whose data_coverage is below leveling.level_change_min_coverage
      carries no leveling signal — both streaks hold and no level moves in
      either direction (the confidence blend pulls thin-data scores toward
      neutral 50, which must never be climbable; nor should a pillar crash
      on no information).
    - a level-up additionally requires the day's own raw_score to be at the
      TARGET level: the EMA decides the target, but you climb only on days you
      actually performed at it. This stops a pillar from continuing to level up
      on EMA momentum after the behavior stopped.

      #913 scale fix: the gate used to be ``raw_score >= current_level + 1`` —
      a 0-100 daily score compared against a 1-100 level that is still
      CONVERGING from 1. Early in a cycle the level is small (say 8) purely
      because streak gates are slow, so a crashed raw score of 9 still "beat"
      it and the character climbed 8→13 through 14 days of total logging
      silence. Levels and scores share the 0-100 scale by construction
      (``target_level = round(level_score)``), so the like-for-like rule is
      against the target itself: today's raw performance must be at least the
      score the EMA says the pillar deserves. Strictly tighter than the old
      gate whenever target > current + 1, never looser; a below-target day
      HOLDS the up-streak (it doesn't reset it), so honest climbs still land.

      #954 boost fix: ``current_level_score`` arrives AFTER cross-pillar
      modifiers (F-05), so a standing positive boost (Alignment + Synergy +
      Training Boost = x1.16) pushed the raw-day gate above any achievable
      raw score and froze the boosted pillar forever (steady raw 76 vs a
      boosted target of 89 — day_supports_up never True). The #913 rationale
      is like-for-like — today's RAW performance vs what the EMA of RAW
      scores says the pillar deserves — so callers pass the pre-modifier EMA
      as ``unadjusted_level_score`` and the raw-day gate compares against
      ``min(boosted target, unboosted target)``: boosts still raise the level
      the pillar converges TO, but never demand a raw day nobody can live.
      (min, not the unboosted value outright, so a NEGATIVE modifier keeps
      the previous, looser behavior — the gate never exceeds the target the
      pillar is actually climbing toward.) When the caller doesn't pass it
      (legacy paths), the gate falls back to the boosted target unchanged.

      #957 blend fix: ``raw_score`` arrives AFTER the confidence blend
      (_weighted_pillar_score pulls thin-coverage scores toward neutral 50),
      so total behavioral silence still produced a positive "raw" floor
      (~15.6 for movement: 0 performance at coverage 0.55). Atrophy pins the
      level score at that same blended floor, the EMA converges down to it,
      and after ~15-17 dark days ``round(15.6) >= target 16`` self-satisfied
      every day — a character that never logs anything climbed with level_up
      celebrations while mood read dormant. ADR-104 model decision: a day
      with no behavioral data can never support a level-up, at any horizon.
      Callers therefore pass ``raw_score_unblended`` — the day's measured
      performance BEFORE the blend (weighted_sum/total_weight; exactly 0 in
      silence) — and the up-gate judges THAT. The blend keeps smoothing the
      EMA/display path; it just isn't performance, so it can't buy a climb.
      Legacy callers that don't pass it fall back to the blended raw.

      #959 dark persistence (ADR-134): the fresh-streak-per-drop cadence
      (streak_below resets to 0 after every level_down) is anti-flip-flop
      machinery for NOISY ENGAGED data — it exists so one bad week can't
      saw-tooth a level. A confirmed multi-day dark stretch is not noise; it
      is a provable sustained absence, and re-demanding a fresh 7-day streak
      between each single drop let a silent month cost the headline only ~2
      levels (the cycle-4 failure mode). When the caller passes
      ``presence_dark=True`` (atrophy-qualifying pillar, presence_class=dark
      past grace, never a planned pause) the down-streak PERSISTS across
      drops, so the level keeps stepping down toward the crashed target day
      by day. Config kill-switch: leveling.neglect_decay.persistent_down_streak.
    """
    leveling = config.get("leveling", {})

    # Progressive streak overrides by tier [F-15]
    tier_overrides = leveling.get("tier_streak_overrides", {})

    prev = previous_state or {"level": 1, "tier": "Foundation", "streak_above": 0, "streak_below": 0, "xp_total": 0}
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

    # XP buffer gate for level-down [F-02]
    # #954: the buffer is explicit state (see _roll_xp_buffer) — trusted from
    # previous_state when present so an XP decline can never re-arm it via the
    # old % wrap; the modulo remains only as the seed for legacy stored state.
    xp_per_level = leveling.get("xp_per_level", DEFAULT_XP_PER_LEVEL)
    xp_buffer_threshold = leveling.get("xp_buffer_threshold", DEFAULT_XP_BUFFER_THRESHOLD)
    xp_buffer = prev.get("xp_buffer")
    if xp_buffer is None:
        xp_buffer = xp_total % xp_per_level if xp_per_level > 0 else 0

    target_level = max(1, min(100, round(current_level_score)))
    events = []

    # ADR-104: no-signal day — insufficient coverage to judge either direction
    min_coverage = leveling.get("level_change_min_coverage", DEFAULT_LEVEL_CHANGE_MIN_COVERAGE)
    coverage_hold = data_coverage is not None and data_coverage < min_coverage

    # ADR-104/#913: the EMA sets the target, but climbing also requires the day
    # itself to have performed AT the target — no up-credit on EMA momentum, and
    # never a comparison against the still-converging (small) current level.
    # round() on both sides: target_level is round(level_score), so the raw
    # side gets the same treatment (raw 86.9 must not lose to its own EMA's 87).
    # #954: the raw-day gate compares against the UNboosted EMA when the caller
    # provides it — cross-pillar boosts raise the target, never the daily bar.
    raw_gate_target = target_level
    if unadjusted_level_score is not None:
        raw_gate_target = min(target_level, max(1, min(100, round(unadjusted_level_score))))
    # #957: judge the day on what it MEASURED, not on the confidence-blended
    # score — in total silence the unblended raw is 0, so no dark day can ever
    # satisfy the up-gate (the blended floor ~15.6 could, once EMA converged).
    gate_raw = raw_score if raw_score_unblended is None else raw_score_unblended
    day_supports_up = gate_raw is None or round(gate_raw) >= raw_gate_target

    if coverage_hold:
        pass  # hold both streaks; levels frozen until real data returns
    elif target_level > current_level and not day_supports_up:
        pass  # target above, but today wasn't lived at that level — hold [ADR-104]
    elif target_level > current_level:
        streak_above += 1
        streak_below = 0
        if streak_above >= up_streak_needed:
            delta = target_level - current_level
            step = _level_step(delta, leveling)
            old_tier = get_tier(current_level, config)["name"]
            new_tier = get_tier(min(current_level + step, 100), config)["name"]
            would_cross_tier = old_tier != new_tier

            if would_cross_tier and streak_above < tier_up_streak_needed:
                pass  # Hold — need longer streak for tier transition
            else:
                old_level = current_level
                current_level = min(current_level + step, 100)
                streak_above = 0
                events.append(
                    {
                        "type": "level_up",
                        "pillar": pillar_name,
                        "old_level": old_level,
                        "new_level": current_level,
                    }
                )
    elif target_level < current_level:
        streak_below += 1
        streak_above = 0
        if streak_below >= down_streak_needed:
            # XP buffer gate: can't lose a level until XP buffer is depleted.
            # #959: a confirmed dark stretch bypasses the buffer — banked XP
            # is flip-flop insurance for noisy engaged data, never a shield
            # against a provable sustained absence (ADR-134).
            if xp_buffer >= xp_buffer_threshold and not presence_dark:
                pass  # Buffer absorbs the pressure — hold level
            else:
                delta = current_level - target_level
                step = _level_step(delta, leveling)
                old_tier = get_tier(current_level, config)["name"]
                new_tier = get_tier(max(current_level - step, 1), config)["name"]
                would_cross_tier = old_tier != new_tier

                if would_cross_tier and streak_below < tier_down_streak_needed:
                    pass  # Hold — need longer streak for tier demotion
                else:
                    old_level = current_level
                    current_level = max(current_level - step, 1)
                    # #959: in a confirmed dark stretch the streak persists —
                    # a provable absence is not noise, so the anti-flip-flop
                    # reset must not throttle the honest fall (ADR-134).
                    if not presence_dark:
                        streak_below = 0
                    events.append(
                        {
                            "type": "level_down",
                            "pillar": pillar_name,
                            "old_level": old_level,
                            "new_level": current_level,
                        }
                    )
    else:
        # Equal day: hold streaks constant [F-11]
        pass

    # Check tier transitions
    new_tier_info = get_tier(current_level, config)
    new_tier = new_tier_info["name"]
    current_tier = prev.get("tier", "Foundation")
    if new_tier != current_tier:
        etype = "tier_up" if current_level > prev.get("level", 1) else "tier_down"
        events.append(
            {
                "type": etype,
                "pillar": pillar_name,
                "old_tier": current_tier,
                "new_tier": new_tier,
                "old_level": prev.get("level", 1),
                "new_level": current_level,
            }
        )
        current_tier = new_tier

    return {
        "level": current_level,
        "tier": current_tier,
        "tier_emoji": new_tier_info.get("emoji", "🔨"),
        "streak_above": streak_above,
        "streak_below": streak_below,
        "xp_total": xp_total,
        "xp_buffer": xp_buffer,
        "coverage_hold": coverage_hold,
        "events": events,
    }


def pillar_drivers(details: dict[str, Any], top_n: int = 2) -> dict[str, list[str]]:
    """ADR-104: derive a provenance summary from a pillar's component details.

    Returns {"top": [...], "dragging": [...], "absent": [...], "no_data": [...]}
    — the components lifting the pillar, the scored-but-weak ones pulling it
    down, the behaviors that didn't happen, and the measurements with no data.
    Pure function of the details dict; every value is computed, never narrated.
    """
    scored = {}
    no_data = []
    absent = list(details.get("_absent_behaviors", []))
    for name, d in details.items():
        if name.startswith("_") or not isinstance(d, dict):
            continue
        weight = d.get("weight") or 0
        if weight <= 0:
            continue
        if d.get("absent"):
            continue  # already in absent_behaviors
        score = d.get("score")
        if score is None:
            no_data.append(name)
        else:
            scored[name] = (float(score), float(weight))

    by_contribution = sorted(scored.items(), key=lambda kv: kv[1][0] * kv[1][1], reverse=True)
    top = [n for n, (s, _w) in by_contribution if s >= 60][:top_n]
    dragging = [n for n, (s, _w) in sorted(scored.items(), key=lambda kv: kv[1][0]) if s < 40][:top_n]
    return {"top": top, "dragging": dragging, "absent": absent, "no_data": no_data}


# ==============================================================================
# CROSS-PILLAR EFFECTS
# ==============================================================================


def compute_cross_pillar_effects(
    pillar_levels: dict[str, float], config: dict[str, Any], vice_streaks: Optional[dict[str, Any]] = None
) -> dict[str, Any]:
    """Evaluate cross-pillar effects. Returns (active_effects, modifier_dict). [F-05]

    ADR-134 (#963, decided): conditions evaluate EMA level_SCORES, not earned
    levels — deliberately. Effects model current-state physiology synergies
    (poor sleep drags today's training capacity), not tier achievements; gating
    them on the slow-converging earned level would fire Sleep Drag on every
    fresh-cycle character regardless of how they actually slept. The config
    narrative is worded to match (thresholds are score thresholds).

    #962: ``vice_streaks`` (the day's {vice: streak_days} dict from
    habit_scores) makes ``any_vice_streak`` conditions data-driven — they were
    hardcoded always-False while the config advertised a Vice Shield effect.
    """
    effects_config = config.get("cross_pillar_effects", [])
    active = []
    modifiers = {}

    for effect in effects_config:
        condition = effect.get("condition", "")
        targets = effect.get("targets", {})

        if _evaluate_condition(condition, pillar_levels, vice_streaks=vice_streaks):
            active.append(
                {
                    "name": effect["name"],
                    "emoji": effect.get("emoji", ""),
                    "condition": condition,
                    "targets": targets,
                }
            )
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


def _evaluate_condition(condition_str, pillar_levels, vice_streaks=None):
    """Evaluate a cross-pillar effect condition against current pillar scores.

    Supports "all_pillars <op> <val>", a single "<pillar> <op> <val>" comparison,
    "any_vice_streak <op> <val>" (against the day's vice_streaks dict, #962),
    and " AND "-joined conjunctions. Returns True if the condition holds.
    """
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
        # #962: was hardcoded False ("handled via data" — nothing handled it).
        # any_vice_streak <op> <val> holds when ANY tracked vice streak does.
        parts = condition_str.split()
        if len(parts) >= 3 and parts[0] == "any_vice_streak" and vice_streaks:
            try:
                op, val = parts[1], float(parts[2])
                streaks = [float(v) for v in vice_streaks.values() if isinstance(v, (int, float))]
                return any(_compare(s, op, val) for s in streaks)
            except (ValueError, TypeError):
                return False
        return False

    if " AND " in condition_str:
        return all(_evaluate_condition(sc.strip(), pillar_levels, vice_streaks=vice_streaks) for sc in condition_str.split(" AND "))

    parts = condition_str.split()
    if len(parts) >= 3:
        pillar, op, val = parts[0].strip(), parts[1].strip(), float(parts[2])
        level = pillar_levels.get(pillar)
        return _compare(level, op, val) if level is not None else False
    return False


def _compare(a, op, b):
    """Apply a comparison operator given as a string (<, <=, >, >=, ==, !=)."""
    if op == "<":
        return a < b
    if op == "<=":
        return a <= b
    if op == ">":
        return a > b
    if op == ">=":
        return a >= b
    if op == "==":
        return a == b
    if op == "!=":
        return a != b
    return False


# ==============================================================================
# MAIN ORCHESTRATOR
# ==============================================================================

PILLAR_COMPUTERS = {
    "sleep": compute_sleep_raw,
    "movement": compute_movement_raw,
    "nutrition": compute_nutrition_raw,
    "metabolic": compute_metabolic_raw,
    "mind": compute_mind_raw,
    "relationships": compute_relationships_raw,
}


def compute_character_sheet(
    data: dict[str, Any], previous_day_state: Optional[dict[str, Any]], raw_score_histories: dict[str, list[float]], config: dict[str, Any]
) -> dict[str, Any]:
    """Compute the full character sheet for a single day."""
    compute_date = data.get("date", datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    experiment_start = config.get("experiment_start", EXPERIMENT_START_DATE)
    try:
        _day_number = max(1, (datetime.strptime(compute_date, "%Y-%m-%d") - datetime.strptime(experiment_start, "%Y-%m-%d")).days + 1)
    except Exception:
        _day_number = None
    pillar_configs = config.get("pillars", {})

    # #747: a pillar's config may carry an explanatory note for the day it has
    # zero data — e.g. Relationships has no wired data source at all today, so
    # `_not_instrumented` is True on every compute. The note is attached here
    # (not baked into the front end) so it clears itself automatically the day
    # a real source starts filling the pillar's components (`_not_instrumented`
    # goes False and the note is simply never attached).
    def _attach_not_instrumented_note(pillar_name, details):
        if details.get("_not_instrumented"):
            details["_not_instrumented_note"] = pillar_configs.get(pillar_name, {}).get("not_instrumented_note")

    # Step 1: Raw scores for 6 primary pillars
    # #961 (ADR-134): behavioral modifiers (e.g. the food-delivery penalty/bonus)
    # arrive as ENGINE INPUTS via data["raw_score_modifiers"] =
    # {pillar: {"multiplier": m, "source": "..."}} and apply HERE, before the
    # EMA, XP bands, up-gate, and drivers — so the stored raw_score is exactly
    # the number the engine scored, with provenance. The old post-engine
    # overwrite mutated the stored value after every gate had judged the
    # unmodified one and leaked silently into the next day's EMA history.
    raw_modifiers = data.get("raw_score_modifiers") or {}
    pillar_raw_scores = {}
    pillar_details = {}
    for pillar_name, compute_fn in PILLAR_COMPUTERS.items():
        raw_score, details = compute_fn(data, config)
        mod = raw_modifiers.get(pillar_name)
        if mod and raw_score is not None:
            try:
                mult = float(mod.get("multiplier", 1.0))
            except (TypeError, ValueError):
                mult = 1.0
            if mult != 1.0:
                details["_modifier"] = {
                    "source": mod.get("source"),
                    "multiplier": mult,
                    "pre_modifier_raw": raw_score,
                }
                raw_score = round(_clamp(raw_score * mult), 1)
                if details.get("_raw_unblended") is not None:
                    # The gate judges the modified performance too — a delivery
                    # day IS the behavior being scored, not measurement noise.
                    details["_raw_unblended"] = round(_clamp(details["_raw_unblended"] * mult), 1)
        pillar_raw_scores[pillar_name] = raw_score
        pillar_details[pillar_name] = details
        _attach_not_instrumented_note(pillar_name, details)

    # Step 2: Consistency meta-pillar
    consistency_raw, consistency_details = compute_consistency_raw(data, config, pillar_raw_scores)
    pillar_raw_scores["consistency"] = consistency_raw
    pillar_details["consistency"] = consistency_details
    _attach_not_instrumented_note("consistency", consistency_details)

    # Step 3: EMA level scores — per-pillar lambda [F-03]
    pillar_level_scores = {}
    histories_with_today = {}
    for pillar_name in pillar_raw_scores:
        history = list(raw_score_histories.get(pillar_name, []))
        history.append(pillar_raw_scores[pillar_name])
        histories_with_today[pillar_name] = history
        pillar_level_scores[pillar_name] = compute_ema_level_score(history, config, pillar_name)

    # Step 4: Cross-pillar effects — ALL modifiers multiplicative [F-05]
    # #962: vice_streaks (lifted from habit_scores by the caller) makes the
    # any_vice_streak conditions data-driven instead of hardcoded-False.
    active_effects, modifiers = compute_cross_pillar_effects(pillar_level_scores, config, vice_streaks=data.get("vice_streaks"))
    adjusted_level_scores = {}
    for pillar_name, ls in pillar_level_scores.items():
        mod = modifiers.get(pillar_name, 0)
        if mod != 0:
            adjusted = ls * (1 + mod)
            adjusted_level_scores[pillar_name] = round(_clamp(adjusted), 1)
        else:
            adjusted_level_scores[pillar_name] = ls

    # Step 4.5 (#913): neglect atrophy — a sustained dark stretch (presence
    # signal from adaptive_mode's engagement_state, passed in via
    # data["engagement_state"]) drags behavioral-heavy pillars' level scores
    # DOWN, floored at the day's own raw score (the decay can never say less
    # than the day itself measured) and at the configured absolute floor.
    # Models real detraining + evidence loss (ADR-104), never punishment.
    engagement = data.get("engagement_state")
    decay = neglect_decay_state(engagement, config)
    neglect_cfg = (config.get("leveling", {}) or {}).get("neglect_decay", {}) or {}
    min_share = neglect_cfg.get("min_behavioral_share", 0.3)
    abs_floor = neglect_cfg.get("floor", 0)
    pillar_neglect = {}
    # #959 (ADR-134): pillars whose down-streak persists across drops today —
    # the same atrophy-qualifying set (dark past grace, behavioral-heavy,
    # never a planned pause), behind the persistent_down_streak config switch.
    dark_persist_pillars = set()
    if decay:
        persist_enabled = bool(neglect_cfg.get("persistent_down_streak", False))
        for pillar_name, ls in adjusted_level_scores.items():
            share = _behavioral_weight_share(pillar_configs.get(pillar_name, {}))
            if share < min_share:
                continue
            if persist_enabled:
                dark_persist_pillars.add(pillar_name)
            raw = pillar_raw_scores.get(pillar_name)
            floor = max(abs_floor, raw if raw is not None else 0)
            decayed = max(floor, ls * decay["multiplier"])
            if decayed < ls:
                adjusted_level_scores[pillar_name] = round(decayed, 1)
                pillar_neglect[pillar_name] = dict(decay, applied=True, behavioral_share=round(share, 3))

    # Step 5: Level changes per pillar
    prev_pillars = {}
    if previous_day_state:
        for pn in pillar_raw_scores:
            pp = previous_day_state.get(f"pillar_{pn}") or {}
            prev_pillars[pn] = {
                "level": pp.get("level", 1),
                "tier": pp.get("tier", "Foundation"),
                "streak_above": pp.get("streak_above", 0),
                "streak_below": pp.get("streak_below", 0),
                "xp_total": pp.get("xp_total", 0),
                "xp_debt": pp.get("xp_debt", 0),  # #913: the visible bleed carries over
                "xp_buffer": pp.get("xp_buffer"),  # #954: explicit buffer state (None = legacy, seeds from % remainder)
            }

    # #961: challenge bonus XP arrives as an engine input ({pillar: xp}) and
    # flows through _compute_xp's signed balance — debt pays down first.
    challenge_bonus = data.get("challenge_bonus_xp") or {}

    all_events = []
    pillar_results = {}
    for pillar_name in pillar_raw_scores:
        prev_state = prev_pillars.get(pillar_name)
        level_state = evaluate_level_changes(
            pillar_name,
            adjusted_level_scores[pillar_name],
            prev_state,
            config,
            data_coverage=pillar_details[pillar_name].get("_data_coverage"),
            raw_score=pillar_raw_scores[pillar_name],
            # #954: the raw-day up-gate compares against the pre-modifier EMA —
            # cross-pillar boosts raise the target, never the daily bar.
            unadjusted_level_score=pillar_level_scores[pillar_name],
            # #957: the up-gate judges the day's UNBLENDED raw (0 in silence) —
            # the confidence blend smooths uncertainty, it never buys a climb.
            raw_score_unblended=pillar_details[pillar_name].get("_raw_unblended"),
            # #959: a confirmed dark stretch keeps the down-streak armed.
            presence_dark=pillar_name in dark_persist_pillars,
        )

        prev_xp = prev_state.get("xp_total", 0) if prev_state else 0
        prev_debt = prev_state.get("xp_debt", 0) if prev_state else 0
        bonus_xp = challenge_bonus.get(pillar_name, 0) or 0
        # #964 (ADR-134): XP mirrors the level gate — a day with no signal for
        # this pillar (coverage below the floor, or not instrumented at all)
        # carries no XP judgment in either direction. The uninstrumented
        # relationships pillar used to feed its 50.0 placeholder into the
        # bands as "a mediocre day" and bleed a permanent phantom −100 debt,
        # contradicting ADR-104's "a device gap is not a failure".
        xp_hold = bool(level_state.get("coverage_hold")) or bool(pillar_details[pillar_name].get("_not_instrumented"))
        if xp_hold:
            xp_earned, xp_delta = 0, 0
            new_xp, new_debt = prev_xp, prev_debt
            if bonus_xp:  # a completed challenge still credits, debt-first
                balance = prev_xp - prev_debt + bonus_xp
                new_xp, new_debt = max(0, balance), max(0, -balance)
                xp_delta = bonus_xp
        else:
            xp_earned, xp_delta, new_xp, new_debt = _compute_xp(
                pillar_raw_scores[pillar_name], prev_xp, config, day_number=_day_number, previous_debt=prev_debt, bonus_xp=bonus_xp
            )
        level_state["xp_total"] = new_xp
        # #954: roll the demotion buffer forward with today's XP change — fills
        # on gain, drains on loss, never the wrap-prone % of lifetime XP.
        _leveling_cfg = config.get("leveling", {}) or {}
        xp_per_level_cfg = _leveling_cfg.get("xp_per_level", DEFAULT_XP_PER_LEVEL)
        level_state["xp_buffer"] = _roll_xp_buffer(
            prev_state.get("xp_buffer") if prev_state else None,
            prev_xp,
            new_xp,
            xp_per_level_cfg,
            buffer_cap=_leveling_cfg.get("xp_buffer_cap"),
        )

        pillar_results[pillar_name] = {
            "raw_score": pillar_raw_scores[pillar_name],
            "level_score": adjusted_level_scores[pillar_name],
            "level": level_state["level"],
            "tier": level_state["tier"],
            "tier_emoji": level_state.get("tier_emoji", "🔨"),
            "xp_total": level_state["xp_total"],
            "xp_delta": xp_delta,
            "xp_earned": xp_earned,
            # #961: engine-input provenance — the modifier that scaled today's
            # raw_score (None when none applied) and any challenge bonus XP.
            "raw_modifier": pillar_details[pillar_name].get("_modifier"),
            "challenge_bonus_xp": bonus_xp,
            # #913: the visible bleed — XP owed below the 0-floor, paid down
            # before xp_total grows again. 0 on healthy days.
            "xp_debt": new_debt,
            # #913: presence-driven atrophy applied to this pillar today (None
            # when engaged / planned pause / not a behavioral-heavy pillar).
            "neglect_decay": pillar_neglect.get(pillar_name),
            "confidence": pillar_details[pillar_name].get("_confidence"),
            "data_coverage": pillar_details[pillar_name].get("_data_coverage"),
            # #747: deterministic, engine-computed — True only when every
            # weighted component had zero data today (never an LLM verdict,
            # ADR-105). Auto-clears the day any component gets a real value.
            "not_instrumented": bool(pillar_details[pillar_name].get("_not_instrumented", False)),
            "not_instrumented_note": pillar_details[pillar_name].get("_not_instrumented_note"),
            "xp_buffer": level_state.get("xp_buffer", 0),
            "streak_above": level_state["streak_above"],
            "streak_below": level_state["streak_below"],
            "coverage_hold": level_state.get("coverage_hold", False),
            "absent_behaviors": pillar_details[pillar_name].get("_absent_behaviors", []),
            "drivers": pillar_drivers(pillar_details[pillar_name]),
            "components": pillar_details[pillar_name],
        }
        # Annotate level events with "why" context for the event log
        for ev in level_state.get("events", []):
            ev["raw_score"] = round(pillar_raw_scores[pillar_name], 1)
            ev["level_score"] = round(adjusted_level_scores[pillar_name], 1)
            ev["xp_earned"] = xp_earned
            ev["streak_days"] = level_state.get("streak_above", 0) or level_state.get("streak_below", 0)
            # Extract top contributing component (skip private keys).
            # v1.2.0: detail values are {"score", "weight"} dicts — read the score
            # (the old isinstance(v, (int, float)) filter matched nothing).
            components = {
                k: v.get("score")
                for k, v in pillar_details[pillar_name].items()
                if not k.startswith("_") and isinstance(v, dict) and isinstance(v.get("score"), (int, float)) and v.get("score") > 0
            }
            if components:
                top = max(components, key=components.get)
                ev["top_driver"] = top.replace("_", " ").title()
                ev["top_driver_value"] = round(components[top], 1)
        all_events.extend(level_state.get("events", []))

    # Step 6: Overall Character Level — floor instead of round [F-14]
    # #960 (ADR-134): a pillar that has NEVER been instrumented (flagged
    # not_instrumented today AND still at level 1) is excluded and the weights
    # renormalize over the pillars that actually measure something. The frozen
    # relationships pillar (#747) used to sit in the mean at level 1 × 0.07,
    # silently capping the reachable headline at floor(93.07) = 93 and pushing
    # Elite out of any horizon. Once a pillar earns its first level it counts
    # forever — going dark later drags honestly instead of vanishing.
    weighted_level_sum = 0.0
    total_weight = 0.0
    headline_excluded = []
    for pillar_name, result in pillar_results.items():
        if result.get("not_instrumented") and result["level"] <= 1:
            headline_excluded.append(pillar_name)
            continue
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
    total_xp_debt = sum(pr.get("xp_debt", 0) or 0 for pr in pillar_results.values())

    # #913: deterministic character mood — thriving/steady/fading/dormant from
    # the presence signal + the 7d composite raw trend. Pure code, ADR-105.
    mood_verdict = compute_character_mood(engagement, pillar_raw_scores, histories_with_today)

    # Confidence stats [F-01]
    confidences: list[float] = [pr["confidence"] for pr in pillar_results.values() if pr.get("confidence") is not None]
    min_confidence = round(min(confidences), 3) if confidences else 0.0
    avg_confidence = round(sum(confidences) / len(confidences), 3) if confidences else 0.0

    record = {
        "date": compute_date,
        "character_level": character_level,
        "character_tier": character_tier["name"],
        "character_tier_emoji": character_tier.get("emoji", "🔨"),
        "character_xp": total_xp,
        "character_xp_debt": total_xp_debt,  # #913: the visible bleed, summed
        "character_mood": mood_verdict["mood"],  # #913: deterministic, never narrated
        "character_mood_inputs": mood_verdict["inputs"],
        "neglect_decay": decay,  # #913: today's atrophy state (None when engaged)
        "min_confidence": min_confidence,
        "avg_confidence": avg_confidence,
        "active_effects": active_effects,
        "level_events": all_events,
        # #960: which pillars the headline mean excluded (never-instrumented).
        "headline_excluded_pillars": headline_excluded,
        "computed_at": datetime.now(timezone.utc).isoformat(),
        "engine_version": ENGINE_VERSION,
    }
    # #961: record-level challenge summary (site_writer contract).
    if challenge_bonus:
        record["challenge_bonus_xp"] = dict(challenge_bonus)
    for pillar_name, result in pillar_results.items():
        record[f"pillar_{pillar_name}"] = result

    return record


# ==============================================================================
# DDB HELPERS
# ==============================================================================


def store_character_sheet(table_resource: Any, user_prefix: str, record: dict[str, Any]) -> None:
    """Write a character_sheet record to DynamoDB.
    Phase 3.3 (2026-05-16): tags with run_id + computed_at via compute_metadata.
    ADR-058 (2026-05-25): pre-genesis dates are tagged phase='pilot' so the
    read-path phase_filter excludes them by default. Without this, compute
    runs on pre-genesis dates (e.g., from manual test invocations or backfill
    scripts) silently leak as live data post-launch.
    """
    item = {"pk": user_prefix + "character_sheet", "sk": "DATE#" + record["date"]}
    item.update(_to_decimal(record))
    if record.get("date", "") < EXPERIMENT_START_DATE:
        item["phase"] = "pilot"
    try:
        from compute_metadata import tag_record

        item = tag_record(item, source_id="character_sheet")
    except ImportError:
        pass  # Helper not in deploy bundle; fall through to untagged write
    table_resource.put_item(Item=item)
    return item


def fetch_character_sheet(table_resource: Any, user_prefix: str, date_str: str) -> Optional[dict[str, Any]]:
    """Fetch one day's character_sheet record from DynamoDB, decoded from Decimal.

    Returns None if the record is missing or the read fails.
    """
    try:
        resp = table_resource.get_item(Key={"pk": user_prefix + "character_sheet", "sk": "DATE#" + date_str})
        item = resp.get("Item")
        return _from_decimal(item) if item else None
    except Exception:
        return None


def fetch_character_sheet_range(
    table_resource: Any, user_prefix: str, start_date: str, end_date: str, include_pilot: bool = False
) -> list[dict[str, Any]]:
    """ADR-058: phase='pilot' records are excluded by default; restart tooling
    can pass include_pilot=True to opt out of the filter."""
    try:
        from phase_filter import with_phase_filter  # ADR-058: default-deny pilot data

        base_kwargs = {
            "KeyConditionExpression": "pk = :pk AND sk BETWEEN :start AND :end",
            "ExpressionAttributeValues": {
                ":pk": user_prefix + "character_sheet",
                ":start": "DATE#" + start_date,
                ":end": "DATE#" + end_date,
            },
        }
        resp = table_resource.query(**with_phase_filter(base_kwargs, include_pilot=include_pilot))
        items = resp.get("Items", [])
        while resp.get("LastEvaluatedKey"):
            resp = table_resource.query(
                **with_phase_filter(
                    dict(base_kwargs, ExclusiveStartKey=resp["LastEvaluatedKey"]),
                    include_pilot=include_pilot,
                )
            )
            items.extend(resp.get("Items", []))
        return [_from_decimal(i) for i in items]
    except Exception as e:
        logger.error("[character_engine] Range query failed: %s", e)
        return []


def _to_decimal(obj):
    """Recursively convert floats to Decimal for DynamoDB writes (NaN/Inf -> None)."""
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
    """Recursively convert DynamoDB Decimal values back to float."""
    from decimal import Decimal

    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, dict):
        return {k: _from_decimal(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_from_decimal(i) for i in obj]
    return obj
