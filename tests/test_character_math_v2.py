"""
tests/test_character_math_v2.py — Character math v2 (epic #956, ADR-134).

Covers the seven mechanics the 2026-07 math audit flagged
(docs/engines/CHARACTER_MATH_AUDIT_2026-07.md):
  - #958: XP zero-point at "a decent day" (decay 1 — raw 40-59 nets 0, 60+ positive)
  - #964: XP earn/decay gated on coverage_hold / not_instrumented
  - #961: food-delivery modifier + challenge XP as ENGINE inputs (provenance,
          debt-first paydown, stored raw == engine-scored raw)
  - #959: persistent down-streak + buffer bypass during confirmed dark stretches
  - #960: headline weighted mean renormalized over instrumented pillars
  - #962: derived consistency inputs + data-driven any_vice_streak conditions
  - #954 sizing: xp_buffer fill capped at leveling.xp_buffer_cap

Run with:   python3 -m pytest tests/test_character_math_v2.py -v
"""

import copy
import os
import sys

# ── Add lambdas/ to import path ──
LAMBDAS_DIR = os.path.join(os.path.dirname(__file__), "..", "lambdas")
sys.path.insert(0, os.path.abspath(LAMBDAS_DIR))

import character_engine as ce
from character_engine import (
    _compute_xp,
    _evaluate_condition,
    _roll_xp_buffer,
    compute_character_sheet,
    compute_cross_pillar_effects,
    derive_consistency_inputs,
    evaluate_level_changes,
)

V2_LEVELING = {
    "ema_lambda": 0.85,
    "ema_window_days": 21,
    "level_change_min_coverage": 0.5,
    "level_up_streak_days": 5,
    "level_down_streak_days": 7,
    "tier_up_streak_days": 7,
    "tier_down_streak_days": 10,
    "level_step_bands": [{"min_delta": 25, "step": 3}, {"min_delta": 10, "step": 2}],
    "xp_per_level": 100,
    "daily_xp_decay": 1,
    "xp_buffer_threshold": 20,
    "xp_buffer_cap": 40,
    "xp_debt_cap": 100,
    "neglect_decay": {
        "n_grace_days": 3,
        "rate": 0.98,
        "floor": 0,
        "min_behavioral_share": 0.3,
        "persistent_down_streak": True,
    },
    "tier_streak_overrides": {},
}

XP_BANDS = [
    {"min_raw_score": 80, "xp": 3},
    {"min_raw_score": 60, "xp": 2},
    {"min_raw_score": 40, "xp": 1},
    {"min_raw_score": 20, "xp": 0},
    {"min_raw_score": 0, "xp": -1},
]

V2_CONFIG = {
    "pillars": {
        "movement": {
            "weight": 0.5,
            "ema_lambda": 0.9,
            "components": {
                "sessions": {"weight": 0.6, "behavioral": True},
                "steps": {"weight": 0.4},
            },
        },
        "relationships": {
            "weight": 0.5,
            "ema_lambda": 0.93,
            "components": {
                "social": {"weight": 1.0},
            },
        },
    },
    "leveling": V2_LEVELING,
    "xp_bands": XP_BANDS,
    "tiers": [
        {"name": "Foundation", "min_level": 1, "max_level": 20},
        {"name": "Momentum", "min_level": 21, "max_level": 40},
        {"name": "Discipline", "min_level": 41, "max_level": 60},
        {"name": "Mastery", "min_level": 61, "max_level": 80},
        {"name": "Elite", "min_level": 81, "max_level": 100},
    ],
    "cross_pillar_effects": [],
}


def _cfg(**leveling_overrides):
    cfg = copy.deepcopy(V2_CONFIG)
    cfg["leveling"].update(leveling_overrides)
    return cfg


# ══════════════════════════════════════════════════════════════════════════════
# #958 · XP zero-point sits at "a decent day", not raw 80
# ══════════════════════════════════════════════════════════════════════════════


