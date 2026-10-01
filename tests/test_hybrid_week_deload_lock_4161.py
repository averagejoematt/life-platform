"""tests/test_hybrid_week_deload_lock_4161.py — the 2026-09-24 red team's rulings, as fixtures (#4161).

WHY THIS FILE EXISTS

An evidence red team (S&C coach, tendon physio, obesity/body-composition researcher, sport
scientist) reviewed v0.4's week semantics and #4149's critic constants; the owner approved its
recommendations on 2026-09-24, plus ruling "B" on the rate target the same day. Every rule gets a
fixture AND a mutation control that shows the fixture can fail:

  1. HYBRID WEEK — a program week advances only when its 4-session cycle is complete AND >= 7
     Pacific days have passed since the previous advance (Kubo 2010; Bohm 2015). The served
     position names its basis. The ramp, the `not_before_week` gate and the block read it.
  2. DELOAD + LOCK — one pre-planned deload at the LATER of week 6 or the block lock (2026-11-04),
     −40 % sets for 7 days, loads held, never a week off (Coleman 2024); the lock is a guard the
     engine reads, and a structural edit before the date reds here.
  3. CRITICS — (i) the stale-lift cap scales with the gap (Nosaka 2001; Chen 2012); (ii) the
     fatigue trigger is performance or readiness, not a loaded-day count (Bell 2023; Rogerson
     2024; Kataoka 2022; Yang 2018), −30 % sets for one session, plus the 48 h same-region guard;
     (iii) the advocate's "+1 set" is dropped (Roth 2023) — held in test_critic_determinism_4149.py.
  4. RULING "B" — the served rate target is conditional on protein adherence (Helms 2014).
"""

from __future__ import annotations

import os
import pathlib
import sys
from unittest.mock import patch

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "lambdas"))

os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")

from coach import (
    critics as c,  # noqa: E402
    critics_fatigue as cf,  # noqa: E402
)
from common.pacific_time import pacific_today, shift_day_key  # noqa: E402
from training import owner_redlines, plan_engine, program_structure, session_sequence  # noqa: E402

START = "2026-09-24"


def lift(day: str, name: str = "Linear Leg Press", wid: str | None = None) -> dict:
    # #4312: `name` plus a bench set, so the generic lift reaches an anchor muscle of whichever role it takes
    return {
        "date": day,
        "sk": f"DATE#{day}#WORKOUT#{wid or day}",
        "source_workout_id": wid or day,
        "exercises": [
            {"name": name, "sets": [{"type": "normal", "weight_kg": 90, "reps": 5}]},
            {"name": "Bench Press (Barbell)", "sets": [{"type": "normal", "weight_kg": 60, "reps": 5}]},
        ],
    }


def daily(n: int, start: str = START, every: int = 1) -> list[dict]:
    return [lift(shift_day_key(start, i * every)) for i in range(n)]


# ── 1. the hybrid week ───────────────────────────────────────────────────────────────
def test_eight_sessions_in_eight_days_never_reach_week_3():
    rows = daily(8)  # 09-24 .. 10-01
    e = session_sequence.next_session("2026-10-02", rows)
    assert e["week"] == 2 and e["completed_sessions"] == 8
    # and two logs a day for six days are SIX sessions, still week 1
    doubled = [lift(shift_day_key(START, i), wid=f"a{i}") for i in range(6)] + [
        lift(shift_day_key(START, i), wid=f"b{i}") for i in range(6)
    ]
    e = session_sequence.next_session("2026-09-30", doubled)
    assert (e["completed_sessions"], e["week"], e["advance_blocked_by"]) == (6, 1, "calendar_floor")


def test_mutation_control_a_session_counted_week_reaches_week_3():
    with patch.dict(session_sequence.WEEK_RULE, {"floor_days": 0}):
        assert session_sequence.next_session("2026-10-02", daily(8))["week"] == 3


def test_the_week_waits_for_both_the_cycle_and_the_calendar():
    # slow pace — a session every 3 days: 4 sessions take 9 days, so the CYCLE binds and week 2 opens on session 5
    slow = daily(4, every=3)  # 09-24, 27, 30, 10-03
    e = session_sequence.next_session("2026-10-04", slow)
    assert (e["week"], e["session_in_week"], e["advance_blocked_by"]) == (2, 1, None)
    three = daily(3, every=3)
    e = session_sequence.next_session("2026-10-04", three)
    assert (e["week"], e["session_in_week"], e["advance_blocked_by"]) == (1, 4, None), "cycle incomplete — not a floor block"


def test_the_served_position_names_its_basis_and_constraint_block_carries_it():
    rows = daily(4)
    e = session_sequence.next_session("2026-09-28", rows)
    b = e["week_basis"]
    assert (b["sessions_completed"], b["sessions_in_prior_week_state"], b["week_opened_on"], b["days_since_last_advance"]) == (
        4,
        4,
        START,
        4,
    )
    assert (b["advance_blocked_by"], b["next_advance_earliest"], b["floor_days"]) == ("calendar_floor", "2026-10-01", 7)
    assert (e["days_since_last_advance"], e["advance_blocked_by"]) == (4, "calendar_floor")
    assert "extra session 5" in e["label"] and "until 2026-10-01" in e["label"]
    block = plan_engine.constraint_block(date="2026-09-28", block_workouts=rows)
    assert block["session"]["week_basis"] == b and block["program_week"] == 1
    e = session_sequence.next_session("2026-10-01", rows)
    assert e["week"] == 2 and e["week_basis"]["advanced_here"] is True and e["week_basis"]["days_since_last_advance"] == 7


def test_the_week_rule_carries_its_provenance():
    r = session_sequence.WEEK_RULE
    assert r["floor_days"] == 7 and r["provenance"] == "population-derived" and r["stated"] == "2026-09-24"
    assert "Kubo 2010" in r["evidence"] and "10.1519/JSC.0b013e3181c865e2" in r["evidence"]
    assert "Bohm 2015" in r["evidence"] and "10.1186/s40798-015-0009-9" in r["evidence"]


