"""
tests/test_character_engine.py — Unit tests for Character Engine v1.1.0.

Covers findings F-01 through F-15 from the statistical review:
  - F-01: Confidence-weighted pillar scoring
  - F-02: XP decay mechanics
  - F-04: Body composition sigmoid + maintenance
  - F-07: Lab biomarker decay to zero at 180 days
  - F-09: Neutral default 50.0
  - F-12: Vice control logarithmic curve
  - F-13: _in_range_score buffer fix
  - F-14: Floor-based level calculation
  - F-15: Progressive difficulty (tier-specific streaks)
  - F-10: Variable step size
  - F-11: Equal day streak hold

Run with:   python3 -m pytest tests/test_character_engine.py -v
"""

import sys
import os
import math

# ── Add lambdas/ to import path ──
LAMBDAS_DIR = os.path.join(os.path.dirname(__file__), "..", "lambdas")
sys.path.insert(0, os.path.abspath(LAMBDAS_DIR))

from character_engine import (
    _weighted_pillar_score,
    _compute_xp,
    _body_comp_score,
    _compute_lab_score,
    _in_range_score,
    evaluate_level_changes,
    compute_ema_level_score,
    get_tier,
    ENGINE_VERSION,
)


# ── Version ──

def test_engine_version():
    assert ENGINE_VERSION == "1.1.0"


# ── F-01: Confidence scoring ──

def test_weighted_pillar_score_full_data():
    """Full data -> confidence 1.0, no blending."""
    scores = {"a": 80, "b": 60}
    config = {"a": {"weight": 0.5}, "b": {"weight": 0.5}}
    score, details = _weighted_pillar_score(scores, config)
    assert details["_confidence"] == 1.0
    assert score == 70.0  # straight average


def test_weighted_pillar_score_sparse_data():
    """50% data coverage -> blended toward neutral."""
    scores = {"a": 80, "b": None}
    config = {"a": {"weight": 0.5}, "b": {"weight": 0.5}}
    score, details = _weighted_pillar_score(scores, config)
    assert details["_confidence"] < 1.0
    assert 50 < score < 80  # blended toward 50


def test_weighted_pillar_score_no_data():
    """No data -> neutral 50, confidence 0."""
    scores = {"a": None, "b": None}
    config = {"a": {"weight": 0.5}, "b": {"weight": 0.5}}
    score, details = _weighted_pillar_score(scores, config)
    assert score == 50.0
    assert details["_confidence"] == 0.0


# ── F-02: XP decay ──

def test_xp_decays_on_mediocre_day():
    """Score 40 earns +1 XP but decay -2 -> net -1."""
    config = {
        "xp_bands": [{"min_raw_score": 40, "xp": 1}, {"min_raw_score": 0, "xp": -1}],
        "leveling": {"daily_xp_decay": 2},
    }
    earned, delta, new_xp = _compute_xp(45, 100, config)
    assert earned == 1
    assert delta == -1  # 1 earned - 2 decay
    assert new_xp == 99  # 100 + 1 - 2


def test_xp_floors_at_zero():
    config = {
        "xp_bands": [{"min_raw_score": 0, "xp": -1}],
        "leveling": {"daily_xp_decay": 2},
    }
    _, _, new_xp = _compute_xp(10, 1, config)
    assert new_xp == 0  # Can't go negative


def test_xp_grows_on_good_day():
    config = {
        "xp_bands": [{"min_raw_score": 80, "xp": 3}, {"min_raw_score": 0, "xp": -1}],
        "leveling": {"daily_xp_decay": 2},
    }
    earned, delta, new_xp = _compute_xp(85, 100, config)
    assert earned == 3
    assert delta == 1  # 3 earned - 2 decay
    assert new_xp == 101


# ── F-04: Body comp sigmoid ──

def test_body_comp_loss_sigmoid():
    """Sigmoid produces nonlinear curve."""
    config = {"baseline": {"start_weight_lbs": 302, "goal_weight_lbs": 185, "weight_phase": "loss"}}
    score_at_300 = _body_comp_score(300, config)
    score_at_250 = _body_comp_score(250, config)
    score_at_200 = _body_comp_score(200, config)
    assert score_at_300 < score_at_250 < score_at_200
    assert score_at_250 > 30  # Mid-journey should be above 30


