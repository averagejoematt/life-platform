"""tests/test_stall_step_due_5057.py — #5057: a stalled accessory gets the step, not another repeat.

The owner's rule (charter `progression.stall_rule`, the 2026-10-18 panel review): the top set's
load x reps identical on 3 consecutive exposures, each at self-reported RPE <= 8, is `step_due` —
the PRESCRIPTION's failure to progress, not his — and the next draft carries one step
(`load_progression.stall_step`, the one progression: a rep step below the top of the range, else
the gain rule's load step). `stall_detector.assess_stall` names it; `stall_check` reports it; the
generator's `_progress_block` applies it; `draft_custom` names it on a block authored below it.

The backtest fixture is the real calf press / leg press / DB curl history (Hevy, 2026-09-24 to
2026-10-18, read-only from DynamoDB; see its `_README`). Nothing here reads the clock: every
window is cut by an explicit as-of date.
"""

from __future__ import annotations

import json
import os

import pytest
from training import load_progression as lp, stall_detector as sd, training_charter as tc
from training.routine_ir import ExerciseBlock, RoutineSpec, Set

_HERE = os.path.dirname(os.path.abspath(__file__))
FIXTURE = os.path.join(_HERE, "fixtures", "stall_step_due_backtest_5057.json")
LB = 0.45359237
CALF, LEG_PRESS, DB_CURL = "91237BDD", "C7973E0E", "37FCC2BB"


@pytest.fixture(autouse=True)
def _fresh_charter():
    tc.reset_cache()
    yield
    tc.reset_cache()


def _kg(lb: float) -> float:
    return lb * LB


def _history(tid: str, as_of: str = "2026-10-18") -> list[dict]:
    """That movement's sessions on or before `as_of`, MOST RECENT FIRST (the history-index order)."""
    with open(FIXTURE, encoding="utf-8") as fh:
        idx = json.load(fh)["history_index"]
    return [s for s in idx[tid] if s["date"] <= as_of]


def _points(sessions: list[dict]) -> list[sd.SessionPoint]:
    """Detector points OLDEST FIRST, each the session's top working set; no plan on file."""
    out = []
    for s in reversed(sessions):
        top = sd.top_working_set(s["sets"])
        out.append(sd.SessionPoint(date=s["date"], load_kg=top["weight_kg"], reps=top["reps"], rpe=top["rpe"]))
    return out


def _session(date: str, lb: float, reps: int, rpe: float | None) -> dict:
    return {"date": date, "sets": [{"weight_kg": _kg(lb), "reps": reps, "rpe": rpe}, {"weight_kg": _kg(lb), "reps": reps, "rpe": rpe}]}


# ── the charter is the registry ──────────────────────────────────────────────────


def test_the_stall_rule_lives_on_the_charter():
    rule = tc.charter_value("progression.stall_rule")
    assert rule["verdict"] == sd.VERDICT_STEP_DUE
    assert rule["consecutive_exposures"] == 3 and rule["max_rpe"] == 8 and rule["rep_step_max"] == 2
    assert "#5057" in rule["ruling"]
    assert any("#5057" in e["by"] for e in tc.load_charter()["change_log"])
    assert lp.rule_summary()["stall_rule"] == rule


def test_the_thresholds_are_the_charters_not_literals():
    pts = _points(_history(CALF))
    assert sd.assess_stall(pts)["verdict"] == sd.VERDICT_STEP_DUE
    stricter = dict(tc.charter_value("progression.stall_rule"), max_rpe=6.5)
    assert lp.stall_run(_history(CALF), stricter)["due"] is False
    longer = dict(tc.charter_value("progression.stall_rule"), consecutive_exposures=6)
    assert lp.stall_run(_history(CALF), longer)["due"] is False  # 5 identical exposures, not 6


# ── the backtest: the three specimens ────────────────────────────────────────────


SPECIMENS = (
    # (template id, as-of date, the three dates, the repeated top set in lb x reps)
    (CALF, "2026-10-18", ["2026-10-09", "2026-10-13", "2026-10-16"], (360, 15)),
    (LEG_PRESS, "2026-10-18", ["2026-10-09", "2026-10-13", "2026-10-16"], (360, 8)),
    (DB_CURL, "2026-10-02", ["2026-09-25", "2026-09-29", "2026-10-02"], (25, 12)),
)


