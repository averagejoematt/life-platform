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

import math
import os
import sys

# ── Add lambdas/ to import path ──
LAMBDAS_DIR = os.path.join(os.path.dirname(__file__), "..", "lambdas")
sys.path.insert(0, os.path.abspath(LAMBDAS_DIR))

from character_engine import (
    ENGINE_VERSION,
    _body_comp_score,
    _compute_lab_score,
    _compute_xp,
    _in_range_score,
    _roll_xp_buffer,
    _social_quality_to_10,
    _weighted_pillar_score,
    character_level_up_drivers,
    compute_character_sheet,
    compute_ema_level_score,
    compute_relationships_raw,
    evaluate_level_changes,
    pillar_drivers,
)

# ── Version ──


def test_engine_version():
    assert ENGINE_VERSION == "1.7.0"  # #1373: progression-receipt transition capture


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


# ── #747: not-instrumented flag (deterministic, ADR-105) ──


def test_weighted_pillar_score_no_data_flags_not_instrumented():
    """Zero components had ANY value today -> the placeholder 50 is flagged so
    callers never present it as a real reading."""
    scores = {"a": None, "b": None}
    config = {"a": {"weight": 0.5}, "b": {"weight": 0.5}}
    score, details = _weighted_pillar_score(scores, config)
    assert score == 50.0
    assert details["_not_instrumented"] is True


def test_weighted_pillar_score_with_data_not_flagged():
    """As soon as any component has a real value, the flag clears itself —
    no code change needed on the day a data source starts flowing."""
    scores = {"a": 80, "b": None}
    config = {"a": {"weight": 0.5}, "b": {"weight": 0.5}}
    score, details = _weighted_pillar_score(scores, config)
    assert details["_not_instrumented"] is False


def test_compute_relationships_raw_no_data_is_not_instrumented():
    """The reported #747 scenario: none of the relationships components have a
    real data source today (no journal_entries, no buddy_freshness_days) -> the
    pillar is flagged, not silently rendered as a real neutral score."""
    config = {
        "pillars": {
            "relationships": {
                "components": {
                    "social_interaction_frequency": {"weight": 0.4},
                    "interaction_quality": {"weight": 0.3},
                    "buddy_engagement": {"weight": 0.15},
                    "social_mood_correlation": {"weight": 0.15},
                }
            }
        }
    }
    raw, details = compute_relationships_raw({}, config)
    assert raw == 50.0
    assert details["_not_instrumented"] is True


def test_compute_relationships_raw_with_data_is_instrumented():
    """Once a real relationship signal shows up (e.g. journal_entries carries a
    social_connection_score), the pillar scores normally and is no longer flagged."""
    config = {
        "pillars": {
            "relationships": {
                "components": {
                    "social_interaction_frequency": {"weight": 0.4},
                    "interaction_quality": {"weight": 0.3},
                    "buddy_engagement": {"weight": 0.15},
                    "social_mood_correlation": {"weight": 0.15},
                }
            }
        }
    }
    data = {"journal_entries": [{"social_connection_score": 7.0}]}
    raw, details = compute_relationships_raw(data, config)
    assert details["_not_instrumented"] is False
    assert raw != 50.0 or details["_confidence"] > 0  # a real (if partial) reading, not the bare placeholder


# ── #910: categorical enriched_social_quality → numeric social_score bridge ──


def _relationships_config():
    return {
        "pillars": {
            "relationships": {
                "components": {
                    "social_interaction_frequency": {"weight": 0.4},
                    "interaction_quality": {"weight": 0.3},
                    "buddy_engagement": {"weight": 0.15},
                    "social_mood_correlation": {"weight": 0.15},
                }
            }
        }
    }


def test_social_quality_scale_map_full_domain():
    """The four ordered categories spread evenly across the 0–10 scale by rank:
    alone→0, surface→3.33, meaningful→6.67, deep→10. The consumer's
    `social_score * 10` then lands them at the intuitive quartiles 0/33/67/100 %."""
    assert _social_quality_to_10("alone") == 0.0
    assert round(_social_quality_to_10("surface"), 2) == 3.33
    assert round(_social_quality_to_10("meaningful"), 2) == 6.67
    assert _social_quality_to_10("deep") == 10.0
    # Case / whitespace tolerant (the field is a free-form LLM string).
    assert _social_quality_to_10(" Deep ") == 10.0
    # Unknown / null / non-string -> None (falsy contract preserved).
    assert _social_quality_to_10("null") is None
    assert _social_quality_to_10("") is None
    assert _social_quality_to_10(None) is None
    assert _social_quality_to_10(5) is None


