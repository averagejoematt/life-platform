"""tests/test_character_final_amendments_6293.py — the four final #6293 amendments + the XP proof (owner ruling 2026-11-26).

"Finish the four outstanding scoring-method amendments and use the exact final implementation for the replay." Governing
principle: "Inactivity, missing journals or appropriate rest should not automatically imply psychological deterioration
or generate punitive character mechanics." Each amendment is pinned in BOTH directions, and its module switch is shown to
restore the pre-amendment rule (the graft a method ladder uses). The XP proof answers the owner's question whether
removing XP debt suppressed adjustments generally: it did not — a measured low day still drains the shield and a level
still falls on sustained measured evidence.

Every fixture is synthetic.
"""

import copy
import json
import math
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "lambdas"))

from health import (
    character_engine as ce,  # noqa: E402
    character_public,  # noqa: E402
)

CONFIG = json.loads((REPO / "config" / "character_sheet.json").read_text(encoding="utf-8"))
DAY = "2026-10-20"
WINDOW = [f"2026-10-{d:02d}" for d in range(14, 21)]  # the 7 dates ending DAY


@pytest.fixture
def switch(monkeypatch):
    def _set(name, value):
        monkeypatch.setattr(ce, name, value)

    return _set


# ══════════════════════════════════════════════════════════════════════════════
# 1 · planned_rest — a recorded planned pause leaves Movement's count windows
# ══════════════════════════════════════════════════════════════════════════════


def _move(planned=None, **over):
    data = {"date": DAY, "strava_7d": [], "hevy_7d": [], "hevy_workout_days_7d": ["2026-10-15", "2026-10-17"]}
    if planned is not None:
        data["planned_rest_days_7d"] = planned
    data.update(over)
    return ce.compute_movement_raw(data, CONFIG)


def test_planned_rest_prorates_the_window_targets():
    target = CONFIG["pillars"]["movement"]["components"]["strength_sessions"]["target_days_week"]
    _r, full = _move()
    _r, rest = _move(planned=WINDOW[:3])  # 3 of 7 days a recorded sick/travel day
    perfect = (target + 1) / target
    assert full["strength_sessions"]["score"] == ce._pct_of_target(2, target, perfect)
    assert rest["strength_sessions"]["score"] == ce._pct_of_target(2, target * 4 / 7, perfect)
    assert rest["strength_sessions"]["score"] > full["strength_sessions"]["score"]
    assert rest["_planned_rest"]["days"] == 3
    assert rest["_planned_rest"]["pre_rest_details"]["strength_sessions"] == full["strength_sessions"]


def test_a_week_of_planned_rest_is_unknown_not_zero():
    raw, d = _move(planned=WINDOW)
    for c in ce.MOVEMENT_WINDOW_COMPONENTS:
        assert d[c]["score"] is None, c
    assert d["_planned_rest"]["days"] == 7 and "_absent_behaviors" in d and not d["_absent_behaviors"]


def test_unplanned_inactivity_stays_a_measured_zero():
    _r, d = _move(planned=[], hevy_workout_days_7d=[])
    assert d["training_frequency"]["score"] == 0.0 and d["strength_sessions"]["score"] == 0.0
    assert "_planned_rest" not in d
    _r, outside = _move(planned=["2026-10-01", "2026-10-21"], hevy_workout_days_7d=[])  # outside the window
    assert outside["training_frequency"]["score"] == 0.0 and "_planned_rest" not in outside


def test_planned_rest_switch_off_is_the_pre_amendment_rule(switch):
    _r, on = _move(planned=WINDOW[:3])
    switch("PLANNED_REST_PRORATES", False)
    raw_off, off = _move(planned=WINDOW[:3])
    assert (raw_off, off) == _move()
    assert off != on


def test_the_public_method_restores_the_day_without_the_private_rest_record():
    raw, d = _move(planned=WINDOW[:3])
    pub_raw, pub = character_public.without_private_modifiers(raw, d)
    full_raw, full = _move()
    assert (pub_raw, pub) == (full_raw, full)