def test_backtest_flags_each_specimen_step_due_with_its_dates():
    """One test over the three specimens (one census gate), every miss reported together."""
    misses = []
    for tid, as_of, dates, top in SPECIMENS:
        verdict = sd.assess_stall(_points(_history(tid, as_of)), movement_key=tid)
        step = verdict.get("step") or {}
        days = [d[5:] for d in dates]
        checks = {
            "verdict": verdict["verdict"] == sd.VERDICT_STEP_DUE,
            "basis": verdict["basis"] == sd.BASIS_SELF_REPORTED_RPE and "rpe" in verdict["signals_used"],
            "dates": step.get("dates") == dates and step.get("rpe_basis") == "self-reported",
            "top": (round((step.get("from_load_kg") or 0) / LB), step.get("from_reps")) == top,
            "reason": f"{days[0]}, {days[1]} and {days[2]}" in verdict["reason"] and "self-reported" in verdict["reason"],
            # no rep range on file -> the gain rule's load step at the same reps
            "load_step": step.get("step_kind") == lp.STEP_KIND_LOAD
            and step.get("next_reps") == top[1]
            and abs(step.get("next_load_kg", 0) - step.get("from_load_kg", 0) - lp.step_kg(step.get("from_load_kg", 0), lp.gain_rule()))
            < 1e-6,
        }
        misses += [f"{tid} as of {as_of}: {k} ({verdict['reason']})" for k, ok in checks.items() if not ok]
    assert not misses, "\n".join(misses)


def test_the_db_curl_window_after_his_own_raise_is_not_step_due():
    """Through 10-18 the curl moved (27.5 x 12 -> 30 x 10 -> 27.5 x 12): no identical run."""
    run = lp.stall_run(_history(DB_CURL))
    assert run["due"] is False and "changed on 10-15" in run["why"]


def test_with_a_rep_range_below_the_top_the_step_is_reps_at_the_same_load():
    step = lp.stall_step(_history(LEG_PRESS), rep_range=(8, 15))
    assert step["step_kind"] == lp.STEP_KIND_REPS and step["next_reps"] == 10
    assert step["next_load_kg"] == pytest.approx(_kg(360), abs=0.01)
    assert step["reason"].startswith("+2 reps to 10 at 360 lb: 360 lb x 8 3 times at self-reported RPE <= 8 (10-09, 10-13 and 10-16)")
    one = lp.stall_step(_history(LEG_PRESS), rep_range=(8, 9))
    assert one["next_reps"] == 9 and one["reason"].startswith("+1 rep to 9")  # never past the top


# ── the non-triggers ─────────────────────────────────────────────────────────────


def test_rpe_above_8_does_not_trigger():
    hist = json.loads(json.dumps(_history(CALF)))
    hist[1]["sets"][0]["rpe"] = 8.5  # 10-13's top set
    verdict = sd.assess_stall(_points(hist))
    assert verdict["verdict"] != sd.VERDICT_STEP_DUE
    assert "RPE 8.5 on 10-13, above 8" in lp.stall_run(hist)["why"]
    synthetic = [_session(d, 200, 10, 9.0) for d in ("2026-10-16", "2026-10-13", "2026-10-09")]
    assert lp.stall_step(synthetic, rep_range=(8, 12)) is None


def test_an_unlogged_rpe_is_not_evidence():
    synthetic = [_session(d, 200, 10, r) for d, r in (("2026-10-16", 7.0), ("2026-10-13", None), ("2026-10-09", 7.0))]
    assert "no RPE logged on 10-13" in lp.stall_run(synthetic)["why"]


def test_two_exposures_do_not_trigger():
    """Leg press as of 10-13: 360 x 10 on 10-06, then 360 x 8 twice — two identical, not three."""
    hist = _history(LEG_PRESS, "2026-10-13")
    assert lp.stall_run(hist)["due"] is False
    assert sd.assess_stall(_points(hist))["verdict"] != sd.VERDICT_STEP_DUE
    two = [_session(d, 200, 10, 7.0) for d in ("2026-10-16", "2026-10-13")]
    assert "2 of 3 exposures" in lp.stall_run(two)["why"]
    assert sd.assess_stall(_points(two))["verdict"] == sd.VERDICT_UNKNOWN


def test_a_lowered_exposure_count_is_not_hidden_behind_the_trend_floor(monkeypatch):
    """The detector's 3-session trend floor (MIN_SESSIONS) must not silently cap the charter's
    `consecutive_exposures`: lowered to 2, a two-exposure window IS step_due."""
    two = [_session(d, 200, 10, 7.0) for d in ("2026-10-16", "2026-10-13")]
    rule = dict(tc.charter_value("progression.stall_rule"), consecutive_exposures=2)
    monkeypatch.setattr(lp, "stall_rule", lambda: dict(rule))
    assert sd.assess_stall(_points(two))["verdict"] == sd.VERDICT_STEP_DUE