def test_xp_decent_day_is_net_positive():
    """Raw 60-79 ("a solid day") must GROW XP under the v2 decay of 1."""
    _earned, delta, new_xp, debt = _compute_xp(65, 50, _cfg(), day_number=30)
    assert delta == 1
    assert new_xp == 51
    assert debt == 0


def test_xp_mediocre_day_breaks_even():
    """Raw 40-59 is the neutral point — no growth, no bleed."""
    _earned, delta, new_xp, debt = _compute_xp(45, 50, _cfg(), day_number=30)
    assert delta == 0
    assert new_xp == 50
    assert debt == 0


def test_xp_bad_day_still_bleeds():
    """Raw < 20 keeps bleeding — the retraction signal survives the retune."""
    _earned, delta, new_xp, debt = _compute_xp(10, 1, _cfg(), day_number=30)
    assert delta == -2
    assert new_xp == 0
    assert debt == 1


def test_xp_debt_repayable_by_realistic_living():
    """A dark-stretch debt pays down day by day at raw ~65 — never a one-way
    ratchet (the pre-v2 economy needed raw 80+ to move debt at all)."""
    debt = 30
    xp = 0
    for _ in range(30):
        _e, _d, xp, debt = _compute_xp(65, xp, _cfg(), day_number=100, previous_debt=debt)
    assert debt == 0
    assert xp == 0  # 30 days x net +1 exactly clears the 30-debt hole


# ══════════════════════════════════════════════════════════════════════════════
# #964 · XP mirrors the level gate: no signal, no XP judgment
# ══════════════════════════════════════════════════════════════════════════════


def _not_instrumented_day(date="2026-08-01"):
    """Movement fully scored; relationships has NO data (not_instrumented)."""
    return {
        "date": date,
        "_script": None,  # unused — real computers run below
    }


def _sheet(config, data_overrides=None, prev=None, histories=None):
    data = {"date": "2026-08-01"}
    data.update(data_overrides or {})
    return compute_character_sheet(data, prev, histories or {}, config)


def test_uninstrumented_pillar_accrues_no_xp_and_no_debt():
    """The #747 relationships placeholder (coverage 0.0) must stop feeding the
    bands as 'a mediocre day' — no earn, no decay, no phantom debt, ever."""
    cfg = _cfg()
    rec = None
    histories = {}
    for day in range(40):
        data = {"date": f"2026-08-{(day % 28) + 1:02d}", "apple": {"steps": 9000}}
        rec = compute_character_sheet(data, rec, histories, cfg)
        for p, r in [(k, v) for k, v in rec.items() if k.startswith("pillar_")]:
            histories.setdefault(p.replace("pillar_", ""), []).append(r["raw_score"])
    rel = rec["pillar_relationships"]
    assert rel["not_instrumented"] is True
    assert rel["xp_total"] == 0
    assert rel["xp_debt"] == 0
    assert rel["xp_earned"] == 0


def test_coverage_hold_freezes_xp_both_directions():
    """A below-floor-coverage day carries no XP judgment (mirrors the level
    gate): prior XP and prior debt both carry over untouched."""
    cfg = _cfg()
    # movement scored only by the measured component -> coverage 0.4 < 0.5
    prev = {
        "character_level": 5,
        "pillar_movement": {"level": 5, "tier": "Foundation", "streak_above": 0, "streak_below": 0, "xp_total": 37, "xp_debt": 12},
    }
    data = {"date": "2026-08-02", "apple": {"steps": 9000}}
    # Note: 'sessions' is behavioral -> absence scores 0 at full weight, so
    # coverage stays 1.0. To force a genuine coverage hold, use a config where
    # the missing component is measured.
    cfg2 = copy.deepcopy(cfg)
    cfg2["pillars"]["movement"]["components"]["sessions"] = {"weight": 0.6}  # measured now
    rec = compute_character_sheet(data, prev, {}, cfg2)
    mv = rec["pillar_movement"]
    assert mv["coverage_hold"] is True
    assert mv["xp_total"] == 37
    assert mv["xp_debt"] == 12
    assert mv["xp_earned"] == 0
    assert mv["xp_delta"] == 0