# ══════════════════════════════════════════════════════════════════════════════
# 2 · lab_ageing — age tapers the WEIGHT, never the score
# ══════════════════════════════════════════════════════════════════════════════

LABS = {"date": "2026-06-01", "apob": 85, "hba1c": 5.2, "ldl": 95}


def _metabolic(day, labs=LABS, **over):
    data = {"date": day, "labs_latest": labs, "whoop": {"resting_heart_rate": 55}}
    data.update(over)
    return ce.compute_metabolic_raw(data, CONFIG)


def test_an_ageing_lab_keeps_its_score_and_loses_weight():
    _r, fresh = _metabolic("2026-06-15")
    _r, aged = _metabolic("2026-09-14")  # ~105 days: the [F-07] curve's factor is between 0 and 0.5
    assert aged["lab_biomarkers"]["score"] == fresh["lab_biomarkers"]["score"]
    f = ce.lab_evidence_factor(LABS, "2026-09-14")
    assert 0 < f < 0.5 and aged["lab_biomarkers"]["evidence_weight"] == f
    assert aged["_data_coverage"] < fresh["_data_coverage"]  # the aged share is unknown: coverage drops
    # the measured performance does not decline with age: both readings are good-markers + RHR, unblended
    rhr = ce._in_range_score(55, 40, 65, buffer=0.4)
    w_lab, w_rhr = CONFIG["pillars"]["metabolic"]["components"]["lab_biomarkers"]["weight"], 0.15
    lab = fresh["lab_biomarkers"]["score"]
    assert aged["_raw_unblended"] == round((lab * w_lab * f + rhr * w_rhr) / (w_lab * f + w_rhr), 1)


def test_past_the_horizon_the_lab_is_unknown_and_leaves_sum_and_coverage():
    _r, d = _metabolic("2026-12-15")  # 197 days
    assert d["lab_biomarkers"]["score"] is None
    assert d["_raw_unblended"] == round(ce._in_range_score(55, 40, 65, buffer=0.4), 1)


def test_lab_ageing_switch_off_is_the_pre_amendment_score_decay(switch):
    switch("LAB_AGE_TAPERS_WEIGHT", False)
    _r, fresh = _metabolic("2026-06-15")
    _r, aged = _metabolic("2026-09-14")
    assert aged["lab_biomarkers"]["score"] < fresh["lab_biomarkers"]["score"]
    assert "evidence_weight" not in aged["lab_biomarkers"]
    _r, expired = _metabolic("2026-12-15")
    assert expired["lab_biomarkers"]["score"] == 0.0


# ══════════════════════════════════════════════════════════════════════════════
# 3 · rest_day_completeness — a day with no activity does not expect a Strava row
# ══════════════════════════════════════════════════════════════════════════════

ALL_BUT_STRAVA = {"whoop": True, "macrofactor": True, "apple": True, "strava": False, "habitify": True}


def test_a_rest_day_does_not_expect_strava():
    assert ce.data_completeness_pct(ALL_BUT_STRAVA, activity_elsewhere=False) == 100.0


def test_a_missing_sync_on_a_training_day_still_counts_missing():
    assert ce.data_completeness_pct(ALL_BUT_STRAVA, activity_elsewhere=True) == 80.0


def test_a_strava_row_that_arrived_always_counts_and_silence_is_zero():
    assert ce.data_completeness_pct(dict(ALL_BUT_STRAVA, strava=True), activity_elsewhere=False) == 100.0
    nothing = dict.fromkeys(ALL_BUT_STRAVA, False)
    assert ce.data_completeness_pct(nothing, activity_elsewhere=False) == 0.0  # compute_consistency_raw reads 0 as unknown
    assert ce.data_completeness_pct({}, activity_elsewhere=False) is None