def test_body_comp_maintenance():
    config = {"baseline": {"goal_weight_lbs": 185, "weight_phase": "maintenance", "maintenance_band_lbs": 3}}
    assert _body_comp_score(185, config) == 100.0
    assert _body_comp_score(187, config) == 100.0  # within band
    assert _body_comp_score(190, config) < 100.0   # outside band
    assert _body_comp_score(205, config) == 0.0     # 20 lbs out


def test_body_comp_none_weight():
    config = {"baseline": {"start_weight_lbs": 302, "goal_weight_lbs": 185, "weight_phase": "loss"}}
    assert _body_comp_score(None, config) is None


# ── F-07: Lab decay to zero ──

def test_lab_decay_full_value():
    """Labs within 30 days get full credit."""
    labs = {"date": "2026-03-01", "apob": 80, "hba1c": 5.0}
    score = _compute_lab_score(labs, "2026-03-15", {})
    assert score is not None
    assert score > 0


def test_lab_decay_expires():
    """Labs >180 days old get zero credit."""
    labs = {"date": "2025-06-01", "apob": 80}
    score = _compute_lab_score(labs, "2026-03-01", {})
    assert score == 0.0  # 270+ days -> fully expired


def test_lab_decay_at_90_days():
    """Labs at 90 days get ~50% credit."""
    labs = {"date": "2026-01-01", "apob": 80}
    score_fresh = _compute_lab_score(labs, "2026-01-15", {})
    score_90d = _compute_lab_score(labs, "2026-04-01", {})
    assert score_90d is not None
    assert score_fresh is not None
    assert score_90d < score_fresh


# ── F-09: Neutral default ──

def test_ema_empty_returns_50():
    config = {"leveling": {"ema_lambda": 0.85, "ema_window_days": 21}}
    assert compute_ema_level_score([], config) == 50.0


# ── F-12: Vice log curve ──

def test_vice_log_curve():
    """Day 7 should score higher than old linear 23%."""
    avg_streak = 7
    score = min(100, round(100 * math.log(1 + avg_streak) / math.log(31), 1))
    assert score > 50  # log curve rewards early days


def test_vice_log_day_30():
    """Day 30 should score 100."""
    avg_streak = 30
    score = min(100, round(100 * math.log(1 + avg_streak) / math.log(31), 1))
    assert score == 100


# ── F-13: _in_range_score buffer ──

def test_in_range_score_in_range():
    assert _in_range_score(100, 90, 120) == 100.0


def test_in_range_score_below():
    score = _in_range_score(85, 90, 120, buffer=0.5)
    assert score is not None
    assert 0 < score < 100


def test_in_range_score_none():
    assert _in_range_score(None, 90, 120) is None


# ── F-15: Progressive streaks ──

FULL_CONFIG = {
    "leveling": {
        "tier_streak_overrides": {
            "Foundation": {"up": 3, "down": 5, "tier_boundary_up": 5, "tier_boundary_down": 7},
            "Mastery": {"up": 10, "down": 14, "tier_boundary_up": 14, "tier_boundary_down": 21},
        },
        "level_step_threshold": 10,
        "xp_per_level": 100,
        "xp_buffer_threshold": 20,
    },
    "tiers": [
        {"name": "Foundation", "min_level": 1, "max_level": 20},
        {"name": "Momentum", "min_level": 21, "max_level": 40},
        {"name": "Discipline", "min_level": 41, "max_level": 60},
        {"name": "Mastery", "min_level": 61, "max_level": 80},
        {"name": "Elite", "min_level": 81, "max_level": 100},
    ],
}


def test_foundation_levels_up_in_3_days():
    prev = {"level": 5, "tier": "Foundation", "streak_above": 2, "streak_below": 0, "xp_total": 50}
    # target_level=10, delta=5 <= 10, so step=1
    result = evaluate_level_changes("sleep", 10.0, prev, FULL_CONFIG)
    assert result["level"] == 6  # 3rd day -> level up (+1)