def test_a_fixed_load_with_changing_reps_is_not_a_stall():
    hist = [_session(d, 360, r, 7.5) for d, r in (("2026-10-16", 8), ("2026-10-13", 9), ("2026-10-09", 8))]
    verdict = sd.assess_stall(_points(hist))
    assert verdict["verdict"] not in (sd.VERDICT_STEP_DUE, sd.VERDICT_STALL)
    assert "load x reps changed on 10-13" in lp.stall_run(hist)["why"]


def test_short_of_a_prescription_is_his_not_the_plans():
    """He did 120 x 12 three times while the plan asked for 130: that is #3928's `stall`, not a step_due."""
    pts = [
        sd.SessionPoint(date=d, load_kg=_kg(120), reps=12, rpe=7.0, prescribed_load_kg=_kg(p), prescribed_reps=12)
        for d, p in (("2026-10-09", 120), ("2026-10-13", 125), ("2026-10-16", 130))
    ]
    verdict = sd.assess_stall(pts)
    assert verdict["verdict"] == sd.VERDICT_STALL


def test_at_a_matched_fixed_prescription_step_due_is_callable_where_stall_is_refused():
    pts = [
        sd.SessionPoint(date=d, load_kg=_kg(120), reps=12, rpe=7.5, prescribed_load_kg=_kg(120), prescribed_reps=12)
        for d in ("2026-10-09", "2026-10-13", "2026-10-16")
    ]
    verdict = sd.assess_stall(pts, rep_range=(8, 12))
    assert verdict["verdict"] == sd.VERDICT_STEP_DUE and "not a stall" in verdict["reason"]
    assert verdict["step"]["step_kind"] == lp.STEP_KIND_LOAD  # at the top of the range


# ── the draft paths carry it ─────────────────────────────────────────────────────


def test_the_generator_draft_carries_the_rep_step_and_its_reason():
    from training import routine_generator as rg

    catalog = rg._load_json("movement_catalog.json")
    assert catalog["movements"]["leg_press"]["hevy_template_id_hint"] == LEG_PRESS
    history = {LEG_PRESS: _history(LEG_PRESS)}
    weights = {d: 300.0 for d in ("2026-10-09", "2026-10-13", "2026-10-16", "2026-10-19")}
    block = ExerciseBlock(
        movement_key="leg_press",
        sets=[Set(type="normal", weight_kg=_kg(360), rep_range_start=8, rep_range_end=15) for _ in range(2)],
        rationale_tag="accessory:leg_press:accessory",
    )
    rationale: list[str] = []
    audit = rg._enforce_load_floors([block], catalog, history, weights, "2026-10-19", 3, 7, rationale)
    prog = audit["movements"]["leg_press"]["progression"]
    assert prog["basis"] == lp.BASIS_STEP and prog["trigger"] == lp.TRIGGER_STALL_RULE, prog
    assert prog["charter_version"] == tc.charter_version()
    assert all(s.rep_range_start == 10 and s.rep_range_end == 15 for s in block.sets)
    assert all(s.weight_kg == pytest.approx(_kg(360), abs=0.01) for s in block.sets)
    assert "+2 reps to 10 at 360 lb" in block.notes and "10-09, 10-13 and 10-16" in block.notes
    assert any("stall_rule" in line or "step" in line for line in rationale)


def test_the_generator_holds_the_stall_step_under_an_applied_deload():
    from training import routine_generator as rg

    catalog = rg._load_json("movement_catalog.json")
    weights = {d: 300.0 for d in ("2026-10-16", "2026-10-19")}
    block = ExerciseBlock(movement_key="leg_press", sets=[Set(type="normal", weight_kg=_kg(360), rep_range_start=8, rep_range_end=15)])
    audit = rg._enforce_load_floors(
        [block], catalog, {LEG_PRESS: _history(LEG_PRESS)}, weights, "2026-10-19", 3, 7, [], hold_reason="a deload the owner applied"
    )
    assert audit["movements"]["leg_press"]["progression"]["basis"] == lp.BASIS_HOLD
    assert block.sets[0].rep_range_start == 8


