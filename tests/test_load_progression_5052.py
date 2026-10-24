"""tests/test_load_progression_5052.py — #5052: engine-authored double progression.

A self-raised load at or under the charter effort ceiling becomes the next floor and is graded
`progressed`, never a breach; two top-of-range exposures earn one step; everything else holds.
The rule, the step and the ceilings are read from `config/training_charter.json` (v1.1.0
`progression`, `effort_ceilings`) — never from a literal in the engine.

The re-grade fixture is the real 2026-10-18 session (the Hevy workout + its matched routine IR,
read-only from DynamoDB; see the fixture's `_source`). Nothing here reads the clock.
"""

from __future__ import annotations

import json
import os

import pytest
from training import load_progression as lp, training_charter as tc
from training.routine_ir import ExerciseBlock, RoutineSpec, Set

_HERE = os.path.dirname(os.path.abspath(__file__))
FIXTURE = os.path.join(_HERE, "fixtures", "load_progression_2026_10_18_5052.json")
LB = 0.45359237


@pytest.fixture(autouse=True)
def _fresh_charter():
    tc.reset_cache()
    yield
    tc.reset_cache()


def _kg(lb: float) -> float:
    return lb * LB


def _session(date: str, lb: float, reps: list[int], rpes: list[float | None], prescribed_lb: float | None = None) -> dict:
    s = {"date": date, "sets": [{"weight_kg": _kg(lb), "reps": r, "rpe": e} for r, e in zip(reps, rpes)]}
    if prescribed_lb is not None:
        s["prescribed_kg"] = _kg(prescribed_lb)
    return s


# ── the charter is the registry ──────────────────────────────────────────────────
def test_the_gain_rule_lives_on_the_charter_with_the_redlines_numbers():
    from training import owner_redlines

    rule = lp.gain_rule()
    assert rule["kind"] == "double_progression" and rule["consecutive_same_type_exposures"] == 2
    assert rule["step_lb"] == 5 and rule["step_pct"] == 2.5 and rule["nutrition_clause"] is None
    assert rule["stated"] == "2026-09-30" and "#4503" in rule["ruling"]
    # the charter moves on past 1.1.0 as later lanes add their own entries; this lane's entry is the one it owns
    assert tuple(int(x) for x in tc.charter_version().split(".")) >= (1, 1, 0)
    log = next(e for e in tc.charter_value("change_log") if e["version"] == "1.1.0")
    assert "#5052" in log["by"]
    # the redline copy is retired: a pointer, no numbers
    pointer = owner_redlines.REDLINES["lifting_sessions_per_wk"]["gain_rule"]
    assert set(pointer) == {"source", "applied_by"} and pointer["source"].endswith("progression.gain_rule")


def test_effort_limits_are_read_from_the_charter_not_typed():
    lim = lp.effort_limits()
    # #5058: the ruled class bands (`by_movement_class`); the ceiling is the band's HIGH end
    bands = tc.charter_value("effort_ceilings.by_movement_class")
    tol = tc.charter_value("effort_ceilings.overage_tolerance_rpe")
    assert lim["compound"]["ceiling_rpe"] == max(bands["compounds_rpe"])
    assert lim["compound"]["limit_rpe"] == max(bands["compounds_rpe"]) + tol
    assert lim["last_isolation_set"]["limit_rpe"] == max(bands["last_isolation_set_rpe"]) + tol


# ── the four bases ────────────────────────────────────────────────────────────────
def test_floor_raise_a_self_raised_load_under_the_ceiling_is_the_next_floor():
    # 10-18 lat pulldown: prescribed 155, he did 160 x 8 at RPE 8 / 8 / 8.5
    hist = [_session("2026-10-18", 160, [8, 8, 8], [8, 8, 8.5], prescribed_lb=155)]
    out = lp.next_prescription(hist, current_kg=_kg(155), rep_range=(8, 12), cls=lp.CLASS_COMPOUND)
    assert out["basis"] == lp.BASIS_FLOOR_RAISE
    assert out["next_load_kg"] == pytest.approx(_kg(160))
    assert "floor 160 lb" in out["reason"] and "you raised it" in out["reason"] and "10-18" in out["reason"]
    assert out["charter_version"] == tc.charter_version()


def test_hold_one_top_of_range_exposure_is_not_two():
    hist = [_session("2026-10-16", 185, [12, 12], [8, 8]), _session("2026-10-14", 185, [11, 10], [8, 8])]
    out = lp.next_prescription(hist, current_kg=_kg(185), rep_range=(8, 12), cls=lp.CLASS_COMPOUND)
    assert out["basis"] == lp.BASIS_HOLD and out["next_load_kg"] == pytest.approx(_kg(185))
    assert "1 of 2" in out["reason"]