def test_the_block_counter_reads_the_hybrid_week():
    rows = daily(45)  # daily: weeks open every 7 days, week 7 (block 2) opens on day 42 = 11-05
    assert session_sequence.block_boundaries(rows, shift_day_key(START, 45)) == ["2026-11-05"]
    assert session_sequence.next_session(shift_day_key(START, 45), rows)["block"] == 2


# ── 2. the deload and the lock ───────────────────────────────────────────────────────
def test_a_week_6_before_the_lock_date_does_not_deload():
    rows = daily(35)  # daily: week 6 opens 10-29 (day 35)
    e = session_sequence.next_session("2026-10-29", rows)
    assert (e["week"], e["deload"]) == (6, False)
    assert session_sequence.next_session("2026-11-03", daily(40))["deload"] is False


def test_the_deload_opens_on_the_lock_date_and_runs_seven_days():
    on = [p for p in session_sequence.preview(60) if p["deload"]]
    assert [p["date"] for p in on][:7] == [shift_day_key("2026-11-04", i) for i in range(7)]
    assert on[0]["week"] == 6 and on[0]["deload_window"] == {"started_on": "2026-11-04", "days": 7}
    e = session_sequence.next_session("2026-11-04", daily(41))
    assert e["deload"] is True and "DELOAD" in e["label"]
    assert e["deload_plan"]["sets_pct"] == -40 and e["deload_plan"]["not_before"] == "2026-11-04"
    assert session_sequence.next_session("2026-11-11", daily(48))["deload"] is False


def test_at_a_slower_pace_the_deload_waits_for_week_6():
    pv = session_sequence.preview(40, every_days=3)  # 4 sessions / 9 days: week 6 opens well after 11-04
    first = next(p for p in pv if p["deload"])
    assert first["week"] == 6 and first["session_in_week"] == 1 and first["date"] > "2026-11-04"


def test_mutation_control_an_unenforced_lock_deloads_in_week_6_before_it():
    with patch.dict(program_structure.BLOCK_LOCK, {"locked_until": "2026-10-01"}):
        first = next(p for p in session_sequence.preview(60) if p["deload"])
    assert first["date"] == "2026-10-29" and first["week"] == 6


def test_the_deload_is_minus_40_loads_held_never_a_week_off():
    dl = owner_redlines.REDLINES["lifting_sessions_per_wk"]["deload"]
    assert (dl["sets_pct"], dl["days"], dl["loads"], dl["week_off"], dl["stated"]) == (-40, 7, "held", False, "2026-09-24")
    assert "Coleman 2024" in dl["evidence"] and "e16777" in dl["evidence"]
    for role in program_structure.SESSION_TEMPLATES:
        rx = program_structure.session_prescription_for_role(role, deload=True)
        assert rx["deload_trim"]["pct"] == -40 and rx["deload_trim"]["loads"] == "held"
        assert rx["total_sets"] >= 1 and all(len(e["sets"]) >= 1 for e in rx["exposures"]), "a deload is lighter, never a week off"


def test_no_structural_edit_before_the_lock_date():
    """THE refusal: before 2026-11-04 the v0.4 structure (split, order, templates, accessories) must
    fingerprint to what was recorded at the lock. Loads, deloads, catalog keys are not structure."""
    state = session_sequence.block_lock_state(pacific_today())
    if pacific_today() < program_structure.BLOCK_LOCK["locked_until"]:
        assert state["state"] == "locked", state.get("refusal")
    assert session_sequence.block_lock_state("2026-11-03")["recorded_fingerprint"] == program_structure.BLOCK_LOCK["structure_fingerprint"]


def test_mutation_control_a_structural_edit_is_flagged_on_the_served_session():
    with patch.dict(program_structure.SESSION_TEMPLATES["lower_heavy"], {"accessories": ["leg_press"]}):
        state = session_sequence.block_lock_state("2026-10-10")
        e = session_sequence.next_session("2026-10-10", [])
        after = session_sequence.block_lock_state("2026-11-04")
    assert state["state"] == "violated" and "block lock" in state["refusal"]
    assert e["block_lock"]["state"] == "violated"
    assert after["state"] == "open"


# ── 3(i). the stale-lift cap scales with the gap ───────────────────────────────────────
TARGET = "2026-10-10"


def _days_ago(*ns: int) -> list[str]:
    return [shift_day_key(TARGET, -n) for n in ns]


def test_a_five_month_gap_caps_exposure_1_only():
    first = cf.stale_exposure(_days_ago(150, 160), TARGET, window_start=shift_day_key(TARGET, -400))
    assert (first["exposure"], first["gap_class"], first["gap_days"], cf.stale_cap(first)) == (1, "short", 150, 2)
    second = cf.stale_exposure(_days_ago(3, 153), TARGET, window_start=shift_day_key(TARGET, -400))
    assert (second["exposure"], second["gap_class"], cf.stale_cap(second)) == (2, "short", None)


def test_a_seven_month_gap_caps_exposures_1_to_3():
    w = shift_day_key(TARGET, -400)
    caps = [cf.stale_cap(cf.stale_exposure(_days_ago(*back, 213), TARGET, window_start=w)) for back in ((), (6,), (6, 4), (6, 4, 2))]
    assert caps == [2, 2, 3, None]
    assert cf.stale_exposure([], TARGET, window_start=w)["gap_class"] == "long", "never trained is the long class"


def test_a_current_lift_is_not_a_return():
    w = shift_day_key(TARGET, -400)
    weekly = _days_ago(*range(3, 400, 7))
    info = cf.stale_exposure(weekly, TARGET, window_start=w)
    assert info["gap_class"] == "none" and cf.stale_cap(info) is None


