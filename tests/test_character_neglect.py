"""
tests/test_character_neglect.py — #913: the character sheet responds honestly
to neglect.

The audit story this file guards against: during 14 days of total manual-
logging silence (2026-06-26..07-09, /api/presence dark, gap_days 15) the
character LEVELED UP 8→13 with two tier-up celebrations while pillar raw
scores crashed (movement 54→9, mind 64→15). Four fixes:

  1. Up-gate scale bug — ``raw_score >= current_level + 1`` compared a 0-100
     daily score to a still-converging 1-100 level; now the day must perform
     at the TARGET level.
  2. Presence-driven atrophy — sustained dark presence decays behavioral-heavy
     pillars' level scores (leveling.neglect_decay), floored at the raw score.
  3. Visible XP bleed — the sub-zero shortfall accumulates as xp_debt instead
     of vanishing under the 0-floor.
  4. Deterministic character_mood — thriving/steady/fading/dormant, pure code.

Run with:   python3 -m pytest tests/test_character_neglect.py -v
"""

import os
import sys

# ── Add lambdas/ to import path ──
LAMBDAS_DIR = os.path.join(os.path.dirname(__file__), "..", "lambdas")
sys.path.insert(0, os.path.abspath(LAMBDAS_DIR))

from character_engine import (
    _behavioral_weight_share,
    _compute_xp,
    compute_character_mood,
    compute_character_sheet,
    compute_ema_level_score,
    evaluate_level_changes,
    neglect_decay_state,
)

# A realistic slice of the live config: Foundation streak gates, the graduated
# step bands, and the movement pillar's behavioral component mix.
CONFIG = {
    "pillars": {
        "movement": {
            "weight": 0.18,
            "ema_lambda": 0.9,
            "components": {
                "training_frequency": {"weight": 0.2, "behavioral": True},
                "zone2_adequacy": {"weight": 0.25, "behavioral": True},
                "training_load_balance": {"weight": 0.2},
                "progressive_overload": {"weight": 0.15},
                "movement_diversity": {"weight": 0.1, "behavioral": True},
                "daily_steps": {"weight": 0.1},
            },
        },
        "sleep": {
            "weight": 0.2,
            "ema_lambda": 0.85,
            "components": {
                "duration_vs_target": {"weight": 0.25},
                "efficiency": {"weight": 0.2},
            },
        },
    },
    "leveling": {
        "ema_lambda": 0.85,
        "ema_window_days": 21,
        "level_change_min_coverage": 0.5,
        "level_up_streak_days": 5,
        "level_down_streak_days": 7,
        "tier_up_streak_days": 7,
        "tier_down_streak_days": 10,
        "level_step_threshold": 10,
        "level_step_bands": [{"min_delta": 25, "step": 3}, {"min_delta": 10, "step": 2}],
        "xp_per_level": 100,
        "daily_xp_decay": 2,
        "xp_buffer_threshold": 20,
        "xp_debt_cap": 100,
        "neglect_decay": {"n_grace_days": 3, "rate": 0.98, "floor": 0, "min_behavioral_share": 0.3},
        "tier_streak_overrides": {
            "Foundation": {"up": 3, "down": 5, "tier_boundary_up": 5, "tier_boundary_down": 7},
        },
    },
    "tiers": [
        {"name": "Foundation", "min_level": 1, "max_level": 20},
        {"name": "Momentum", "min_level": 21, "max_level": 40},
        {"name": "Discipline", "min_level": 41, "max_level": 60},
        {"name": "Mastery", "min_level": 61, "max_level": 80},
        {"name": "Elite", "min_level": 81, "max_level": 100},
    ],
    "xp_bands": [
        {"min_raw_score": 80, "xp": 3},
        {"min_raw_score": 60, "xp": 2},
        {"min_raw_score": 40, "xp": 1},
        {"min_raw_score": 20, "xp": 0},
        {"min_raw_score": 0, "xp": -1},
    ],
    "cross_pillar_effects": [],
}


# ══════════════════════════════════════════════════════════════════════════════
# 1 · P0 regression — 14 days of behavioral silence must produce ZERO climbs
# ══════════════════════════════════════════════════════════════════════════════