def test_a_hold_below_the_prescribed_load_names_the_load_not_a_met_criterion():
    """The 2026-10-23 pre-draft's calf line read "hold 435 lb: 2 of 2 top sets at the top of 8-15 at or under the ceiling"
    while the sessions were at 360 lb — the gain rule (rightly) never counts a run below the prescribed load, so the text
    claimed a met criterion beside a hold. The hold now names the case."""
    hist = [_session("2026-10-21", 360, [21, 21, 21], [8, 8, 8]), _session("2026-10-16", 360, [21, 21, 21], [8, 8, 8])]
    out = lp.next_prescription(hist, current_kg=_kg(435), rep_range=(8, 15), cls=lp.CLASS_ISOLATION)
    assert out["basis"] == lp.BASIS_HOLD and out["next_load_kg"] == pytest.approx(_kg(435))
    assert out["reason"].startswith("hold 435 lb: the top sets on 10-21 were at 360 lb, below the prescribed load"), out["reason"]
    assert "2 of 2" not in out["reason"]
    # the same run AT the prescribed load still steps (the case the gain rule exists for)
    at = [_session("2026-10-21", 435, [15, 15], [8, 8]), _session("2026-10-16", 435, [15, 15], [8, 8])]
    assert lp.next_prescription(at, current_kg=_kg(435), rep_range=(8, 15), cls=lp.CLASS_ISOLATION)["basis"] == lp.BASIS_STEP


def test_step_two_top_sets_at_the_top_of_the_range_earn_one_step_reps_to_the_bottom():
    hist = [_session("2026-10-16", 185, [12, 12], [8, 7.5]), _session("2026-10-14", 185, [12, 11], [8, 8])]
    out = lp.next_prescription(hist, current_kg=_kg(185), rep_range=(8, 12), cls=lp.CLASS_COMPOUND)
    assert out["basis"] == lp.BASIS_STEP
    assert out["next_load_kg"] == pytest.approx(_kg(190)) and out["next_reps"] == 8
    assert out["reason"].startswith("+5 lb to 190 lb") and "10-14 and 10-16" in out["reason"] and "reps back to 8" in out["reason"]
    assert len(out["reason"]) <= 150  # short enough for any Hevy note


def test_step_size_is_two_and_a_half_percent_in_whole_five_lb_steps():
    rule = lp.gain_rule()
    assert lp.step_kg(_kg(185), rule) == pytest.approx(_kg(5))  # 4.6 lb -> one step, never under one
    assert lp.step_kg(_kg(400), rule) == pytest.approx(_kg(10))  # 10 lb -> two steps


def test_the_rpe_is_a_veto_a_top_of_range_set_above_the_ceiling_does_not_count():
    ceiling = lp.effort_limits()["compound"]["ceiling_rpe"]
    hist = [_session("2026-10-16", 185, [12], [ceiling + 0.5]), _session("2026-10-14", 185, [12], [ceiling])]
    out = lp.next_prescription(hist, current_kg=_kg(185), rep_range=(8, 12), cls=lp.CLASS_COMPOUND)
    assert out["basis"] == lp.BASIS_HOLD and "0 of 2" in out["reason"]
    unlogged = [_session("2026-10-16", 185, [12], [None]), _session("2026-10-14", 185, [12], [ceiling])]
    assert lp.next_prescription(unlogged, current_kg=_kg(185), rep_range=(8, 12), cls=lp.CLASS_COMPOUND)["basis"] == lp.BASIS_HOLD


def test_breach_a_raised_load_above_ceiling_plus_tolerance_is_never_a_floor():
    lim = lp.effort_limits()["compound"]
    over = lim["limit_rpe"] + 0.5  # above the ceiling + the charter's tolerance
    hist = [_session("2026-10-18", 90, [10, 10], [lim["ceiling_rpe"], over], prescribed_lb=85)]
    out = lp.next_prescription(hist, current_kg=_kg(85), rep_range=(8, 12), cls=lp.CLASS_COMPOUND)
    assert out["basis"] == lp.BASIS_HOLD and out["next_load_kg"] == pytest.approx(_kg(85))
    assert "a breach, not a floor" in out["reason"]
    # AT ceiling + tolerance is within (the charter's overage rule), so the raise stands
    edge = [_session("2026-10-18", 90, [10], [lim["limit_rpe"]], prescribed_lb=85)]
    assert lp.next_prescription(edge, current_kg=_kg(85), rep_range=(8, 12), cls=lp.CLASS_COMPOUND)["basis"] == lp.BASIS_FLOOR_RAISE