# ══════════════════════════════════════════════════════════════════════════════
# #961 · Modifiers + challenge XP are engine inputs
# ══════════════════════════════════════════════════════════════════════════════


def _movement_data(steps=12000):
    return {"date": "2026-08-01", "apple": {"steps": steps}}


def test_raw_modifier_applies_before_gates_with_provenance():
    cfg = _cfg()
    data = _movement_data()
    data["raw_score_modifiers"] = {"movement": {"multiplier": 0.85, "source": "food_delivery"}}
    rec_mod = compute_character_sheet(data, None, {}, cfg)
    rec_base = compute_character_sheet(_movement_data(), None, {}, cfg)
    mv_mod, mv_base = rec_mod["pillar_movement"], rec_base["pillar_movement"]
    # Stored raw IS the engine-scored raw — scaled, clamped, with provenance.
    assert mv_mod["raw_score"] < mv_base["raw_score"]
    assert mv_mod["raw_modifier"]["source"] == "food_delivery"
    assert mv_mod["raw_modifier"]["multiplier"] == 0.85
    assert mv_mod["raw_modifier"]["pre_modifier_raw"] == mv_base["raw_score"]
    # And the XP bands judged the modified value, not the pre-modifier one.
    assert mv_mod["xp_earned"] <= mv_base["xp_earned"]


def test_challenge_bonus_pays_debt_before_growing_xp():
    """+15 challenge XP against a 10-debt hole ends at debt 0 / xp 5+delta —
    never a straight xp_total += that teleports past the paydown contract."""
    earned, delta, new_xp, debt = _compute_xp(45, 0, _cfg(), day_number=50, previous_debt=10, bonus_xp=15)
    assert earned == 1  # band credit unchanged
    assert delta == 15  # net 0 day + 15 bonus
    assert debt == 0
    assert new_xp == 5


def test_challenge_bonus_credits_even_on_hold_days_debt_first():
    cfg = _cfg()
    cfg2 = copy.deepcopy(cfg)
    cfg2["pillars"]["movement"]["components"]["sessions"] = {"weight": 0.6}  # measured
    prev = {
        "character_level": 5,
        "pillar_movement": {"level": 5, "tier": "Foundation", "streak_above": 0, "streak_below": 0, "xp_total": 0, "xp_debt": 12},
    }
    data = {"date": "2026-08-02", "apple": {"steps": 9000}, "challenge_bonus_xp": {"movement": 20}}
    rec = compute_character_sheet(data, prev, {}, cfg2)
    mv = rec["pillar_movement"]
    assert mv["coverage_hold"] is True
    assert mv["xp_debt"] == 0  # 20 bonus pays the 12 hole first
    assert mv["xp_total"] == 8
    assert mv["challenge_bonus_xp"] == 20


# ══════════════════════════════════════════════════════════════════════════════
# #959 · Confirmed dark stretch: down-streak persists, buffer gives no shield
# ══════════════════════════════════════════════════════════════════════════════


def _down_pressure_state(level=30, streak_below=7, xp_buffer=0.0):
    return {
        "level": level,
        "tier": "Momentum",
        "streak_above": 0,
        "streak_below": streak_below,
        "xp_total": 0,
        "xp_buffer": xp_buffer,
    }


def test_dark_down_streak_persists_across_drops():
    state = evaluate_level_changes(
        "movement", 10.0, _down_pressure_state(streak_below=7), _cfg(), data_coverage=0.6, raw_score=5.0, presence_dark=True
    )
    assert state["level"] < 30
    assert state["streak_below"] == 8  # incremented, NOT reset to 0
    # Next dark day drops again immediately — no fresh 7-day re-arm.
    state2 = evaluate_level_changes("movement", 10.0, state, _cfg(), data_coverage=0.6, raw_score=5.0, presence_dark=True)
    assert state2["level"] < state["level"]