def test_mutation_control_a_six_month_line_moved_out_uncaps_exposure_2():
    w = shift_day_key(TARGET, -400)
    with patch.object(cf, "STALE_LONG_GAP_DAYS", 400):
        assert cf.stale_cap(cf.stale_exposure(_days_ago(6, 213), TARGET, window_start=w)) is None


def test_the_joints_packet_applies_the_scaled_cap():
    d = {
        "total_sets": 8,
        "exercises": [
            {"idx": 0, "label": "Squat", "n_sets": 4, "n_working_sets": 4, "top_weight_lbs": 135.0, "to_failure": False, "axial": None},
            {"idx": 1, "label": "Row", "n_sets": 4, "n_working_sets": 4, "top_weight_lbs": 100.0, "to_failure": False, "axial": None},
        ],
    }
    stale = {0: {"exposure": 3, "gap_class": "long", "gap_days": 213}, 1: {"exposure": 2, "gap_class": "short", "gap_days": 150}}
    p = c.build_joints_packet(
        d,
        pain_by_idx={},
        days_since_by_idx={0: 2, 1: 3},
        loaded_lifting_streak=1,
        pain_layer_status="ok",
        stale_by_idx=stale,
    )
    f0 = next(f for f in p["flags"] if f["metric"] == "days_since_movement[0]")
    assert (f0["severity"], f0["field"], f0["to"], f0["governed"]) == ("change", "exercises[0].set_count", 3, True)
    assert not [f for f in p["flags"] if f["metric"] == "days_since_movement[1]"], "exposure 2 after a short gap is uncapped"


def test_the_stale_constants_carry_their_provenance():
    assert cf.STALE_CAPS == {"short": {1: 2}, "long": {1: 2, 2: 2, 3: 3}}
    assert "Nosaka 2001" in cf.STALE_PROVENANCE["evidence"] and "Chen 2012" in cf.STALE_PROVENANCE["evidence"]
    assert (
        "the first three exposures of a novel-again pattern"
        in owner_redlines.REDLINES["lifting_sessions_per_wk"]["gain_rule"]["refused_when"]
    )


# ── 3(ii). the fatigue trigger ─────────────────────────────────────────────────────────
def _hist(date: str, lbs: float, rpe: float | None = 8.0) -> dict:
    return {"date": date, "best_weight": lbs, "sets": [{"weight_lbs": lbs, "rpe": rpe}]}


ROLES = {"2026-09-24": "upper_heavy", "2026-09-28": "upper_heavy", "2026-10-02": "upper_heavy", "2026-09-26": "upper_volume"}


def test_two_consecutive_same_role_drops_at_target_rpe_trigger():
    tops = [_hist("2026-09-24", 200), _hist("2026-09-26", 150), _hist("2026-09-28", 188), _hist("2026-10-02", 176)]
    p = cf.performance_drop(tops, ROLES, "upper_heavy")
    assert p["state"] == "triggered" and p["drop_pct"] == [6.0, 12.0] and p["reference"] == {"date": "2026-09-24", "top_lbs": 200}
    assert p["exposures"][0]["top_lbs"] == 200, "the volume-day 150 is never compared with a heavy day"


def test_one_drop_or_a_drop_below_target_rpe_does_not_trigger():
    one = [_hist("2026-09-24", 200), _hist("2026-09-28", 200), _hist("2026-10-02", 188)]
    assert cf.performance_drop(one, ROLES, "upper_heavy")["state"] == "clear"
    easy = [_hist("2026-09-24", 200), _hist("2026-09-28", 188, rpe=6), _hist("2026-10-02", 176)]
    assert cf.performance_drop(easy, ROLES, "upper_heavy")["state"] == "clear"
    unlogged = [_hist("2026-09-24", 200), _hist("2026-09-28", 188, rpe=None), _hist("2026-10-02", 176)]
    got = cf.performance_drop(unlogged, ROLES, "upper_heavy")
    assert got["state"] == "triggered" and got["rpe_unlogged_on"] == ["2026-09-28"]
    assert cf.performance_drop(one[:2], ROLES, "upper_heavy")["state"] == "insufficient"
    assert cf.performance_drop(one, None, "upper_heavy")["state"] == "unknown"


def test_mutation_control_a_single_drop_rule_fires_on_one_drop():
    one = [_hist("2026-09-24", 200), _hist("2026-09-28", 200), _hist("2026-10-02", 188)]
    with patch.object(cf, "PERF_DROP_CONSECUTIVE", 1):
        assert cf.performance_drop(one, ROLES, "upper_heavy")["state"] == "triggered"


def _joints(fatigue: dict, total: int = 20) -> dict:
    return c.build_joints_packet(
        {"total_sets": total, "exercises": []},
        pain_by_idx={},
        days_since_by_idx={},
        loaded_lifting_streak=6,
        pain_layer_status="ok",
        fatigue=fatigue,
    )


def test_a_six_day_lifting_streak_with_no_drop_does_not_trigger():
    fat = cf.assess(
        readiness_low_streak_days=1, perf_by_idx={0: {"state": "clear"}}, soreness_by_idx={0: None}, same_region={"state": "clear"}
    )
    p = _joints(fat)
    assert fat["triggered"] is False and c.deterministic_verdict(p)["verdict"] == "approve"


@pytest.mark.parametrize(
    "kw",
    [
        {"readiness_low_streak_days": 2},
        {"perf_by_idx": {0: {"state": "triggered", "role": "upper_heavy", "drop_pct": [6.0, 12.0], "rpe_unlogged_on": []}}},
        {"soreness_by_idx": {0: ["2026-09-28", "2026-09-29"]}},
    ],
    ids=["readiness", "performance", "soreness"],
)
def test_each_trigger_cuts_one_session_by_30_percent_loads_held(kw):
    base = {"readiness_low_streak_days": 0, "perf_by_idx": {}, "soreness_by_idx": {}, "same_region": {"state": "clear"}}
    fat = cf.assess(**{**base, **kw})
    v = c.deterministic_verdict(_joints(fat))
    assert (v["verdict"], v["metric"], v["field"], v["to"]) == ("change", "fatigue_trigger", "session.total_sets", 14)
    assert "THIS session only" in v["reason"] and cf.FATIGUE_RESPONSE == {
        "sets_pct": -30,
        "loads": "held",
        "sessions": 1,
        "then": "re-test",
    }