def test_the_tolerance_is_the_charters_not_a_literal(monkeypatch):
    real = tc.charter_value

    def no_tolerance(path, default=None):
        return 0 if path == "effort_ceilings.overage_tolerance_rpe" else real(path, default)

    monkeypatch.setattr(lp, "charter_value", no_tolerance)
    lim = lp.effort_limits()["compound"]
    assert lim["limit_rpe"] == lim["ceiling_rpe"]
    edge = [_session("2026-10-18", 90, [10], [lim["ceiling_rpe"] + 1], prescribed_lb=85)]
    assert lp.next_prescription(edge, current_kg=_kg(85), rep_range=(8, 12), cls=lp.CLASS_COMPOUND)["basis"] == lp.BASIS_HOLD


def test_re_entry_and_an_applied_deload_hold_progression():
    hist = [_session("2026-10-16", 185, [12], [8]), _session("2026-10-14", 185, [12], [8])]
    out = lp.next_prescription(
        hist, current_kg=_kg(170), rep_range=(8, 12), cls=lp.CLASS_COMPOUND, re_entry_reason="9d since the last session"
    )
    assert out["basis"] == lp.BASIS_RE_ENTRY and out["next_load_kg"] == pytest.approx(_kg(170))
    held = lp.next_prescription(
        hist, current_kg=_kg(185), rep_range=(8, 12), cls=lp.CLASS_COMPOUND, hold_reason="a deload the owner applied"
    )
    assert held["basis"] == lp.BASIS_HOLD and "deload" in held["reason"]


def test_a_heavy_days_five_rep_top_set_is_not_a_volume_slots_floor():
    hist = [_session("2026-10-16", 225, [5, 5], [8, 8])]
    out = lp.next_prescription(hist, current_kg=_kg(185), rep_range=(8, 12), cls=lp.CLASS_COMPOUND)
    assert out["basis"] == lp.BASIS_HOLD and out["next_load_kg"] == pytest.approx(_kg(185))


def test_apply_to_sets_raises_working_sets_only_and_never_lowers():
    sets = [Set(type="warmup", weight_kg=40.0), Set(type="normal", weight_kg=_kg(155)), Set(type="normal", weight_kg=_kg(170))]
    lines = lp.apply_to_sets(sets, {"basis": lp.BASIS_FLOOR_RAISE, "next_load_kg": _kg(160)})
    assert [s.weight_kg for s in sets] == [40.0, pytest.approx(_kg(160)), pytest.approx(_kg(170))]
    assert len(lines) == 1
    assert lp.apply_to_sets(sets, {"basis": lp.BASIS_HOLD, "next_load_kg": _kg(200)}) == []


# ── the grader: progressed is a third named state ─────────────────────────────────
def test_grade_sets_counts_a_self_raised_set_as_progressed_not_over():
    from training.intensity_prescription import grade_sets

    prog = {"prescribed_kg": _kg(155), **lp.grading_limits(lp.CLASS_COMPOUND)}
    limit = prog["limit_rpe"]
    sets = [
        {"type": "normal", "weight_kg": _kg(160), "reps": 8, "rpe": 8.5},  # raised, within the limit -> progressed
        {"type": "normal", "weight_kg": _kg(160), "reps": 8, "rpe": limit + 0.5},  # raised, above -> still a breach
        {"type": "normal", "weight_kg": _kg(155), "reps": 8, "rpe": 8.5},  # at the prescription, over its 8 -> over
        {"type": "normal", "weight_kg": _kg(155), "reps": 8, "rpe": 7},  # within
    ]
    g = grade_sets(8.0, sets, progression=prog)
    assert g["sets_progressed"] == 1 and g["sets_over_ceiling"] == 2 and g["sets_graded"] == 4
    assert g["pct_within_ceiling"] == pytest.approx(33.3)  # 1 of the 3 non-progressed sets — progressed is never in it
    assert grade_sets(8.0, sets)["sets_over_ceiling"] == 3  # without the progression input: the pre-#5052 reading


def _fixture():
    with open(FIXTURE, encoding="utf-8") as f:
        return json.load(f)