def test_fourteen_dark_days_zero_level_up_zero_tier_up():
    """The exact audit scenario, replayed against the leveling loop: a pillar
    at level 8 with a healthy EMA history goes fully dark for 14 days (raw
    crashes to ~9-15, coverage stays above the hold threshold because absent
    behaviors ARE information). Before the fix, raw 9 beat ``current_level + 1``
    and the pillar climbed the whole stretch. Now: zero level_up, zero tier_up."""
    history = [60.0] * 14  # a genuinely good pre-silence fortnight
    state = {"level": 8, "tier": "Foundation", "streak_above": 2, "streak_below": 0, "xp_total": 850}
    dark_raws = [15.0, 12.0, 9.0, 11.0, 9.0, 10.0, 9.0, 13.0, 9.0, 9.0, 10.0, 9.0, 9.0, 9.0]

    events = []
    for raw in dark_raws:
        history.append(raw)
        level_score = compute_ema_level_score(history, CONFIG, "movement")
        result = evaluate_level_changes("movement", level_score, state, CONFIG, data_coverage=0.8, raw_score=raw)
        events.extend(result.get("events", []))
        state = {
            "level": result["level"],
            "tier": result["tier"],
            "streak_above": result["streak_above"],
            "streak_below": result["streak_below"],
            "xp_total": state["xp_total"],  # held constant — isolates the gate
        }

    assert [e for e in events if e["type"] == "level_up"] == []
    assert [e for e in events if e["type"] == "tier_up"] == []
    assert state["level"] <= 8  # never climbed; may honestly fall


def test_sixty_dark_days_zero_level_up_beyond_the_blend_floor():
    """#957: the 14-day guard above stops at exactly the horizon where the bug
    re-opens. In total silence the confidence blend floors the BLENDED raw at
    ~15.6 (0 performance at coverage 0.55), atrophy pins level_score at that
    floor, the EMA converges down to it, and from ~day 15-17 the old gate
    (round(15.6)=16 >= target 16) self-satisfied every single dark day. The
    fixed gate judges the UNBLENDED raw — exactly 0 in silence — so no dark
    day can support a level-up at ANY horizon. Full-orchestrator replay:
    level-8 pillar with a healthy history, then 60 days of total silence."""
    prev = {
        "character_level": 8,
        "pillar_movement": {"level": 8, "tier": "Foundation", "streak_above": 2, "streak_below": 0, "xp_total": 850},
    }
    histories = {"movement": [60.0] * 14, "sleep": [70.0] * 14}
    events = []
    for gap in range(1, 61):
        data = {"date": "2026-07-08", "engagement_state": _dark(gap)}  # NO data at all: behaviors absent, wearable off
        rec = compute_character_sheet(data, prev, histories, CONFIG)
        for p in ("movement", "sleep"):
            histories[p].append(rec[f"pillar_{p}"]["raw_score"])
        events.extend(rec["level_events"])
        prev = rec

    ups = [e for e in events if e["type"] in ("level_up", "tier_up", "character_level_up")]
    assert ups == [], ups
    assert rec["pillar_movement"]["level"] <= 8  # never climbed; may honestly fall


def test_fresh_character_never_logs_stays_level_one_forever():
    """#957's worst case: a fresh cycle-5 character that NEVER logs anything
    reached level 16 with 12 level_up celebrations in 60 days while mood read
    'dormant'. Now: level 1, zero celebrations, and never a level_up event on
    a dormant day — the honesty headline at any horizon."""
    prev = None
    histories = {"movement": [], "sleep": []}
    events, dormant_ups = [], []
    for gap in range(1, 76):
        data = {"date": "2026-07-08", "engagement_state": _dark(gap)}
        rec = compute_character_sheet(data, prev, histories, CONFIG)
        for p in ("movement", "sleep"):
            histories[p].append(rec[f"pillar_{p}"]["raw_score"])
        events.extend(rec["level_events"])
        if rec["character_mood"] == "dormant":
            dormant_ups.extend(e for e in rec["level_events"] if e["type"] == "level_up")
        prev = rec

    assert [e for e in events if e["type"] in ("level_up", "tier_up", "character_level_up")] == []
    assert dormant_ups == []
    assert rec["character_level"] == 1
    assert rec["pillar_movement"]["level"] == 1
    assert rec["character_mood"] == "dormant"


def test_up_gate_judges_unblended_raw_not_the_blend_floor():
    """Direct unit shape of #957: EMA converged to the blend floor (target 16),
    blended raw sits AT the floor (15.6 -> rounds to 16, the old gate passed),
    but the day actually measured 0. The gate must hold — forever."""
    prev = {"level": 8, "tier": "Foundation", "streak_above": 99, "streak_below": 0, "xp_total": 0}
    result = evaluate_level_changes("movement", 15.6, prev, CONFIG, data_coverage=0.55, raw_score=15.6, raw_score_unblended=0.0)
    assert result["level"] == 8
    assert result.get("events") == []
    assert result["streak_above"] == 99  # held, not grown — a silent day carries no up-signal