def test_readiness_low_on_one_day_does_not_trigger_and_consecutive_soreness_is_by_session():
    assert cf.assess(readiness_low_streak_days=1, perf_by_idx={}, soreness_by_idx={}, same_region=None)["triggered"] is False
    sessions = ["2026-09-24", "2026-09-26", "2026-09-28"]
    assert cf.soreness_consecutive(["2026-09-26", "2026-09-28"], sessions) == ["2026-09-26", "2026-09-28"]
    assert cf.soreness_consecutive(["2026-09-24", "2026-09-28"], sessions) is None


def test_the_48h_same_region_guard():
    # a single-region row on purpose: the generic `lift()` spans both regions since #4312
    squat_yesterday = [
        {**lift("2026-10-09"), "exercises": [{"name": "Squat (Barbell)", "sets": [{"type": "normal", "weight_kg": 90, "reps": 5}]}]}
    ]
    got = cf.same_region_recent(squat_yesterday, "2026-10-10", "lower")
    assert got == {"state": "triggered", "region": "lower", "loaded_on": ["2026-10-09"]}
    assert cf.same_region_recent(squat_yesterday, "2026-10-11", "lower")["state"] == "clear", "two days is >= 48 h"
    assert cf.same_region_recent(squat_yesterday, "2026-10-10", "upper")["state"] == "clear"
    fat = cf.assess(readiness_low_streak_days=0, perf_by_idx={}, soreness_by_idx={}, same_region=got)
    v = c.deterministic_verdict(_joints(fat))
    assert (v["metric"], v["to"]) == ("same_region_48h", 14)


def test_the_fatigue_constants_carry_their_provenance():
    ev = cf.FATIGUE_PROVENANCE["evidence"]
    for cite in ("Bell 2023", "Rogerson 2024", "10.1186/s40798-024-00691-y", "Kataoka 2022", "Yang 2018"):
        assert cite in ev
    assert (cf.PERF_DROP_PCT, cf.PERF_DROP_CONSECUTIVE, cf.READINESS_CONSECUTIVE_DAYS, cf.SAME_REGION_MIN_HOURS) == (5.0, 2, 2, 48)


def test_the_advocate_ruling_is_drop_with_its_citation():
    from coach import critics_apply

    assert c.ADVOCATE_RULING["adds_sets"] == 0 and critics_apply.MAX_ADDED_SETS == 0
    src = (REPO / "lambdas/coach/critics_apply.py").read_text()
    assert "Roth 2023" in src and "10.1111/sms.14237" in src


def test_stage_2_evidence_attaches_the_fatigue_inputs_from_the_ledger():
    from mcp import plan_draft_evidence as pde

    ev = {"exercises": [{"idx": 0, "pain_flag_any": False, "_tops": [_hist("2026-09-24", 200)]}]}
    rows = [lift("2026-09-24"), lift("2026-09-25", name="Squat (Barbell)")]
    pde.attach_fatigue_inputs(ev, readiness_low_streak_days=2, block_workouts=rows, target_date="2026-09-26")
    fat = ev["fatigue"]
    assert fat["triggered"] is True and "_tops" not in ev["exercises"][0]
    # served 09-26 is lower-volume (lower) and a squat was loaded 09-25 -> the guard reads it too
    assert fat["same_region_48h"]["state"] == "triggered"
    pde.attach_fatigue_inputs(ev, readiness_low_streak_days=None, block_workouts=None, target_date="2026-09-26")
    assert set(ev["fatigue"]["unknown"]) == {"readiness_low_streak_days", "performance_drop"}


# ── 4. ruling "B": the rate target is conditional on protein adherence ────────────────
WEIGHT = 316.0


@pytest.mark.parametrize(
    "grams,state,target",
    [
        ([150, 150, 150, 150, 190, 190, 190], "gated", round(WEIGHT * 0.5 / 100, 1)),  # 4 misses -> the lower band
        ([150, 150, 190, 190, 190, 190, 190], "clear", 3.5),  # 2 misses -> the step
        ([None, None, None, None, 150, 150, 150], "unknown", 3.5),  # 3 measured days -> unknown, no change
        ([None, None, None, 150, 150, 150, 190], "gated", round(WEIGHT * 0.5 / 100, 1)),  # an unlogged day is not a miss
    ],
    ids=["four-misses", "two-misses", "three-measured", "unlogged-not-missed"],
)
def test_the_protein_gate(grams, state, target):
    """The gate's arithmetic under mode=enforce (the < 30 % body-fat tier, #4166)."""
    with patch.dict(owner_redlines.REDLINES["rate_protein_gate"], {"mode": "enforce"}):
        _assert_the_protein_gate(grams, state, target)


def _assert_the_protein_gate(grams, state, target):
    missed, measured = owner_redlines.protein_days_missed(grams)
    rt = owner_redlines.rate_target_lb_per_wk(WEIGHT, protein_missed_7d=missed, protein_measured_7d=measured)
    assert rt["protein_gate"]["state"] == state and rt["target_lb_wk"] == target and rt["step_target_lb_wk"] == 3.5
    block = plan_engine.constraint_block(
        date="2026-09-20", weight_lb=WEIGHT, protein_days_missed_7d=missed, protein_days_measured_7d=measured
    )
    assert block["rate_target"]["target_lb_wk"] == target and block["rate_target"]["protein_gate"]["state"] == state
    from health import nutrition_critics as nc

    n = nc.build_deficit_advocate_packet({"weight_lb": WEIGHT, "protein_g_by_day": grams})["numbers"]
    assert (n["rate_target_lb_wk"], n["rate_step_target_lb_wk"], n["rate_protein_gate"]) == (target, 3.5, state)