def test_social_quality_bridges_interaction_frequency():
    """A day whose only social signal is the categorical enriched_social_quality
    now scores social_interaction_frequency — previously dead, since the numeric
    fields are never written. deep -> 10 -> *10 -> 100."""
    data = {"journal_entries": [{"enriched_social_quality": "deep"}]}
    raw, details = compute_relationships_raw(data, _relationships_config())
    assert details["social_interaction_frequency"]["score"] == 100.0
    assert details["_not_instrumented"] is False


def test_social_quality_averaged_across_entries():
    """Multiple entries' mapped qualities are averaged (mirrors #902's mood_avg).
    deep(10) + surface(3.33) -> avg 6.67 -> *10 -> 66.7."""
    data = {
        "journal_entries": [
            {"enriched_social_quality": "deep"},
            {"enriched_social_quality": "surface"},
        ]
    }
    raw, details = compute_relationships_raw(data, _relationships_config())
    assert details["social_interaction_frequency"]["score"] == 66.7


def test_social_quality_enables_mood_correlation():
    """social_mood_correlation is gated on `social_score is not None`; #902 fixed
    `mood`, and the categorical bridge now supplies the remaining social_score.
    meaningful -> 6.67 (non-None) unlocks the gate; mood_avg 8.0 -> (8/10)*100."""
    data = {
        "journal": {"mood_avg": 8.0},
        "journal_entries": [{"enriched_social_quality": "meaningful"}],
    }
    raw, details = compute_relationships_raw(data, _relationships_config())
    assert details["social_mood_correlation"]["score"] == 80.0


def test_numeric_social_score_takes_precedence_over_quality():
    """The numeric field stays the primary path; the categorical is only a
    fallback. A numeric 7 wins even when enriched_social_quality is also present."""
    data = {"journal_entries": [{"social_connection_score": 7.0, "enriched_social_quality": "alone"}]}
    raw, details = compute_relationships_raw(data, _relationships_config())
    assert details["social_interaction_frequency"]["score"] == 70.0


def test_unknown_social_quality_leaves_both_components_none():
    """An unrecognized / null category leaves social_score None -> both social
    components stay None (falsy contract preserved), even with mood present."""
    data = {"journal": {"mood_avg": 8.0}, "journal_entries": [{"enriched_social_quality": "null"}]}
    raw, details = compute_relationships_raw(data, _relationships_config())
    assert details["social_interaction_frequency"]["score"] is None
    assert details["social_mood_correlation"]["score"] is None


def test_compute_character_sheet_propagates_not_instrumented_and_note():
    """End-to-end: compute_character_sheet's pillar_results carry the flag +
    the config-sourced note for a pillar with a note configured, and nothing
    extra for a pillar that's genuinely instrumented."""
    config = {
        "pillars": {
            "sleep": {"weight": 0.5, "components": {"duration_vs_target": {"weight": 1.0, "target_hours": 7.5}}},
            "relationships": {
                "weight": 0.5,
                "not_instrumented_note": "No relationship data source feeds this pillar yet — tracked as future work (#747).",
                "components": {"social_interaction_frequency": {"weight": 1.0}},
            },
        },
        "leveling": {},
        "tiers": [{"name": "Foundation", "min_level": 1, "max_level": 100}],
        "xp_bands": [{"min_raw_score": 0, "xp": 0}],
        "cross_pillar_effects": [],
    }
    data = {"date": "2026-07-08", "sleep": {"sleep_duration_hours": 7.5, "sleep_performance": 90}}
    record = compute_character_sheet(data, None, {"sleep": [], "relationships": []}, config)

    rel = record["pillar_relationships"]
    assert rel["not_instrumented"] is True
    assert rel["not_instrumented_note"] == "No relationship data source feeds this pillar yet — tracked as future work (#747)."

    sleep_p = record["pillar_sleep"]
    assert sleep_p["not_instrumented"] is False
    assert sleep_p["not_instrumented_note"] is None


# ── F-02: XP decay ──