def _fixture_ir(fx: dict) -> RoutineSpec:
    return RoutineSpec(
        routine_id="014e1142aaad30b3b3b1fb5e90046dc2",
        target_date=fx["target_date"],
        archetype="upper",
        notes=fx["routine_notes"],
        exercises=[
            ExerciseBlock(
                movement_key=e["movement_key"],
                notes=e["notes"],
                sets=[
                    Set(type=s["type"], weight_kg=s["weight_kg"], rep_range_start=s["rep_range_start"], rep_range_end=s["rep_range_end"])
                    for s in e["sets"]
                ],
            )
            for e in fx["routine"]
        ],
    )


def _no_limits():
    empty = {"ceiling_rpe": None, "limit_rpe": None, "source": "test: no charter"}
    return {"tolerance_rpe": None, "compound": dict(empty), "last_isolation_set": dict(empty)}


def test_the_real_2026_10_18_session_regrades_self_raised_loads_from_no_to_progressed(monkeypatch):
    """The live session, re-graded. Pre-#5052 (no progression input) it reproduces the stored verdict
    exactly — `no`, 14 sets over, five movements. Post-#5052 the three loads he raised himself under the
    charter ceiling (lat pulldown 155 -> 160, curl 25 -> 27.5, three of the row's four sets 85 -> 90) are
    `progressed`. #5058 (the charter's compounds ceiling RPE 9, +1 tolerance): the row's fourth set at
    RPE 10 is now inside the limit too (progressed), and the pushdown's 8.5s over its RPE-8 note are within
    tolerance, not breaches. What stays a breach is real: the bench at its PRESCRIBED 185 logged RPE 9.5-10
    against its own RPE-8 note. So the session verdict stays `no`, on one movement."""
    from health import adherence_calc

    fx = _fixture()
    stored = fx["stored_adherence"]

    monkeypatch.setattr(lp, "effort_limits", _no_limits)
    before = adherence_calc.calculate_adherence(_fixture_ir(fx), fx["workout"])
    assert before["as_prescribed"]["verdict"] == stored["as_prescribed"]["verdict"] == "no"
    assert before["intensity_adherence"]["sets_over_ceiling"] == stored["sets_over_ceiling"] == 14
    assert before["intensity_adherence"]["over_ceiling_movements"] == stored["over_ceiling_movements"]
    monkeypatch.undo()
    tc.reset_cache()

    after = adherence_calc.calculate_adherence(_fixture_ir(fx), fx["workout"])
    by = {m["movement_key"]: m["intensity"] for m in after["movements"]}
    for key in ("lat_pulldown", "db_curl"):  # flipped: every over-ceiling set was a self-raised load under the charter ceiling
        assert key in stored["over_ceiling_movements"]
        assert by[key]["sets_over_ceiling"] == 0 and by[key]["sets_progressed"] == 3, (key, by[key])
    # #5058: the RPE-10 set is at the compounds limit (9 + 1), so it is progressed too
    assert by["one_arm_db_row"]["sets_progressed"] == 4 and by["one_arm_db_row"]["sets_over_ceiling"] == 0
    assert by["barbell_bench_press"]["sets_progressed"] == 0  # 185 was the prescription, not a raise
    assert (by["barbell_bench_press"]["sets_over_ceiling"], by["barbell_bench_press"]["sets_within_tolerance"]) == (3, 2)
    assert by["cable_tricep_pushdown"]["sets_over_ceiling"] == 0 and by["cable_tricep_pushdown"]["sets_within_tolerance"] == 2
    ia = after["intensity_adherence"]
    # 10 progressed sets (lat 3 + curl 3 + row 4); of the 14 strict "over" only the bench's 9.5 / 10 / 9.5 breach
    assert ia["sets_progressed"] == 10 and ia["sets_over_ceiling"] == 3
    assert ia["progressed_movements"] == ["db_curl", "lat_pulldown", "one_arm_db_row"]
    assert set(ia["over_ceiling_movements"]) == {"barbell_bench_press"}
    assert after["as_prescribed"]["verdict"] == "no"


def test_a_session_whose_only_overages_are_self_raised_reads_progressed():
    """The same 10-18 lat pulldown + curl, alone: every set done, every overage a self-raised load at or
    under the charter ceiling -> `progressed` (was `no`)."""
    from health import adherence_calc

    fx = _fixture()
    keep = {"lat_pulldown", "db_curl"}
    fx["routine"] = [e for e in fx["routine"] if e["movement_key"] in keep]
    fx["routine_notes"] = ""
    titles = {"Lat Pulldown (Cable)", "Bicep Curl (Dumbbell)"}
    fx["workout"]["exercises"] = [e for e in fx["workout"]["exercises"] if e["title"] in titles]
    out = adherence_calc.calculate_adherence(_fixture_ir(fx), fx["workout"])
    assert out["as_prescribed"]["verdict"] == "progressed", out["as_prescribed"]
    assert "6 set(s) above the prescribed load" in out["as_prescribed"]["reasons"][0]
    assert out["intensity_adherence"]["pct"] is None  # progressed is never folded into a percentage