def test_up_gate_unblended_raw_still_allows_honest_climbs():
    """A genuinely-lived thin-coverage day is judged on what it MEASURED: a
    real 60-performance day at coverage 0.55 blends down to 56.9 (the blend
    pulls above-50 raws toward neutral), which the old gate would have held
    below a target of 60 — the unblended 60 passes. Uncertainty smoothing
    cuts both ways; performance credit follows the measurement."""
    prev = {"level": 30, "tier": "Momentum", "streak_above": 5, "streak_below": 0, "xp_total": 0}
    result = evaluate_level_changes("movement", 60.0, prev, CONFIG, data_coverage=0.55, raw_score=56.9, raw_score_unblended=60.0)
    assert result["level"] > 30


def test_up_gate_legacy_callers_fall_back_to_blended_raw():
    """Callers that don't pass raw_score_unblended keep the pre-#957 gate."""
    prev = {"level": 8, "tier": "Foundation", "streak_above": 5, "streak_below": 0, "xp_total": 0}
    result = evaluate_level_changes("movement", 26.0, prev, CONFIG, data_coverage=1.0, raw_score=30.0)
    assert result["level"] > 8


def test_up_gate_compares_raw_to_target_not_current_level():
    """Direct unit shape of the scale bug: level 8, EMA target 26, crashed raw 9.
    The old gate (9 >= 8+1) passed; the fixed gate (9 >= 26) must hold."""
    prev = {"level": 8, "tier": "Foundation", "streak_above": 5, "streak_below": 0, "xp_total": 0}
    result = evaluate_level_changes("movement", 26.0, prev, CONFIG, data_coverage=1.0, raw_score=9.0)
    assert result["level"] == 8
    assert result.get("events") == []


def test_up_gate_still_allows_honest_climbs():
    """A day genuinely lived at the target keeps climbing exactly as before."""
    prev = {"level": 8, "tier": "Foundation", "streak_above": 5, "streak_below": 0, "xp_total": 0}
    result = evaluate_level_changes("movement", 26.0, prev, CONFIG, data_coverage=1.0, raw_score=30.0)
    assert result["level"] > 8


# ══════════════════════════════════════════════════════════════════════════════
# 2 · P0 engagement-driven atrophy
# ══════════════════════════════════════════════════════════════════════════════


def _dark(gap_days, planned=False):
    return {"presence_class": "dark", "gap_days": gap_days, "planned_pause": planned}


def test_neglect_decay_state_grace_and_planned_pause():
    assert neglect_decay_state(None, CONFIG) is None
    assert neglect_decay_state({"presence_class": "present", "gap_days": 0}, CONFIG) is None
    assert neglect_decay_state(_dark(3), CONFIG) is None  # within grace
    assert neglect_decay_state(_dark(10, planned=True), CONFIG) is None  # sick/travel never decays
    d = neglect_decay_state(_dark(10), CONFIG)
    assert d is not None
    assert abs(d["multiplier"] - 0.98**7) < 1e-3  # rate ** (gap - grace)


def test_behavioral_weight_share():
    assert _behavioral_weight_share(CONFIG["pillars"]["movement"]) > 0.5
    assert _behavioral_weight_share(CONFIG["pillars"]["sleep"]) == 0.0


def _sheet_for_gap(gap_days, histories=None):
    """One compute_character_sheet run: no manual data (behaviors absent),
    sleep still measured by the wearable, presence dark at the given gap."""
    data = {
        "date": "2026-07-08",
        "sleep": {"sleep_duration_hours": 7.4, "sleep_performance": 88},
        "engagement_state": _dark(gap_days),
    }
    histories = histories or {"movement": [55.0] * 21, "sleep": [70.0] * 21}
    return compute_character_sheet(data, None, histories, CONFIG)


def test_ten_dark_days_level_score_strictly_decreasing_on_behavioral_pillar():
    """With raw-score histories held constant, the only moving part is the
    atrophy multiplier — 10 deepening dark days must drag the behavioral
    pillar's level_score strictly down, day over day."""
    level_scores = [_sheet_for_gap(g)["pillar_movement"]["level_score"] for g in range(4, 14)]
    assert all(b < a for a, b in zip(level_scores, level_scores[1:])), level_scores