def test_report_only_reads_the_gate_and_never_moves_the_target_4162():
    """Owner ruling 2026-09-25 (#4162 -> #4166): at >= 40 % body fat the gate is REPORT-ONLY. Four misses still
    read `gated` / would_apply, and the served target stays the step (3.5 at 316 lb) at every site — here on the
    LIVE DXA wire (2026-03-30: FFM 178.6 lb -> 43.5 % at 316 lb)."""
    from health import nutrition_critics as nc

    g = owner_redlines.REDLINES["rate_protein_gate"]
    assert g["mode"] == "by_body_fat" and "2026-09-25" in g["mode_ruling"]
    grams = [150, 150, 150, 150, 190, 190, 190]
    missed, measured = owner_redlines.protein_days_missed(grams)
    rt = owner_redlines.rate_target_lb_per_wk(WEIGHT, protein_missed_7d=missed, protein_measured_7d=measured, dxa_scans=DXA_WIRE)
    gate = rt["protein_gate"]
    assert (gate["state"], gate["would_apply"], gate["applied"], gate["mode"]) == ("gated", True, False, "report_only")
    assert (gate["tier"], gate["body_fat_pct"], gate["body_fat_source"]["scan_date"]) == ("report_only", 43.5, "2026-03-30")
    assert gate["body_fat_source"]["ffm_lb"] == 178.6 and "Hall 2007" in gate["tier_evidence"]
    assert rt["target_lb_wk"] == rt["step_target_lb_wk"] == 3.5
    block = plan_engine.constraint_block(
        date="2026-09-20", weight_lb=WEIGHT, protein_days_missed_7d=missed, protein_days_measured_7d=measured, dxa_scans=DXA_WIRE
    )
    assert block["rate_target"]["target_lb_wk"] == 3.5 and block["rate_target"]["protein_gate"]["tier"] == "report_only"
    assert block["inputs"]["dxa_scans"]["state"] == "measured"
    n = nc.build_deficit_advocate_packet({"weight_lb": WEIGHT, "protein_g_by_day": grams, "dxa_scans": DXA_WIRE})["numbers"]
    assert (n["rate_target_lb_wk"], n["rate_protein_gate"], n["rate_protein_gate_tier"]) == (3.5, "gated", "report_only")
    # mutation control: the same misses under enforce DO move the target
    with patch.dict(g, {"mode": "enforce"}):
        assert owner_redlines.rate_target_lb_per_wk(WEIGHT, protein_missed_7d=missed, protein_measured_7d=measured)["target_lb_wk"] < 3.5


# ── #4166: the gate scales with body fat — tiers, the brake, the DXA override, absence ─────────────
DXA_WIRE = __import__("json").loads((pathlib.Path(__file__).parent / "fixtures" / "dexa_wire_2026-09-27.json").read_text())["items"]
BF_WEIGHT = 300.0  # step 3.5; lower band 1.5


def _scan(date: str, lean: float, bmc: float = 8.0, total: float = 300.0) -> dict:
    return {"scan_date": date, "body_composition": {"lean_mass_lb": lean, "bone_mineral_content_lb": bmc, "total_mass_lb": total}}


def _served(scans, missed=4, weight=BF_WEIGHT):
    return owner_redlines.rate_target_lb_per_wk(weight, protein_missed_7d=missed, protein_measured_7d=7, dxa_scans=scans)


@pytest.mark.parametrize(
    "ffm,tier,mode,target",
    [
        (180.0, "report_only", "report_only", 3.5),  # 40.0 % — the 40 edge is report-only
        (180.3, "brake", "brake", 3.0),  # 39.9 % — the step minus 0.5
        (210.0, "brake", "brake", 3.0),  # 30.0 % — the 30 edge is the brake
        (210.3, "full", "enforce", 1.5),  # 29.9 % — the full gate, the lower band
    ],
    ids=["40.0-report-only", "39.9-brake", "30.0-brake", "29.9-full"],
)
def test_the_body_fat_tier_edges_4166(ffm, tier, mode, target):
    rt = _served([_scan("2026-11-01", ffm - 8.0)])
    gate = rt["protein_gate"]
    assert (gate["tier"], gate["mode"], rt["target_lb_wk"], gate["applied"]) == (tier, mode, target, mode != "report_only")
    assert _served([_scan("2026-11-01", ffm - 8.0)], missed=2)["target_lb_wk"] == 3.5, "a clear week serves the step in every tier"


@pytest.mark.parametrize("edge_index,ffm,moved_to", [(0, 180.0, "brake"), (1, 210.0, "full")], ids=["40-edge", "30-edge"])
def test_mutation_control_a_moved_tier_edge_reds_4166(edge_index, ffm, moved_to):
    """Moving an edge by 0.1 moves the boundary case to the next tier — the edges are what decide it."""
    tiers = [dict(t) for t in owner_redlines.REDLINES["rate_protein_gate"]["body_fat_tiers"]["tiers"]]
    tiers[edge_index]["at_or_above_pct"] += 0.1
    with patch.dict(owner_redlines.REDLINES["rate_protein_gate"]["body_fat_tiers"], {"tiers": tiers}):
        assert _served([_scan("2026-11-01", ffm - 8.0)])["protein_gate"]["tier"] == moved_to


WEEK16 = "2026-12-27"  # #4503 OD6: the override first evaluates at the week-16 DXA