def test_xp_decays_on_mediocre_day():
    """Score 40 earns +1 XP but decay -2 -> net -1."""
    config = {
        "xp_bands": [{"min_raw_score": 40, "xp": 1}, {"min_raw_score": 0, "xp": -1}],
        "leveling": {"daily_xp_decay": 2},
    }
    earned, delta, new_xp, debt = _compute_xp(45, 100, config)
    assert earned == 1
    assert delta == -1  # 1 earned - 2 decay
    assert new_xp == 99  # 100 + 1 - 2
    assert debt == 0  # positive balance -> no debt


def test_xp_floors_at_zero_with_visible_debt():
    """#913: xp_total still floors at 0 (downstream % consumers untouched),
    but the shortfall is now a visible xp_debt instead of vanishing."""
    config = {
        "xp_bands": [{"min_raw_score": 0, "xp": -1}],
        "leveling": {"daily_xp_decay": 2},
    }
    _, _, new_xp, debt = _compute_xp(10, 1, config)
    assert new_xp == 0  # Can't go negative
    assert debt == 2  # 1 - 3 = -2 -> the bleed is visible, not silent


def test_xp_grows_on_good_day():
    config = {
        "xp_bands": [{"min_raw_score": 80, "xp": 3}, {"min_raw_score": 0, "xp": -1}],
        "leveling": {"daily_xp_decay": 2},
    }
    earned, delta, new_xp, debt = _compute_xp(85, 100, config)
    assert earned == 3
    assert delta == 1  # 3 earned - 2 decay
    assert new_xp == 101
    assert debt == 0


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
    assert _body_comp_score(190, config) < 100.0  # outside band
    assert _body_comp_score(205, config) == 0.0  # 20 lbs out


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


# ── #954 (char-math-2): the demotion buffer is explicit, monotone state ──


def test_xp_buffer_decline_across_century_does_not_rearm():
    """The wrap bug: xp 205 → 199 used to flip the buffer 5 → 99 (% 100),
    re-arming near-maximum demotion immunity BY LOSING XP. The rolled buffer
    drains by the loss and floors at 0 — it can only ever deplete on decline."""
    assert _roll_xp_buffer(5, 205, 199, 100) == 0
    assert _roll_xp_buffer(5, 205, 202, 100) == 2  # partial drain, no wrap


def test_xp_buffer_monotone_under_sustained_decline():
    """60 crash days: the buffer never increases while XP only falls."""
    buffer, xp = None, 205.0
    seen = []
    for _ in range(60):
        new_xp = max(0.0, xp - 3.0)
        buffer = _roll_xp_buffer(buffer, xp, new_xp, 100)
        seen.append(buffer)
        xp = new_xp
    assert all(b2 <= b1 for b1, b2 in zip(seen, seen[1:]))
    assert seen[-1] == 0


def test_xp_buffer_fills_on_gain_capped_at_one_level():
    assert _roll_xp_buffer(95, 200, 212, 100) == 100  # fills, capped
    assert _roll_xp_buffer(40, 100, 103, 100) == 43  # ordinary good day


def test_xp_buffer_legacy_state_seeds_from_remainder():
    """State stored before the fix has no xp_buffer — seed from the previous
    total's within-level remainder (the last honest pre-wrap reading)."""
    assert _roll_xp_buffer(None, 250, 245, 100) == 45  # seed 50, drain 5


def test_stored_buffer_wins_over_modulo_in_down_gate():
    """xp_total=199 would read as buffer 99 under the old % wrap and hold the
    level forever; the explicitly stored (drained) buffer must win."""
    prev = {"level": 10, "tier": "Foundation", "streak_above": 0, "streak_below": 4, "xp_total": 199, "xp_buffer": 5}
    result = evaluate_level_changes("sleep", 5.0, prev, FULL_CONFIG)
    assert result["level"] == 9  # demotes — the wrap no longer grants immunity


def test_stored_buffer_still_absorbs_when_genuinely_earned():
    prev = {"level": 10, "tier": "Foundation", "streak_above": 0, "streak_below": 4, "xp_total": 130, "xp_buffer": 30}
    result = evaluate_level_changes("sleep", 5.0, prev, FULL_CONFIG)
    assert result["level"] == 10  # a real earned buffer still holds