def test_completeness_switch_off_is_the_pre_amendment_rule(switch):
    switch("REST_DAY_COMPLETENESS", False)
    assert ce.data_completeness_pct(ALL_BUT_STRAVA, activity_elsewhere=False) == 80.0


# ══════════════════════════════════════════════════════════════════════════════
# 4 · mood_label_presence — silence is "unavailable", decline needs measurement
# ══════════════════════════════════════════════════════════════════════════════

FLAT = {"m": [60.0] * 7}
FALLING = {"m": [70.0, 70.0, 70.0, 70.0, 50.0, 45.0, 40.0]}


@pytest.mark.parametrize("presence", ["dark", "quiet"])
def test_logging_silence_reads_unavailable(presence):
    v = ce.compute_character_mood({"presence_class": presence, "gap_days": 6}, {"m": 60.0}, FLAT)
    assert v["mood"] == ce.MOOD_UNAVAILABLE == "unavailable"


def test_fading_needs_a_measured_fall_and_dormant_is_never_produced():
    assert ce.compute_character_mood({"presence_class": "dark", "gap_days": 6}, {"m": 40.0}, FALLING)["mood"] == "fading"
    assert ce.compute_character_mood({"presence_class": "present", "gap_days": 0}, {"m": 40.0}, FALLING)["mood"] == "fading"
    for presence in ("present", "light", "quiet", "dark"):
        for hist in (FLAT, FALLING, {"m": [50.0, 50.0, 52.0, 53.0, 60.0, 62.0, 65.0]}):
            assert ce.compute_character_mood({"presence_class": presence}, {"m": 60.0}, hist)["mood"] != "dormant"


def test_mood_switch_off_is_the_pre_amendment_rule(switch):
    switch("MOOD_NOT_OBSERVED", False)
    assert ce.compute_character_mood({"presence_class": "dark"}, {"m": 60.0}, FLAT)["mood"] == "dormant"
    assert ce.compute_character_mood({"presence_class": "quiet"}, {"m": 60.0}, FLAT)["mood"] == "fading"


def test_the_site_reader_knows_the_label():
    js = (REPO / "site" / "assets" / "js" / "evidence_character.js").read_text(encoding="utf-8")
    assert '"unavailable"' in js and 'if (m === "dormant") return "unavailable";' in js
    assert "levels below are decaying" not in js


# ══════════════════════════════════════════════════════════════════════════════
# XP proof — removing debt did not suppress adjustments generally
# ══════════════════════════════════════════════════════════════════════════════


def test_every_band_verdict_still_exists_and_only_its_positive_part_credits():
    verdicts = {raw: ce.xp_day_verdict(raw, CONFIG) for raw in (90, 70, 50, 30, 10)}
    assert verdicts == {90: 2, 70: 1, 50: 0, 30: -1, 10: -2}
    for raw, v in verdicts.items():
        earned, delta, new_xp, debt = ce._compute_xp(raw, 50, CONFIG)
        assert (earned, new_xp, debt) == (max(0, v), 50 + max(0, v), 0)
        assert ce.xp_shield_delta(raw, False, 0, CONFIG) == v  # the negative part still acts — on the shield
        assert ce.xp_shield_delta(raw, True, 0, CONFIG) == 0  # a held day: no signal, no movement