def test_the_dxa_override_enforces_at_any_body_fat_4166():
    """Pre-registered: dFFM/dW > 0.25 over a losing DXA pair -> the full gate even at >= 40 % body fat. #4503 OD6: the
    override first evaluates at the week-16 scan; the same pair ending at week 8 is a baseline, not yet evaluated."""
    week0 = DXA_WIRE[-1]  # the live 2026-03-30 scan: 311.7 lb, FFM 178.6
    bad = _scan(WEEK16, 170.6 - 5.2, total=291.7)  # dW 20.0, dFFM 5.2 -> 0.26
    rt = _served([*DXA_WIRE, bad], weight=292.0)
    gate = rt["protein_gate"]
    assert gate["dxa_override"]["pair"] == [week0["scan_date"], WEEK16]
    assert (gate["dxa_override"]["state"], gate["dxa_override"]["ffm_share_of_loss"]) == ("triggered", 0.26)
    assert gate["mode"] == "enforce" and "DXA override" in gate["mode_reason"] and rt["target_lb_wk"] == gate["gated_target_lb_wk"]
    # 0.25 exactly is NOT worse than the diet-alone average: the tier decides (report-only above 40 %)
    ok = _served([*DXA_WIRE, _scan(WEEK16, 170.6 - 5.0, total=291.7)], weight=320.0)["protein_gate"]
    assert (ok["dxa_override"]["state"], ok["mode"]) == ("clear", "report_only")
    # mutation control: an override that is ignored serves the report-only step at 45 % body fat
    with patch("training.redline_rate.dxa_override", return_value={"triggered": False, "state": "clear"}):
        assert _served([*DXA_WIRE, bad], weight=330.0)["protein_gate"]["mode"] == "report_only"
    # mutation control: a higher threshold stops the same pair triggering
    with patch.dict(owner_redlines.REDLINES["rate_protein_gate"]["body_fat_tiers"]["dxa_override"], {"ffm_share_of_loss_above": 0.3}):
        assert _served([*DXA_WIRE, bad], weight=330.0)["protein_gate"]["dxa_override"]["triggered"] is False


def test_4503_od6_the_week_8_scan_does_not_evaluate_the_override():
    bad8 = _scan("2026-11-01", 170.6 - 5.2, total=291.7)  # the same 0.26 pair, ending at week 8
    gate = _served([*DXA_WIRE, bad8], weight=292.0)["protein_gate"]
    assert gate["dxa_override"]["state"] == "not_yet_evaluated" and gate["dxa_override"]["triggered"] is False
    assert "DXA override" not in gate["mode_reason"]
    # mutation control: without the OD6 date the week-8 pair triggers, as it did before the ruling
    with patch.dict(owner_redlines.REDLINES["rate_protein_gate"]["body_fat_tiers"]["dxa_override"], {"first_evaluation_on_or_after": None}):
        assert _served([*DXA_WIRE, bad8], weight=292.0)["protein_gate"]["dxa_override"]["state"] == "triggered"


@pytest.mark.parametrize(
    "scans,why",
    [(None, "the DXA read failed"), ([], "no readable DXA scan"), ([_scan("2026-11-01", 170.0, bmc=None)], "no readable DXA scan")],
    ids=["read-failed", "no-scan", "no-bmc"],
)
def test_no_dxa_is_tier_unknown_and_report_only_4166(scans, why):
    gate = _served(scans)["protein_gate"]
    assert (gate["tier"], gate["body_fat_pct"], gate["body_fat_source"], gate["mode"], gate["applied"]) == (
        "unknown",
        None,
        None,
        "report_only",
        False,
    )
    assert why in gate["mode_reason"] and "says so" in gate["mode_reason"]


def test_the_plan_reads_dxa_through_one_reader_4166():
    """tools_plan and the nutrition critics' resolver call `shared_quantities.dxa_scans` — one reader, oldest first."""
    from mcp import shared_quantities as sq

    with patch("mcp.core.query_source", return_value=list(reversed(DXA_WIRE))) as q:
        assert [r["scan_date"] for r in sq.dxa_scans("2026-09-27")] == ["2025-05-10", "2026-03-30"]
    assert q.call_args.args == ("dexa", sq.DXA_EPOCH, "2026-09-27")
    root = pathlib.Path(__file__).resolve().parents[1]
    for rel in ("mcp/tools_plan.py", "mcp/nutrition_critics_inputs.py"):
        src = (root / rel).read_text()
        assert "dxa_scans" in src and 'query_source("dexa"' not in src, rel


def test_mutation_control_a_higher_miss_threshold_stops_gating_four_misses():
    with patch.dict(owner_redlines.REDLINES["rate_protein_gate"], {"missed_days_threshold": 5, "mode": "enforce"}):
        assert owner_redlines.rate_target_lb_per_wk(WEIGHT, protein_missed_7d=4, protein_measured_7d=7)["target_lb_wk"] == 3.5


def test_ruling_b_carries_its_provenance_and_version():
    g = owner_redlines.REDLINES["rate_protein_gate"]
    assert (g["missed_days_threshold"], g["window_days"], g["min_measured_days"], g["provenance"], g["stated"]) == (
        3,
        7,
        4,
        "owner",
        "2026-09-24",
    )
    assert "Helms 2014" in g["evidence"] and "10.1186/1550-2783-11-20" in g["evidence"]
    assert owner_redlines.REDLINES_VERSION == "3.3" and owner_redlines.REDLINES["protein_floor_g"]["value"] == 180


# ── #4161 review fixes ─────────────────────────────────────────────────────────────────
def _pairwise_rule(tops: list[float]) -> bool:
    """The rule the review rejected: each exposure >= 5 % below the one BEFORE it (kept only as the control)."""
    return all((a - b) / a * 100 >= 5 for a, b in zip(tops[-3:], tops[-2:]))