def test_sixty_day_crash_demotes_honestly_despite_lifetime_xp():
    """The issue's sim: level 30 with xp_total=205 crashed for 60 days used to
    demote ONCE (30→28) because every century crossing re-armed the buffer.
    With the monotone buffer the pillar falls at the streak-gated pace."""
    state = {"level": 30, "tier": "Momentum", "streak_above": 0, "streak_below": 0, "xp_total": 205.0}
    buffer = None
    downs = 0
    for _ in range(60):
        result = evaluate_level_changes("sleep", 5.0, dict(state, xp_buffer=buffer), FULL_CONFIG, data_coverage=1.0, raw_score=5.0)
        _earned, _delta, new_xp, _debt = _compute_xp(5.0, state["xp_total"], FULL_CONFIG)
        buffer = _roll_xp_buffer(buffer, state["xp_total"], new_xp, 100)
        downs += sum(1 for e in result.get("events", []) if e["type"] == "level_down")
        state = {
            "level": result["level"],
            "tier": result["tier"],
            "streak_above": result["streak_above"],
            "streak_below": result["streak_below"],
            "xp_total": new_xp,
        }
    assert downs >= 4  # the old wrap allowed exactly 1 demotion in 60 days
    assert state["level"] < 28  # 28 was the buggy landing spot


# ── #954 (char-sim-1): cross-pillar boosts must not raise the raw-day bar ──


def test_boosted_target_does_not_freeze_up_gate():
    """Steady raw 76 under a +16% cross-pillar boost: the boosted target (88)
    exceeds any day this performer lives, but the gate compares against the
    UNboosted EMA (76) — the pillar still climbs toward the boosted target."""
    prev = {"level": 5, "tier": "Foundation", "streak_above": 2, "streak_below": 0, "xp_total": 50}
    result = evaluate_level_changes("metabolic", 88.2, prev, FULL_CONFIG, data_coverage=1.0, raw_score=76.0, unadjusted_level_score=76.0)
    assert result["level"] > 5  # 3rd Foundation day above target -> climb


def test_boosted_target_freezes_without_unadjusted_score():
    """Legacy callers that don't pass the unboosted EMA keep the old gate."""
    prev = {"level": 5, "tier": "Foundation", "streak_above": 2, "streak_below": 0, "xp_total": 50}
    result = evaluate_level_changes("metabolic", 88.2, prev, FULL_CONFIG, data_coverage=1.0, raw_score=76.0)
    assert result["level"] == 5
    assert result["streak_above"] == 2  # held, not reset


def test_negative_modifier_keeps_the_looser_adjusted_gate():
    """With a NEGATIVE modifier the adjusted target is BELOW the raw EMA; the
    gate uses min(adjusted, unadjusted) so it never demands more than the
    target the pillar is actually climbing toward."""
    prev = {"level": 5, "tier": "Foundation", "streak_above": 2, "streak_below": 0, "xp_total": 50}
    result = evaluate_level_changes("metabolic", 26.0, prev, FULL_CONFIG, data_coverage=1.0, raw_score=26.0, unadjusted_level_score=30.0)
    assert result["level"] > 5  # raw 26 meets the adjusted target 26


def test_unboosted_gate_still_blocks_ema_momentum():
    """The #913 protection is intact: a crashed raw day can't ride either
    target up — 9 fails the unboosted EMA (26) exactly as it fails the target."""
    prev = {"level": 8, "tier": "Foundation", "streak_above": 5, "streak_below": 0, "xp_total": 0}
    result = evaluate_level_changes("movement", 30.2, prev, FULL_CONFIG, data_coverage=1.0, raw_score=9.0, unadjusted_level_score=26.0)
    assert result["level"] == 8
    assert result.get("events") == []


def test_steady_76_with_active_boost_levels_up_end_to_end():
    """Issue #954 regression (1), through compute_character_sheet: a steady
    raw-76 sleep pillar under an active +16% cross-pillar effect must climb —
    before the fix the boosted target (88) froze it at its previous level."""
    config = _scenario_config()
    config["cross_pillar_effects"] = [
        {"name": "Test Boost", "emoji": "*", "condition": "sleep >= 50", "targets": {"sleep": 0.16}},
    ]
    # sleep_performance 76 with only the efficiency component -> raw exactly 76
    config["pillars"]["sleep"]["components"] = {"efficiency": {"weight": 1.0}}
    data = {"date": "2026-07-20", "sleep": {"sleep_performance": 76}}
    prev_state = {
        "character_level": 3,
        "pillar_sleep": {"level": 5, "tier": "Foundation", "streak_above": 2, "streak_below": 0, "xp_total": 50, "xp_debt": 0},
    }
    record = compute_character_sheet(data, prev_state, {"sleep": [76.0] * 21}, config)

    sleep_p = record["pillar_sleep"]
    assert any(e["name"] == "Test Boost" for e in record["active_effects"])
    assert sleep_p["raw_score"] == 76.0
    assert sleep_p["level_score"] > 85  # the boost still lifts the displayed target
    assert sleep_p["level"] > 5  # ...and no longer freezes the climb