def test_a_level_still_falls_on_sustained_measured_evidence():
    """Synthetic: a Momentum pillar at level 30 with a full shield, then measured days at raw 10. The shield drains
    by the verdict (-2/day), the down-streak builds, and the level falls — while XP never drops and no debt accrues."""
    leveling = CONFIG["leveling"]
    state = {"level": 30, "tier": "Momentum", "streak_above": 0, "streak_below": 0, "xp_total": 400, "xp_buffer": 40.0}
    falls, buffers, xps = [], [], []
    for _day in range(30):
        ls = ce.evaluate_level_changes("sleep", 10.0, state, CONFIG, data_coverage=1.0, raw_score=10.0, raw_score_unblended=10.0)
        _e, _d, xp, debt = ce.pillar_xp_transition(10.0, state["xp_total"], 0, 0, bool(ls["coverage_hold"]), CONFIG)
        buf = ce._roll_xp_buffer(
            state["xp_buffer"],
            state["xp_total"],
            state["xp_total"] + ce.xp_shield_delta(10.0, False, 0, CONFIG),
            100,
            leveling["xp_buffer_cap"],
        )
        falls += [e for e in ls["events"] if e["type"] == "level_down"]
        assert debt == 0
        state = dict(ls, xp_total=xp, xp_buffer=buf)
        buffers.append(buf)
        xps.append(xp)
    assert falls, "a sustained measured decline must still lower the level"
    assert state["level"] < 30
    assert buffers[0] < 40 and min(buffers) == 0  # the shield drained
    assert xps == [400] * 30  # XP itself never fell


def test_the_same_series_with_no_evidence_moves_nothing():
    """The contrast: the identical days with no evidence (coverage held) move no level, shield or XP."""
    state = {"level": 30, "tier": "Momentum", "streak_above": 0, "streak_below": 0, "xp_total": 400, "xp_buffer": 40.0}
    for _day in range(30):
        ls = ce.evaluate_level_changes("sleep", 10.0, state, CONFIG, data_coverage=0.2, raw_score=10.0)
        assert ls["coverage_hold"] is True
        _e, _d, xp, _debt = ce.pillar_xp_transition(10.0, 400, 0, 0, True, CONFIG)
        buf = ce._roll_xp_buffer(40.0, 400, 400 + ce.xp_shield_delta(10.0, True, 0, CONFIG), 100, 40)
        assert (ls["level"], xp, buf) == (30, 400, 40.0)
        state = dict(ls, xp_total=xp, xp_buffer=buf)


def test_a_full_chain_falls_on_measured_poor_sleep():
    """End to end through compute_character_sheet: a good fortnight, then measured poor nights — the Sleep level falls
    and the record carries no debt."""
    good = {"sleep_duration_hours": 8.2, "sleep_efficiency_pct": 93, "deep_sleep_pct": 0.2, "rem_sleep_pct": 0.23}
    poor = {"sleep_duration_hours": 3.0, "sleep_efficiency_pct": 55, "deep_sleep_pct": 0.04, "rem_sleep_pct": 0.05}
    from datetime import date, timedelta

    prev, hist, peak, last = None, {}, 0, None
    for i in range(150):  # 80 good nights climb the level past what the poor nights measure (raw ~36), then 70 poor ones
        day = (date(2026, 9, 6) + timedelta(days=i)).isoformat()
        rec = ce.compute_character_sheet({"date": day, "sleep": good if i < 80 else poor}, prev, hist, CONFIG)
        for k, v in rec.items():
            if k.startswith("pillar_") and isinstance(v, dict) and v.get("raw_score") is not None and not ce.day_is_held(v):
                hist.setdefault(k[7:], []).append(v["raw_score"])
        peak = max(peak, rec["pillar_sleep"]["level"])
        assert rec["character_xp_debt"] == 0
        prev, last = rec, rec
    assert peak > 1 and last["pillar_sleep"]["level"] < peak
    assert not math.isnan(last["pillar_sleep"]["level_score"])


def test_the_engine_keeps_every_entry_point_the_stacks_use():
    for name in (
        "UNINSTRUMENTED_PILLARS",
        "day_is_held",
        "xp_shield_delta",
        "xp_day_verdict",
        "compute_character_sheet",
        "pillar_xp_transition",
    ):
        assert hasattr(ce, name), name
    assert hasattr(character_public, "consistency_inputs")
    assert copy.deepcopy(ce.HABIT_TWO_STATE_COMPONENTS) == ("t0_habit_compliance", "t1_habit_compliance")