def test_atrophy_tagged_on_pillar_and_floored_at_raw():
    rec = _sheet_for_gap(12)
    mv = rec["pillar_movement"]
    assert mv["neglect_decay"] is not None
    assert mv["neglect_decay"]["applied"] is True
    assert mv["level_score"] >= mv["raw_score"]  # the day itself is the floor
    # sleep is device-measured — never atrophies
    assert rec["pillar_sleep"]["neglect_decay"] is None


def test_no_atrophy_when_engaged():
    data = {
        "date": "2026-07-08",
        "sleep": {"sleep_duration_hours": 7.4, "sleep_performance": 88},
        "engagement_state": {"presence_class": "present", "gap_days": 0},
    }
    rec = compute_character_sheet(data, None, {"movement": [55.0] * 21, "sleep": [70.0] * 21}, CONFIG)
    assert rec["pillar_movement"]["neglect_decay"] is None
    assert rec["neglect_decay"] is None


# ══════════════════════════════════════════════════════════════════════════════
# 3 · P1 visible XP bleed
# ══════════════════════════════════════════════════════════════════════════════


def test_xp_debt_accumulates_across_dark_days():
    """Once xp_total hits 0, further bad days deepen a VISIBLE debt."""
    xp, debt = 0, 0
    debts = []
    for _ in range(5):  # raw 10 → band -1, decay 2 → -3/day
        _, _, xp, debt = _compute_xp(10, xp, CONFIG, previous_debt=debt)
        debts.append(debt)
    assert debts == [3, 6, 9, 12, 15]
    assert xp == 0


def test_good_days_pay_debt_before_growing_xp():
    _, _, xp, debt = _compute_xp(85, 0, CONFIG, previous_debt=6)  # +3 - 2 = +1
    assert (xp, debt) == (0, 5)
    _, _, xp, debt = _compute_xp(85, 0, CONFIG, previous_debt=1)
    assert (xp, debt) == (0, 0)
    _, _, xp, debt = _compute_xp(85, 0, CONFIG, previous_debt=0)
    assert (xp, debt) == (1, 0)


def test_xp_debt_capped():
    _, _, xp, debt = _compute_xp(10, 0, CONFIG, previous_debt=99)
    assert debt == 100  # leveling.xp_debt_cap — the hole stays climbable
    assert xp == 0


def test_xp_debt_surfaces_in_record_payload():
    rec = _sheet_for_gap(10)
    assert "xp_debt" in rec["pillar_movement"]
    assert "character_xp_debt" in rec
    # day 1 from zero prior state: raw ~0-ish behavioral pillar bleeds
    assert rec["character_xp_debt"] >= 0


# ══════════════════════════════════════════════════════════════════════════════
# 4 · P2 deterministic character_mood
# ══════════════════════════════════════════════════════════════════════════════


def test_mood_dormant_on_dark_presence():
    v = compute_character_mood(_dark(15), {"movement": 9.0}, {"movement": [50.0] * 7})
    assert v["mood"] == "dormant"
    assert v["inputs"]["gap_days"] == 15


def test_mood_fading_on_quiet_presence_or_falling_trend():
    v = compute_character_mood({"presence_class": "quiet", "gap_days": 3}, {"m": 40.0}, {"m": [50.0] * 7})
    assert v["mood"] == "fading"
    falling = {"m": [70.0, 70.0, 70.0, 70.0, 50.0, 45.0, 40.0]}
    v = compute_character_mood({"presence_class": "present", "gap_days": 0}, {"m": 40.0}, falling)
    assert v["mood"] == "fading"


def test_mood_thriving_needs_presence_trend_and_level():
    rising = {"m": [50.0, 50.0, 52.0, 53.0, 60.0, 62.0, 65.0]}
    v = compute_character_mood({"presence_class": "present", "gap_days": 0}, {"m": 65.0}, rising)
    assert v["mood"] == "thriving"


def test_mood_steady_default_and_no_engagement():
    v = compute_character_mood(None, {"m": 50.0}, {"m": [50.0] * 7})
    assert v["mood"] == "steady"


def test_mood_rides_the_daily_record():
    rec = _sheet_for_gap(15)
    assert rec["character_mood"] == "dormant"
    assert rec["character_mood_inputs"]["presence_class"] == "dark"