# ── ADR-104: behavioral absence scores 0, not neutral ──


def test_behavioral_absent_scores_zero():
    """An unlogged behavior is a miss (0 at full weight), not dropped-to-neutral."""
    scores = {"journal_consistency": None, "stress_management": 60}
    config = {
        "journal_consistency": {"weight": 0.5, "behavioral": True},
        "stress_management": {"weight": 0.5},
    }
    score, details = _weighted_pillar_score(scores, config)
    # Both components count: (0*0.5 + 60*0.5) / 1.0 = 30, full coverage, no blend
    assert score == 30.0
    assert details["_data_coverage"] == 1.0
    assert details["_absent_behaviors"] == ["journal_consistency"]
    assert details["journal_consistency"] == {"score": 0.0, "weight": 0.5, "absent": True}


def test_measured_absent_still_neutral_blended():
    """A missing device reading keeps the confidence blend — a gap is not a failure."""
    scores = {"efficiency": None, "duration_vs_target": 80}
    config = {"efficiency": {"weight": 0.5}, "duration_vs_target": {"weight": 0.5}}
    score, details = _weighted_pillar_score(scores, config)
    assert details["_absent_behaviors"] == []
    assert 50 < score < 80  # blended toward neutral, unchanged v1.1 semantics


def test_fully_absent_behavioral_pillar_scores_low_not_neutral():
    """The level-13 bug: a pillar of unlogged behaviors must read ~0, not ~50."""
    scores = {"a": None, "b": None, "c": None}
    config = {
        "a": {"weight": 0.4, "behavioral": True},
        "b": {"weight": 0.3, "behavioral": True},
        "c": {"weight": 0.3, "behavioral": True},
    }
    score, details = _weighted_pillar_score(scores, config)
    assert score == 0.0
    assert details["_data_coverage"] == 1.0  # absence IS information here


# ── ADR-104: coverage gate — no-signal days can't move levels ──


def test_low_coverage_day_cannot_level_up():
    """Neutral-blended thin-data days must not climb (the lockstep-13 driver)."""
    prev = {"level": 5, "tier": "Foundation", "streak_above": 2, "streak_below": 0, "xp_total": 50}
    result = evaluate_level_changes("relationships", 50.0, prev, FULL_CONFIG, data_coverage=0.15)
    assert result["level"] == 5
    assert result["coverage_hold"] is True
    assert result["streak_above"] == 2  # held, not incremented


def test_low_coverage_day_cannot_level_down():
    """No information must not crash a pillar either — unknown ≠ failure."""
    prev = {"level": 10, "tier": "Foundation", "streak_above": 0, "streak_below": 4, "xp_total": 10}
    result = evaluate_level_changes("relationships", 2.0, prev, FULL_CONFIG, data_coverage=0.1)
    assert result["level"] == 10
    assert result["streak_below"] == 4  # held


def test_good_coverage_day_levels_normally():
    prev = {"level": 5, "tier": "Foundation", "streak_above": 2, "streak_below": 0, "xp_total": 50}
    result = evaluate_level_changes("sleep", 10.0, prev, FULL_CONFIG, data_coverage=0.9)
    assert result["level"] == 6
    assert result["coverage_hold"] is False


def test_no_coverage_arg_keeps_legacy_behavior():
    """Callers that don't pass coverage (e.g. old stored paths) are unaffected."""
    prev = {"level": 5, "tier": "Foundation", "streak_above": 2, "streak_below": 0, "xp_total": 50}
    result = evaluate_level_changes("sleep", 10.0, prev, FULL_CONFIG)
    assert result["level"] == 6


# ── ADR-104: drivers provenance ──