def test_the_next_draft_raises_the_10_18_self_raised_loads():
    """The 10-18 sets as the generator's history: the next draft's floor is the load he raised to."""
    fx = _fixture()
    perf = {e["title"]: e for e in fx["workout"]["exercises"]}
    rows = {"Lat Pulldown (Cable)": (155, (8, 12), lp.CLASS_COMPOUND), "Bicep Curl (Dumbbell)": (25, (8, 15), lp.CLASS_ISOLATION)}
    for title, (rx_lb, rep_range, cls) in rows.items():
        sets = [s for s in perf[title]["sets"] if s["type"] != "warmup"]
        out = lp.next_prescription(
            [{"date": "2026-10-18", "sets": sets, "prescribed_kg": _kg(rx_lb)}], current_kg=_kg(rx_lb), rep_range=rep_range, cls=cls
        )
        assert out["basis"] == lp.BASIS_FLOOR_RAISE, (title, out)
        assert out["next_load_kg"] == pytest.approx(max(s["weight_kg"] for s in sets))


# ── the wiring ────────────────────────────────────────────────────────────────────
def test_the_generator_applies_progression_after_the_floor_and_writes_the_reason_into_the_note():
    from training import routine_generator as rg

    catalog = rg._load_json("movement_catalog.json")
    tid = catalog["movements"]["lat_pulldown"]["hevy_template_id_hint"]
    history = {
        tid: [
            {"date": "2026-10-16", "top_weight_kg": _kg(160), "sets": [{"weight_kg": _kg(160), "reps": 12, "rpe": 7.5}]},
            {"date": "2026-10-14", "top_weight_kg": _kg(160), "sets": [{"weight_kg": _kg(160), "reps": 12, "rpe": 8.0}]},
        ]
    }
    weights = {"2026-10-14": 300.0, "2026-10-16": 300.0, "2026-10-18": 300.0}
    block = ExerciseBlock(
        movement_key="lat_pulldown", sets=[Set(type="normal", rep_range_start=8, rep_range_end=12) for _ in range(2)], notes=""
    )
    rationale: list[str] = []
    audit = rg._enforce_load_floors([block], catalog, history, weights, "2026-10-19", 1, 7, rationale)
    prog = audit["movements"]["lat_pulldown"]["progression"]
    assert prog["basis"] == lp.BASIS_STEP and prog["charter_version"] == tc.charter_version()
    assert all(s.weight_kg == pytest.approx(_kg(165)) for s in block.sets)
    assert "+5 lb to 165 lb" in block.notes and any("step" in line for line in rationale)

    held = ExerciseBlock(movement_key="lat_pulldown", sets=[Set(type="normal", rep_range_start=8, rep_range_end=12)], notes="")
    audit = rg._enforce_load_floors([held], catalog, history, weights, "2026-10-19", 1, 7, [], hold_reason="a deload the owner applied")
    assert audit["movements"]["lat_pulldown"]["progression"]["basis"] == lp.BASIS_HOLD
    assert held.sets[0].weight_kg == pytest.approx(_kg(160))  # the floor, not the step


def test_the_constraint_block_carries_progression_with_the_charter_version():
    from training import plan_engine

    block = plan_engine.constraint_block(date="2026-10-19")
    prog = block["progression"]
    assert prog["charter_version"] == block["charter_version"] == tc.charter_version()
    assert prog["gain_rule"]["consecutive_same_type_exposures"] == 2 and set(prog["bases"]) == set(lp.BASES)


def test_the_stall_detector_reads_a_self_raised_top_set_as_progressed():
    from training.stall_detector import MATCH_DEVIATED, MATCH_PROGRESSED, SessionPoint

    limit = lp.grading_limits(lp.CLASS_COMPOUND)["limit_rpe"]
    p = SessionPoint(date="2026-10-18", load_kg=_kg(160), reps=8, rpe=8.5, prescribed_load_kg=_kg(155), prescribed_reps=8)
    assert p.match() == MATCH_DEVIATED  # no limit supplied: the pre-#5052 reading
    p.progression_limit_rpe = limit
    assert p.match() == MATCH_PROGRESSED
    p.rpe = limit + 0.5
    assert p.match() == MATCH_DEVIATED