def test_a_sustained_drop_triggers_and_a_dip_that_recovers_does_not():
    sustained = [_hist("2026-09-24", 200), _hist("2026-09-28", 190), _hist("2026-10-02", 190)]
    got = cf.performance_drop(sustained, ROLES, "upper_heavy")
    assert got["state"] == "triggered" and got["drop_pct"] == [5.0, 5.0]
    dip = [_hist("2026-09-24", 200), _hist("2026-09-28", 198), _hist("2026-10-02", 200)]
    assert cf.performance_drop(dip, ROLES, "upper_heavy")["state"] == "clear"
    # mutation control: the rejected each-vs-previous reading never fires on the sustained drop
    assert _pairwise_rule([200, 190, 190]) is False and _pairwise_rule([200, 198, 200]) is False
    with patch.object(cf, "PERF_DROP_PCT", 5.1):
        assert cf.performance_drop(sustained, ROLES, "upper_heavy")["state"] == "clear", "the 5 % line is what decides it"


def test_a_critic_set_count_increase_is_refused():
    from training.routine_ir import ExerciseBlock, RoutineSpec, Set

    ir = RoutineSpec(
        routine_id="r",
        target_date="2026-10-10",
        archetype="x",
        exercises=[ExerciseBlock(movement_key="tmpl:1", rationale_tag="Row", sets=[Set(weight_kg=40, reps=10) for _ in range(2)])],
    )
    [rec] = c.apply_changes(ir, [{"critic": "joints_tendons", "verdict": "change", "field": "exercises[0].set_count", "to": 5}])
    assert rec["applied"] is False and "no critic adds sets" in rec["why"] and len(ir.exercises[0].sets) == 2
    [rec] = c.apply_changes(ir, [{"critic": "joints_tendons", "verdict": "change", "field": "exercises[0].set_count", "to": 1}])
    assert rec["applied"] is True and len(ir.exercises[0].sets) == 1, "a reduction still applies"


def test_inside_the_deload_the_fatigue_cut_does_not_stack():
    base = {"readiness_low_streak_days": 3, "perf_by_idx": {}, "soreness_by_idx": {}, "same_region": {"state": "clear"}}
    in_deload = _joints(cf.assess(**base, deload_sets_pct=-40), total=12)
    v = c.deterministic_verdict(in_deload)
    assert v["verdict"] == "approve" and in_deload["numbers"]["fatigue_cut_superseded_by_deload"] is True
    assert any("larger cut is taken, not both" in f["reason"] for f in in_deload["flags"])
    # mutation control: outside the deload the same trigger cuts
    out = c.deterministic_verdict(_joints(cf.assess(**base), total=12))
    assert (out["verdict"], out["to"]) == ("change", 8)


def test_the_stage_2_evidence_marks_a_deload_session_superseded():
    from mcp import plan_draft_evidence as pde

    ev = {"exercises": []}
    pde.attach_fatigue_inputs(ev, readiness_low_streak_days=3, block_workouts=daily(41), target_date="2026-11-04")
    assert ev["fatigue"]["response"]["superseded_by_deload"] is True and ev["fatigue"]["response"]["deload_sets_pct"] == -40


def test_a_version_bump_is_not_a_structural_edit():
    with patch.dict(program_structure.SESSION_SEQUENCE, {"program_version": "0.4.1"}):
        assert session_sequence.block_lock_state("2026-10-10")["state"] == "locked"


def test_a_fingerprint_re_record_without_the_owner_note_reds():
    assert session_sequence.fingerprint_record_problems() == []
    with patch.dict(program_structure.BLOCK_LOCK, {"structure_fingerprint": "deadbeefdeadbeef"}):
        assert session_sequence.fingerprint_record_problems(), "a bare re-record must not pass"
        assert session_sequence.block_lock_state("2026-10-10")["state"] == "violated"
    bad = {**program_structure.BLOCK_LOCK["structure_fingerprint_record"], "provenance": "platform"}
    with patch.dict(program_structure.BLOCK_LOCK, {"structure_fingerprint_record": bad}):
        assert "record provenance is not 'owner'" in session_sequence.fingerprint_record_problems()


def test_the_gated_target_is_one_data_field():
    g = owner_redlines.REDLINES["rate_protein_gate"]["gated_target"]
    assert g["source"] == "rate_band_pct_bw_per_wk.low" and g["fixed_lb_wk"] is None
    gate = owner_redlines.REDLINES["rate_protein_gate"]
    with patch.dict(gate, {"mode": "enforce"}):  # the < 30 % body-fat tier (#4166); report_only serves the step
        assert owner_redlines.rate_target_lb_per_wk(WEIGHT, protein_missed_7d=4, protein_measured_7d=7)["target_lb_wk"] == 1.6
        with patch.dict(g, {"fixed_lb_wk": 2.5}):
            rt = owner_redlines.rate_target_lb_per_wk(WEIGHT, protein_missed_7d=4, protein_measured_7d=7)
    assert rt["target_lb_wk"] == 2.5 and rt["protein_gate"]["gated_target_source"] == "rate_protein_gate.gated_target.fixed_lb_wk"