def test_raw_gate_blocks_up_on_ema_momentum():
    """EMA still above the level, but today scored 0 — no climb credit."""
    prev = {"level": 8, "tier": "Foundation", "streak_above": 2, "streak_below": 0, "xp_total": 50}
    result = evaluate_level_changes("movement", 26.0, prev, FULL_CONFIG, data_coverage=1.0, raw_score=0.0)
    assert result["level"] == 8
    assert result["streak_above"] == 2  # held — the day didn't earn it


def test_raw_gate_allows_up_when_day_performed():
    prev = {"level": 8, "tier": "Foundation", "streak_above": 2, "streak_below": 0, "xp_total": 50}
    result = evaluate_level_changes("movement", 26.0, prev, FULL_CONFIG, data_coverage=1.0, raw_score=64.0)
    assert result["level"] > 8


def test_step_bands_scale_with_gap():
    """A huge honest gap converges faster than a small one (no more lockstep pace)."""
    bands_cfg = {
        "leveling": dict(FULL_CONFIG["leveling"], level_step_bands=[{"min_delta": 25, "step": 3}, {"min_delta": 10, "step": 2}]),
        "tiers": FULL_CONFIG["tiers"],
    }
    prev = {"level": 5, "tier": "Foundation", "streak_above": 2, "streak_below": 0, "xp_total": 50}
    big_gap = evaluate_level_changes("sleep", 80.0, prev, bands_cfg, raw_score=85.0)
    small_gap = evaluate_level_changes("sleep", 12.0, prev, bands_cfg, raw_score=85.0)
    assert big_gap["level"] == 8  # +3
    assert small_gap["level"] == 6  # +1


def test_pillar_drivers_summary():
    details = {
        "t0_habit_compliance": {"score": 0.0, "weight": 0.3, "absent": True},
        "journal_consistency": {"score": 0.0, "weight": 0.15, "absent": True},
        "stress_management": {"score": 72.0, "weight": 0.15},
        "vice_control": {"score": 25.0, "weight": 0.1},
        "state_of_mind_valence": {"score": None, "weight": 0.15},
        "_confidence": 0.9,
        "_data_coverage": 0.85,
        "_absent_behaviors": ["t0_habit_compliance", "journal_consistency"],
    }
    d = pillar_drivers(details)
    assert d["top"] == ["stress_management"]
    assert d["dragging"] == ["vice_control"]
    assert d["absent"] == ["t0_habit_compliance", "journal_consistency"]
    assert d["no_data"] == ["state_of_mind_valence"]


def test_state_of_mind_valence_reads_som_avg_valence():
    """#507: SoM daily aggregate lands on the apple_health record as som_avg_valence
    (HealthKit -1..+1). The Mind pillar must read that field (the old code read a
    non-existent `valence`/`average_valence` key → always None even with real data)
    and map it to 0..100, while honest absence stays None (ADR-104)."""
    from character_engine import compute_mind_raw

    cfg = {"pillars": {"mind": {"components": {"state_of_mind_valence": {"weight": 1.0}}}}}

    # Real one-day fixture value (raw/matthew/state_of_mind/2026/04/02.json) → slightly unpleasant.
    _, details = compute_mind_raw({"state_of_mind": {"som_avg_valence": -0.2965}}, cfg)
    assert details["state_of_mind_valence"]["score"] == 35.2

    # Full-scale endpoints and neutral midpoint.
    for valence, expected in [(1.0, 100.0), (-1.0, 0.0), (0.0, 50.0)]:
        _, d2 = compute_mind_raw({"state_of_mind": {"som_avg_valence": valence}}, cfg)
        assert d2["state_of_mind_valence"]["score"] == expected

    # Behavioral absence reads as None, never fabricated.
    _, d3 = compute_mind_raw({"state_of_mind": {}}, cfg)
    assert d3["state_of_mind_valence"]["score"] is None


# ── ADR-104: the reported scenario, end-to-end ──
# 20 days: wearables flow (sleep data present), but zero journaling all cycle
# and habits/workouts stop after day 13. Mind must lag sleep; movement must
# sink after the stop; nothing may climb in lockstep on neutral defaults.