def test_engaged_down_streak_still_resets():
    """The anti-flip-flop reset is untouched for noisy engaged data."""
    state = evaluate_level_changes(
        "movement", 10.0, _down_pressure_state(streak_below=7), _cfg(), data_coverage=0.9, raw_score=12.0, presence_dark=False
    )
    assert state["level"] < 30
    assert state["streak_below"] == 0


def test_dark_bypasses_the_xp_buffer_shield():
    state = evaluate_level_changes(
        "movement",
        10.0,
        _down_pressure_state(streak_below=7, xp_buffer=40.0),
        _cfg(),
        data_coverage=0.6,
        raw_score=5.0,
        presence_dark=True,
    )
    assert state["level"] < 30  # a full buffer holds an ENGAGED dip, never a dark one


def test_engaged_buffer_still_shields():
    state = evaluate_level_changes(
        "movement",
        10.0,
        _down_pressure_state(streak_below=7, xp_buffer=40.0),
        _cfg(),
        data_coverage=0.9,
        raw_score=12.0,
        presence_dark=False,
    )
    assert state["level"] == 30


def test_buffer_fill_caps_at_config_cap():
    assert _roll_xp_buffer(35.0, 100, 120, 100, buffer_cap=40) == 40.0
    assert _roll_xp_buffer(None, 95, 95, 100, buffer_cap=40) == 40.0  # legacy seed also capped
    assert _roll_xp_buffer(40.0, 100, 90, 100, buffer_cap=40) == 30.0  # drains uncapped


# ══════════════════════════════════════════════════════════════════════════════
# #960 · Headline renormalizes over instrumented pillars
# ══════════════════════════════════════════════════════════════════════════════


def test_headline_excludes_never_instrumented_pillar():
    """Movement at L1 + relationships never instrumented: the headline follows
    movement alone instead of averaging in the frozen placeholder."""
    cfg = _cfg()
    prev = {
        "character_level": 1,
        "pillar_movement": {"level": 40, "tier": "Momentum", "streak_above": 0, "streak_below": 0, "xp_total": 0},
        "pillar_relationships": {"level": 1, "tier": "Foundation", "streak_above": 0, "streak_below": 0, "xp_total": 0},
    }
    rec = compute_character_sheet(_movement_data(), prev, {}, cfg)
    assert rec["pillar_relationships"]["not_instrumented"] is True
    assert "relationships" in rec["headline_excluded_pillars"]
    # weight 0.5/0.5: old math floor((40*.5 + 1*.5)) = 20; renormalized = 40
    assert rec["character_level"] == rec["pillar_movement"]["level"]


def test_headline_keeps_pillar_once_it_has_leveled():
    """A pillar that EARNED levels then went dark still counts — going dark
    drags honestly instead of vanishing from the mean."""
    cfg = _cfg()
    prev = {
        "character_level": 30,
        "pillar_movement": {"level": 40, "tier": "Momentum", "streak_above": 0, "streak_below": 0, "xp_total": 0},
        "pillar_relationships": {"level": 20, "tier": "Foundation", "streak_above": 0, "streak_below": 0, "xp_total": 0},
    }
    rec = compute_character_sheet(_movement_data(), prev, {}, cfg)
    assert rec["pillar_relationships"]["not_instrumented"] is True
    assert "relationships" not in rec["headline_excluded_pillars"]
    assert rec["character_level"] == 30  # floor((40*.5 + 20*.5))


# ══════════════════════════════════════════════════════════════════════════════
# #962 · Derived consistency inputs + data-driven vice conditions
# ══════════════════════════════════════════════════════════════════════════════


def _rec(date, raws):
    out = {"date": date}
    for p, r in raws.items():
        out[f"pillar_{p}"] = {"raw_score": r}
    return out