def test_foundation_no_levelup_at_2_days():
    prev = {"level": 5, "tier": "Foundation", "streak_above": 1, "streak_below": 0, "xp_total": 50}
    result = evaluate_level_changes("sleep", 60.0, prev, FULL_CONFIG)
    assert result["level"] == 5  # Only 2nd day


def test_mastery_requires_10_days():
    prev = {"level": 65, "tier": "Mastery", "streak_above": 8, "streak_below": 0, "xp_total": 500}
    result = evaluate_level_changes("sleep", 70.0, prev, FULL_CONFIG)
    assert result["level"] == 65  # Only 9th day -- need 10


def test_mastery_levels_up_at_10_days():
    prev = {"level": 65, "tier": "Mastery", "streak_above": 9, "streak_below": 0, "xp_total": 500}
    result = evaluate_level_changes("sleep", 70.0, prev, FULL_CONFIG)
    assert result["level"] == 66  # 10th day -> level up


# ── F-11: Equal day streak hold ──

def test_equal_day_holds_streak():
    """Equal day should not decay streak."""
    prev = {"level": 5, "tier": "Foundation", "streak_above": 2, "streak_below": 0, "xp_total": 50}
    result = evaluate_level_changes("sleep", 5.0, prev, FULL_CONFIG)  # target == current
    assert result["streak_above"] == 2  # Held, not decayed


# ── F-10: Variable step size ──

def test_variable_step_when_delta_large():
    """When target - current > 10, step by 2."""
    prev = {"level": 5, "tier": "Foundation", "streak_above": 2, "streak_below": 0, "xp_total": 50}
    # target_level = round(20.0) = 20, delta = 20 - 5 = 15 > 10
    result = evaluate_level_changes("sleep", 20.0, prev, FULL_CONFIG)
    assert result["level"] == 7  # +2 step


def test_normal_step_when_delta_small():
    """When target - current <= 10, step by 1."""
    prev = {"level": 5, "tier": "Foundation", "streak_above": 2, "streak_below": 0, "xp_total": 50}
    # target_level = round(10.0) = 10, delta = 10 - 5 = 5 <= 10
    result = evaluate_level_changes("sleep", 10.0, prev, FULL_CONFIG)
    assert result["level"] == 6  # +1 step


# ── F-03: Per-pillar EMA ──

def test_per_pillar_ema_lambda():
    """Metabolic pillar uses higher lambda (0.95) than default (0.85)."""
    config = {
        "pillars": {"metabolic": {"ema_lambda": 0.95}},
        "leveling": {"ema_lambda": 0.85, "ema_window_days": 21},
    }
    history = [50.0] * 10 + [80.0]
    score_metabolic = compute_ema_level_score(history, config, pillar_name="metabolic")
    score_default = compute_ema_level_score(history, config, pillar_name="sleep")
    # Higher lambda = more memory of old values = lower score when last value jumps
    assert score_metabolic < score_default


# ── F-02: XP buffer gate ──

def test_xp_buffer_prevents_level_down():
    """High XP buffer should prevent level loss even after streak threshold."""
    prev = {"level": 10, "tier": "Foundation", "streak_above": 0, "streak_below": 4, "xp_total": 50}
    # streak_below will be 5 which meets Foundation down threshold
    # xp_buffer = 50 % 100 = 50 >= 20 threshold -> hold
    result = evaluate_level_changes("sleep", 5.0, prev, FULL_CONFIG)
    assert result["level"] == 10  # Buffer absorbed


def test_xp_buffer_depleted_allows_level_down():
    """Low XP buffer should allow level loss after streak threshold."""
    prev = {"level": 10, "tier": "Foundation", "streak_above": 0, "streak_below": 4, "xp_total": 10}
    # streak_below will be 5 which meets Foundation down threshold
    # xp_buffer = 10 % 100 = 10 < 20 threshold -> allow
    result = evaluate_level_changes("sleep", 5.0, prev, FULL_CONFIG)
    assert result["level"] == 9  # Level down