def _scenario_config():
    return {
        "experiment_start": "2026-06-14",
        "pillars": {
            "sleep": {
                "weight": 0.2,
                "components": {
                    "duration_vs_target": {"weight": 0.5, "target_hours": 7.5},
                    "efficiency": {"weight": 0.5},
                },
            },
            "movement": {
                "weight": 0.18,
                "components": {
                    "training_frequency": {"weight": 0.5, "target_sessions_week": 5, "behavioral": True},
                    "zone2_adequacy": {"weight": 0.5, "target_minutes": 150, "behavioral": True},
                },
            },
            "nutrition": {
                "weight": 0.18,
                "components": {
                    "calorie_adherence": {"weight": 0.5, "behavioral": True},
                    "protein_total": {"weight": 0.5, "target_grams": 190, "behavioral": True},
                },
            },
            "metabolic": {"weight": 0.12, "components": {"resting_heart_rate": {"weight": 1.0}}},
            "mind": {
                "weight": 0.15,
                "components": {
                    "t0_habit_compliance": {"weight": 0.45, "behavioral": True},
                    "journal_consistency": {"weight": 0.3, "behavioral": True},
                    "stress_management": {"weight": 0.25},
                },
            },
            "relationships": {
                "weight": 0.07,
                "components": {"social_interaction_frequency": {"weight": 1.0}},
            },
            "consistency": {"weight": 0.1, "components": {"data_completeness": {"weight": 1.0}}},
        },
        "leveling": {
            "ema_lambda": 0.85,
            "ema_window_days": 21,
            "level_change_min_coverage": 0.5,
            "level_step_threshold": 10,
            "level_step_bands": [{"min_delta": 25, "step": 3}, {"min_delta": 10, "step": 2}],
            "xp_per_level": 100,
            "daily_xp_decay": 2,
            "xp_buffer_threshold": 20,
            "tier_streak_overrides": {"Foundation": {"up": 3, "down": 5, "tier_boundary_up": 5, "tier_boundary_down": 7}},
        },
        "tiers": [
            {"name": "Foundation", "min_level": 1, "max_level": 20},
            {"name": "Momentum", "min_level": 21, "max_level": 100},
        ],
        "xp_bands": [
            {"min_raw_score": 80, "xp": 3},
            {"min_raw_score": 60, "xp": 2},
            {"min_raw_score": 40, "xp": 1},
            {"min_raw_score": 20, "xp": 0},
            {"min_raw_score": 0, "xp": -1},
        ],
        "cross_pillar_effects": [],
        "baseline": {"start_weight_lbs": 314.52, "goal_weight_lbs": 185, "weight_phase": "loss"},
    }


def _scenario_day(day_index):
    """Data for day N of the scenario (0-based). Good sleep every day; workouts
    and nutrition logging stop at day 13; journaling/habits never happen."""
    trained = day_index < 13
    data = {
        "date": f"2026-06-{14 + day_index:02d}" if day_index < 17 else f"2026-07-{day_index - 16:02d}",
        "sleep": {"sleep_duration_hours": 7.4, "sleep_performance": 88},
        "whoop": {"recovery_score": 62, "resting_heart_rate": 58},
        "strava_7d": ([{"activities": [{"sport_type": "ride", "zone2_minutes": 35}]}] * 4) if trained else [],
        "macrofactor": ({"calories": 2400, "calorie_target": 2500, "protein": 185} if trained else None),
        "habit_scores": None,
        "journal_14d_count": 0,
    }
    return data


def test_reported_scenario_mind_lags_and_movement_sinks():
    config = _scenario_config()
    prev_state = None
    histories = {p: [] for p in config["pillars"]}
    for day in range(20):
        record = compute_character_sheet(_scenario_day(day), prev_state, histories, config)
        for p in config["pillars"]:
            histories[p].append(record[f"pillar_{p}"]["raw_score"])
        prev_state = record

    sleep_p = record["pillar_sleep"]
    mind_p = record["pillar_mind"]
    move_p = record["pillar_movement"]

    # Mind never journaled / logged habits: raw is stress-only ≈ 15, far below sleep
    assert mind_p["raw_score"] < 30 < sleep_p["raw_score"]
    # Habit logging vanished entirely (record absent → behavioral zero, flagged);
    # journaling shows as a scored 0/100 (the 14d count always exists) — both honest.
    assert mind_p["absent_behaviors"] == ["t0_habit_compliance"]
    assert mind_p["components"]["journal_consistency"]["score"] == 0.0
    # Movement collapsed after workouts stopped on day 13
    assert move_p["raw_score"] == 0.0
    # #747: the scenario never feeds a relationships signal (no journal_entries) —
    # the pillar is flagged not-instrumented, not silently reported as a real 50.
    assert record["pillar_relationships"]["not_instrumented"] is True
    # Levels no longer march in lockstep: mind trails sleep, movement fell behind
    assert mind_p["level"] < sleep_p["level"]
    assert move_p["level"] < sleep_p["level"]
    # And the sheet differentiates: pillar levels spread, not one shared number
    levels = [record[f"pillar_{p}"]["level"] for p in config["pillars"]]
    assert max(levels) - min(levels) >= 6
    # Overall level sits below the best pillar — it's a weighted floor of a mixed story
    assert record["character_level"] < sleep_p["level"]