def test_streak_counts_consecutive_days_all_above_30():
    records = [
        _rec("2026-08-01", {"sleep": 55, "movement": 60, "nutrition": 45, "metabolic": 50, "mind": 40}),
        _rec("2026-08-02", {"sleep": 62, "movement": 33, "nutrition": 47, "metabolic": 52, "mind": 41}),
        _rec("2026-08-03", {"sleep": 58, "movement": 35, "nutrition": 49, "metabolic": 51, "mind": 44}),
    ]
    out = derive_consistency_inputs(records, "2026-08-04")
    assert out["streak_all_above_30th"] == 3


def test_streak_breaks_on_sub_30_day_and_on_gap():
    below = [
        _rec("2026-08-01", {"sleep": 55, "movement": 25, "nutrition": 45, "metabolic": 50, "mind": 40}),
        _rec("2026-08-02", {"sleep": 62, "movement": 33, "nutrition": 47, "metabolic": 52, "mind": 41}),
    ]
    assert derive_consistency_inputs(below, "2026-08-03")["streak_all_above_30th"] == 1
    gapped = [
        _rec("2026-08-01", {"sleep": 55, "movement": 60, "nutrition": 45, "metabolic": 50, "mind": 40}),
        # 08-02 missing entirely — a gap is not a floor held
        _rec("2026-08-03", {"sleep": 58, "movement": 35, "nutrition": 49, "metabolic": 51, "mind": 44}),
    ]
    assert derive_consistency_inputs(gapped, "2026-08-04")["streak_all_above_30th"] == 1


def test_weekend_weekday_ratio_needs_enough_of_both():
    # 2026-08-01 is a Saturday; build Mon-Sun x2 weeks ending Sun 08-09
    days = {
        "2026-08-01": 50,  # Sat
        "2026-08-02": 50,  # Sun
        "2026-08-03": 100,
        "2026-08-04": 100,
        "2026-08-05": 100,
        "2026-08-06": 100,
        "2026-08-07": 100,  # Mon-Fri
        "2026-08-08": 50,  # Sat
        "2026-08-09": 50,  # Sun
    }
    records = [_rec(d, {"sleep": v, "movement": v, "nutrition": v, "metabolic": v, "mind": v}) for d, v in days.items()]
    out = derive_consistency_inputs(records, "2026-08-10")
    assert out["weekend_weekday_ratio"] == 0.5
    sparse = records[:2]  # weekend only
    assert derive_consistency_inputs(sparse, "2026-08-10")["weekend_weekday_ratio"] is None


def test_no_records_returns_none_inputs():
    out = derive_consistency_inputs([], "2026-08-04")
    assert out["streak_all_above_30th"] is None
    assert out["weekend_weekday_ratio"] is None


def test_any_vice_streak_condition_is_data_driven():
    assert _evaluate_condition("any_vice_streak > 30", {}, vice_streaks={"alcohol": 45, "doom": 3}) is True
    assert _evaluate_condition("any_vice_streak > 30", {}, vice_streaks={"alcohol": 12}) is False
    assert _evaluate_condition("any_vice_streak > 30", {}, vice_streaks=None) is False


def test_vice_shield_fires_through_cross_pillar_effects():
    cfg = {
        "cross_pillar_effects": [
            {"name": "Vice Shield", "condition": "any_vice_streak > 30", "targets": {"mind": {"type": "multiplicative", "value": 0.03}}}
        ]
    }
    active, mods = compute_cross_pillar_effects({"mind": 50.0}, cfg, vice_streaks={"alcohol": 31})
    assert [e["name"] for e in active] == ["Vice Shield"]
    assert mods == {"mind": 0.03}
    active_none, mods_none = compute_cross_pillar_effects({"mind": 50.0}, cfg, vice_streaks=None)
    assert active_none == [] and mods_none == {}


# ══════════════════════════════════════════════════════════════════════════════
# Buddy engagement removal (#962, B-3 precedent)
# ══════════════════════════════════════════════════════════════════════════════


def test_buddy_engagement_component_is_gone():
    scores, details = ce.compute_relationships_raw({"buddy_freshness_days": 2}, {"pillars": {"relationships": {"components": {}}}})
    assert "buddy_engagement" not in details