def test_apply_to_sets_raises_reps_never_lowers_and_skips_warmups():
    prog = {"basis": lp.BASIS_STEP, "step_kind": lp.STEP_KIND_REPS, "next_load_kg": _kg(100), "next_reps": 10}
    sets = [
        Set(type="warmup", weight_kg=_kg(50), reps=8),
        Set(type="normal", weight_kg=_kg(100), reps=8),
        Set(type="normal", weight_kg=_kg(100), rep_range_start=8, rep_range_end=9),
        Set(type="normal", weight_kg=_kg(100), reps=12),
    ]
    lines = lp.apply_to_sets(sets, prog)
    assert sets[0].reps == 8 and sets[1].reps == 10 and sets[2].rep_range_start == 9 and sets[3].reps == 12
    assert len(lines) == 2


def test_draft_custom_names_the_step_on_a_block_authored_below_it():
    from mcp.draft_custom_session import attach_step_due

    def _ir(lb: float, reps: int) -> RoutineSpec:
        return RoutineSpec(
            routine_id="r",
            target_date="2026-10-19",
            archetype="lower",
            variant="ideal",
            exercises=[ExerciseBlock(movement_key="leg_press", sets=[Set(type="normal", weight_kg=_kg(lb), reps=reps)])],
            inputs_snapshot={},
        )

    catalog = {"leg_press": {"hevy_template_id_hint": LEG_PRESS}}
    below = _ir(360, 8)
    rows = attach_step_due(below, catalog, history_reader=lambda: {LEG_PRESS: _history(LEG_PRESS)})
    assert rows[0]["carried"] is False and rows[0]["trigger"] == lp.TRIGGER_STALL_RULE
    assert below.exercises[0].sets[0].weight_kg == pytest.approx(_kg(360))  # ADR-069: the caller's load, verbatim
    assert "Step due: +" in below.exercises[0].notes and below.inputs_snapshot["step_due"] == rows

    carried = _ir(365, 8)
    rows = attach_step_due(carried, catalog, history_reader=lambda: {LEG_PRESS: _history(LEG_PRESS)})
    assert rows[0]["carried"] is True and "Step due" not in carried.exercises[0].notes

    # A block authored as a rep RANGE with no `reps` (a sanctioned draft_custom input) is read by
    # its load and its range's bottom — never dropped as a non-working set and falsely noted.
    def _ranged(lb: float, lo: int, hi: int) -> RoutineSpec:
        return RoutineSpec(
            routine_id="r",
            target_date="2026-10-19",
            archetype="lower",
            variant="ideal",
            exercises=[
                ExerciseBlock(
                    movement_key="leg_press",
                    sets=[
                        Set(type="warmup", weight_kg=_kg(500), reps=5),
                        Set(type="normal", weight_kg=_kg(lb), rep_range_start=lo, rep_range_end=hi),
                    ],
                )
            ],
            inputs_snapshot={},
        )

    above = _ranged(365, 10, 12)
    rows = attach_step_due(above, catalog, history_reader=lambda: {LEG_PRESS: _history(LEG_PRESS)})
    assert rows[0]["next_reps"] == 10 and rows[0]["carried"] is True
    assert "Step due" not in (above.exercises[0].notes or "")
    short = _ranged(360, 8, 12)
    rows = attach_step_due(short, catalog, history_reader=lambda: {LEG_PRESS: _history(LEG_PRESS)})
    assert rows[0]["carried"] is False and "Step due: +" in short.exercises[0].notes

    def _boom():
        raise RuntimeError("ddb down")

    failed = _ir(360, 8)
    assert attach_step_due(failed, catalog, history_reader=_boom) == []
    assert failed.inputs_snapshot["step_due"]["status"] == "failed"


def test_stall_check_reports_step_due(monkeypatch):
    from mcp import hevy_readback_report

    monkeypatch.setattr(hevy_readback_report, "_prescription_for", lambda w: (None, None))

    def _fake_get_workouts(page=1, page_size=10):
        if page > 1:
            return {"workouts": []}
        return {
            "workouts": [
                {"start_time": f"{s['date']}T17:30:00+00:00", "exercises": [{"template_id": LEG_PRESS, "sets": s["sets"]}]}
                for s in _history(LEG_PRESS)
            ]
        }

    out = hevy_readback_report.stall_check({"template_id": LEG_PRESS, "sessions": 3}, get_workouts=_fake_get_workouts)
    assert out["stall"]["verdict"] == sd.VERDICT_STEP_DUE
    assert out["step_due"]["dates"] == ["2026-10-09", "2026-10-13", "2026-10-16"]