def test_reported_scenario_down_levels_after_stop():
    """A pillar that earned levels then went dark must give some back."""
    config = _scenario_config()
    prev_state = None
    histories = {p: [] for p in config["pillars"]}
    peak_move_level = 1
    for day in range(35):  # extend past the stop to let the EMA + shield drain
        record = compute_character_sheet(_scenario_day(day), prev_state, histories, config)
        for p in config["pillars"]:
            histories[p].append(record[f"pillar_{p}"]["raw_score"])
        if day == 12:
            peak_move_level = record["pillar_movement"]["level"]
        prev_state = record

    assert peak_move_level > 1  # it climbed while training was real
    assert record["pillar_movement"]["level"] < peak_move_level  # and gave levels back


# ── #1125: character_level_up persists its drivers at event fire time ──


def test_character_level_up_drivers_selection():
    """Top-3 pillars by raw_score; zero/absent scores excluded (same rule as
    the journey-timeline read-time enrichment it replaces going forward)."""
    pillar_results = {
        "sleep": {"raw_score": 82.0, "level": 12},
        "movement": {"raw_score": 0.0, "level": 3},  # zero performance: never a driver
        "nutrition": {"raw_score": 91.54, "level": 9},
        "metabolic": {"raw_score": 55.0, "level": 4},
        "mind": {"raw_score": 60.0, "level": 5},
        "relationships": {"raw_score": None, "level": 1},  # no signal: never a driver
    }
    drivers = character_level_up_drivers(pillar_results)
    assert [d["pillar"] for d in drivers] == ["nutrition", "sleep", "mind"]
    assert drivers[0]["raw_score"] == 91.5  # rounded to .1 like the stored record
    assert drivers[0]["level"] == 9


def test_character_level_up_event_persists_drivers():
    """#1125: a headline level-up event carries its fire-time attribution —
    the day's top pillars by raw_score — persisted ON the event, so it
    survives engine re-tuning (read-time reconstruction does not)."""
    import json

    cfg_path = os.path.join(os.path.dirname(__file__), "..", "config", "character_sheet.json")
    with open(cfg_path) as f:
        config = json.load(f)

    pillars = ["sleep", "movement", "nutrition", "metabolic", "mind", "relationships", "consistency"]
    # Yesterday's stored state: pillar levels already earned but the stored
    # headline lags — today's recomputed weighted floor lands higher, which
    # fires character_level_up (streak gates hold every pillar at 12 today).
    prev = {"character_level": 3}
    for p in pillars:
        prev[f"pillar_{p}"] = {"level": 12, "tier": "Foundation", "streak_above": 0, "streak_below": 0, "xp_total": 100}
    rec = compute_character_sheet({"date": "2026-08-01", "apple": {"steps": 11000}}, prev, {}, config)

    ups = [e for e in rec["level_events"] if e["type"] == "character_level_up"]
    assert len(ups) == 1, rec["level_events"]
    drivers = ups[0]["drivers"]
    assert 1 <= len(drivers) <= 3
    for d in drivers:
        assert d["pillar"] in pillars
        assert d["raw_score"] > 0
    # Exactly the record's own top raw scores, highest first — persisted and
    # read-time attribution agree on the day the event fires.
    expected = sorted(
        ((k.replace("pillar_", ""), rec[k]["raw_score"]) for k in rec if k.startswith("pillar_") and (rec[k]["raw_score"] or 0) > 0),
        key=lambda t: -t[1],
    )[:3]
    assert [(d["pillar"], d["raw_score"]) for d in drivers] == [(n, round(float(s), 1)) for n, s in expected]