@pytest.mark.parametrize("target_offset", [0, 1])
def test_the_plan_gate_and_the_deficit_advocate_read_one_window(target_offset):
    """Same MacroFactor days -> the same window, the same counts, the same gate state at both sites.
    Mutation control: the pre-review [target-6, target] window reads a different week and a different state."""
    from health import nutrition_critics as nc

    from mcp import tools_plan as tp

    as_of = "2026-10-10"
    last_complete = shift_day_key(as_of, -1)
    days = [shift_day_key(last_complete, -i) for i in range(13, -1, -1)]  # 14 completed days, oldest first
    # 4 misses, early in the completed week (last_complete-6 .. last_complete-3)
    grams = {d: (150 if shift_day_key(last_complete, -6) <= d <= shift_day_key(last_complete, -3) else 190) for d in days}
    grams[as_of] = 190  # a partial row for the as-of day itself must never be read

    def nutrition(args):
        rows = [{"date": d, "protein_g": g} for d, g in grams.items() if args["start_date"] <= d <= args["end_date"]]
        return {"daily_breakdown": rows}

    target = shift_day_key(as_of, target_offset)
    # the plan's clock is pinned to the fixture's as-of day, so the window cannot drift with the wall clock
    with patch("mcp.tools_plan.pacific_today", return_value=as_of), patch("mcp.tools_nutrition.tool_get_nutrition", side_effect=nutrition):
        missed, measured = tp._protein_days_7d(target)
    win = owner_redlines.protein_window(target, as_of)
    assert win == {"start": shift_day_key(last_complete, -6), "end": last_complete}
    plan = owner_redlines.rate_target_lb_per_wk(WEIGHT, protein_missed_7d=missed, protein_measured_7d=measured, protein_window_days=win)
    adv = nc.build_deficit_advocate_packet({"weight_lb": WEIGHT, "window_end": last_complete, "protein_g_by_day": [grams[d] for d in days]})
    assert plan["protein_gate"]["state"] == adv["numbers"]["rate_protein_gate"] == "gated"
    assert plan["protein_gate"]["window"] == win
    if target_offset == 1:  # mutation control: the pre-review window [target-6, target] sees 2 misses — a different state
        old = [g for d, g in grams.items() if shift_day_key(target, -6) <= d <= target]
        assert owner_redlines.protein_gate(*owner_redlines.protein_days_missed(old))["state"] == "clear"


# ── #4503 OD6 (owner, amended 2026-09-30): Body Scan 2 between DXA scans — bioimpedance-labelled, own-variance band ──
# Synthetic rows (the live values are owner health data and stay out of a public fixture). Segments in the stored
# field names; torso carries the dominant share; the five fat-free segments sum to the scalar, as on the wire (#2994).
def _bs2(day: str, torso: float, leg: float = 15.5, arm: float = 6.2) -> dict:
    row: dict = {"date": day, "sk": f"DATE#{day}"}
    for kind, scale in (("fat_free_mass", 1.0), ("muscle_mass", 0.95), ("fat_mass", 0.5)):
        for seg, v in (("torso", torso), ("left_leg", leg), ("right_leg", leg), ("left_arm", arm), ("right_arm", arm)):
            row[f"{kind}_{seg}_kg"] = round(v * scale, 2)
    row["fat_free_mass_kg"] = round(torso + 2 * leg + 2 * arm, 2)
    return row


BS2_ROWS = [
    _bs2("2026-09-18", 49.0),
    _bs2("2026-09-19", 49.2),
    _bs2("2026-09-20", 48.9),
    _bs2("2026-09-21", 49.1),
    _bs2("2026-09-22", 48.8),
    _bs2("2026-09-29", 47.5),
]


def test_4503_od6_the_between_dxa_read_is_labelled_bioimpedance_with_his_own_noise_band():
    from training import bodyscan_lean

    r = bodyscan_lean.between_dxa_read(BS2_ROWS, [{"scan_date": "2026-03-30"}], "2026-09-30")
    assert r["state"] == "measured" and "bioimpedance" in r["label"] and "never a substitute for the DXA anchor" in r["label"]
    assert r["dxa_anchor"] == "2026-03-30" and r["baseline"]["date"] == "2026-09-18" and r["latest"] == "2026-09-29"
    torso = r["deltas"]["fat_free_mass:torso"]
    # repeat pairs <= 2 d apart: +0.2, -0.3, +0.2, -0.3 -> SD 0.2887 -> band 1.96 x SD = 0.57; n = 4 (the 7-day gap is not a repeat)
    assert torso["noise"]["n"] == 4 and torso["noise"]["band_kg"] == pytest.approx(0.57, abs=0.01)
    assert torso["delta_kg"] == pytest.approx(-1.5) and torso["beyond_noise"] is True
    legs = r["deltas"]["fat_free_mass:legs"]
    assert legs["delta_kg"] == 0 and legs["noise"]["band_kg"] == 0 and legs["beyond_noise"] is False
    assert set(r["deltas"]) >= {"total_ffm_kg", "fat_free_mass:arms", "muscle_mass:torso"}


def test_4503_od6_a_thin_record_reports_no_band_and_a_partial_scan_is_not_a_full_scan():
    from training import bodyscan_lean

    thin = bodyscan_lean.between_dxa_read(BS2_ROWS[-2:], [], "2026-09-30")
    assert thin["baseline"]["rule"].endswith("no DXA on record")
    assert thin["deltas"]["total_ffm_kg"]["noise"]["band_kg"] is None and thin["deltas"]["total_ffm_kg"]["beyond_noise"] is None
    partial = dict(BS2_ROWS[0])
    del partial["muscle_mass_left_arm_kg"]
    assert bodyscan_lean.full_scans([partial]) == []
    assert bodyscan_lean.between_dxa_read(None, [], "2026-09-30")["state"] == "read_failed"
    # mutation control: with no repeat-scan window the band cannot be computed — the 1.5 kg torso drop is no longer judged
    with patch.object(bodyscan_lean, "REPEAT_MAX_GAP_DAYS", 0):
        r = bodyscan_lean.between_dxa_read(BS2_ROWS, [], "2026-09-30")
    assert r["deltas"]["fat_free_mass:torso"]["beyond_noise"] is None


def test_4503_od6_plan_next_session_serves_the_read():
    from mcp import tools_plan

    with patch("mcp.core.query_source", return_value=BS2_ROWS):
        out = tools_plan._between_dxa_lean("2026-09-30", [{"scan_date": "2026-03-30"}], "measured")
    assert out["state"] == "measured" and out["input_status"]["state"] == "measured" and out["dxa_read"] == "measured"
    assert 'out["between_dxa_lean"]' in (pathlib.Path(tools_plan.__file__)).read_text()
