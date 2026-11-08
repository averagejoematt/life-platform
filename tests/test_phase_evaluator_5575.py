"""tests/test_phase_evaluator_5575.py — the weekly phase evaluator is pinned to the charter (#5575).

# premerge-gate: a contract test — every phase, gate, metric, comparator and reference in config/training_charter.json `phases` has evaluator support in training.phase_evaluator

The charter's `phases` section (#5574) is data; `training.phase_evaluator` is the only code that reads it to move the
phase. The contract: a phase or gate the charter grows without evaluator support FAILS THE BUILD here
(`phase_evaluator.unsupported`), so a new gate can never sit as `unknown` forever while looking evaluated. The negative
controls mutate a copy of the live section and assert each fault is named.

Beside the contract: the verdict rules (missing data is unknown, never met and never not_met), the stage machine
(proposal -> next block start, veto, override, no regression), the rows (EVAL written last, no owner-only threshold
copied into a row), the leg's fail-soft wiring on the panel-grade run, the owner's tool, and the qa-smoke dead-man.
Every date below is a literal — nothing here reads the clock.
"""

from __future__ import annotations

import ast
import copy
import json
import os
import pathlib
import sys
from typing import Any

import pytest

_REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO / "lambdas"))
sys.path.insert(0, str(_REPO))
os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")

from training import (
    phase_evaluator as pe,  # noqa: E402
    stage_machine as sm,  # noqa: E402
)

_CHARTER = json.loads((_REPO / "config" / "training_charter.json").read_text())
_GOAL = 199.5  # a test-only twin value: never a real one


def _with_twin(charter: dict, goal: Any = _GOAL) -> dict:
    c = copy.deepcopy(charter)
    c["target_picture"] = {"weight_band_lb": [180.0, goal]}
    return c


# ── the contract ─────────────────────────────────────────────────────────────────────────────────────────────────────
def test_the_live_charter_is_fully_supported():
    assert pe.unsupported(_CHARTER) == []


def test_every_supported_metric_has_exactly_one_evaluator():
    assert set(pe._EVALUATORS) == set(pe.SUPPORTED_METRICS)


def _mutated(fn) -> list[str]:
    c = copy.deepcopy(_CHARTER)
    fn(c["phases"])
    return pe.unsupported(c)


def test_a_new_phase_without_support_fails_the_build():
    def m(ph):
        ph["order"].append("transcend")
        ph["definitions"]["transcend"] = {"title": "Transcend", "entry_gates": [{"id": "vo2", "metric": "vo2max", "comparator": ">="}]}

    assert any("metric 'vo2max' has no evaluator" in p for p in _mutated(m))


def test_a_later_phase_with_no_gate_is_named():
    def m(ph):
        ph["order"].append("coast")
        ph["definitions"]["coast"] = {"title": "Coast"}

    assert any("no entry gate could never be proposed" in p for p in _mutated(m))


def test_a_defined_phase_missing_from_the_order_is_named():
    def m(ph):
        ph["definitions"]["limbo"] = {"title": "Limbo", "entry_gates": []}

    assert any("not in phases.order" in p for p in _mutated(m))


def test_a_new_gate_on_an_existing_phase_without_support_is_named():
    def m(ph):
        ph["definitions"]["build"]["entry_gates"].append({"id": "waist", "metric": "waist_in", "comparator": "<=", "value_ref": "x"})

    assert any("metric 'waist_in'" in p for p in _mutated(m))


def test_an_unimplemented_comparator_is_named():
    def m(ph):
        ph["definitions"]["build"]["entry_gates"][0]["comparator"] = "<"

    assert any("comparator '<'" in p for p in _mutated(m))


def test_a_new_shared_transition_rule_without_support_is_named():
    def m(ph):
        ph["every_transition"]["sleep"] = {"metric": "sleep_hours_mean", "comparator": ">=", "value_ref": "x"}

    assert any("every_transition.sleep" in p for p in _mutated(m))


def test_an_unread_gate_ref_is_named():
    def m(ph):
        ph["definitions"]["forge"]["entry_gates"][0]["gate_ref"] = "gated_movements.power_clean"

    assert any("gate_ref 'gated_movements.power_clean' has no reader" in p for p in _mutated(m))


def test_a_held_for_on_a_non_series_gate_is_named():
    def m(ph):
        ph["definitions"]["forge"]["entry_gates"][0]["held_for"] = "advance.consecutive_evaluations"

    assert any("held_for on 'gate_state'" in p for p in _mutated(m))


def test_a_new_phases_rule_key_and_a_new_definition_key_are_named():
    def m(ph):
        ph["demotion"] = {"rule": "on a lapse"}
        ph["definitions"]["build"]["exit_gates"] = []

    probs = _mutated(m)
    assert any("phases.demotion" in p for p in probs) and any("build.exit_gates" in p for p in probs)


def test_a_changed_advance_rule_is_named():
    def m(ph):
        ph["advance"]["takes_effect"] = "immediately"
        ph["advance"]["regression"] = True

    probs = _mutated(m)
    assert any("takes_effect" in p for p in probs) and any("regression must be false" in p for p in probs)


def test_an_undocumented_owner_alias_is_named():
    def m(ph):
        ph["definitions"]["sustain"]["entry_gates_any_of"][1]["value_ref"] = "owner_twin:goal_waist"

    assert any("OWNER_TWIN_REFS" in p for p in _mutated(m))


def test_the_5574_contract_imports_the_one_alias_map():
    """One map: the #5574 contract test imports OWNER_TWIN_REFS from the evaluator and assigns none of its own."""
    src = (_REPO / "tests" / "test_training_phases_charter_5574.py").read_text()
    tree = ast.parse(src)
    assigns = [
        n for n in ast.walk(tree) if isinstance(n, ast.Assign) and any(getattr(t, "id", None) == "OWNER_TWIN_REFS" for t in n.targets)
    ]
    imports = [n for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module == "training.phase_evaluator"]
    assert not assigns and any(a.name == "OWNER_TWIN_REFS" for n in imports for a in n.names)


# ── the stage machine ────────────────────────────────────────────────────────────────────────────────────────────────
def test_verdict_combinators_never_let_unknown_pass():
    assert sm.all_of([sm.MET, sm.UNKNOWN]) == sm.UNKNOWN
    assert sm.all_of([sm.MET, sm.UNKNOWN, sm.NOT_MET]) == sm.NOT_MET
    assert sm.all_of([sm.MET, sm.MET]) == sm.MET
    assert sm.any_of([sm.NOT_MET, sm.UNKNOWN]) == sm.UNKNOWN
    assert sm.any_of([sm.NOT_MET, sm.MET]) == sm.MET
    assert sm.any_of([sm.NOT_MET]) == sm.NOT_MET
    assert sm.held([sm.MET], 2) == sm.UNKNOWN  # one week is not yet two
    assert sm.held([sm.MET, sm.UNKNOWN], 2) == sm.UNKNOWN
    assert sm.held([sm.MET, sm.NOT_MET], 2) == sm.NOT_MET
    assert sm.held([sm.MET, sm.MET, sm.NOT_MET], 2) == sm.MET


ORDER = ["foundation", "build", "forge", "sustain"]
STATE0 = {"stage": "foundation", "since": "2026-09-06", "pending": None, "origin": "seed"}


def test_all_met_writes_a_proposal_not_a_transition():
    out = sm.step(ORDER, STATE0, as_of="2026-11-15", next_verdict=sm.MET, boundaries=["2026-10-20"], eval_key="E1")
    assert out["action"] == "proposed" and out["transition"] is None
    assert out["state"]["stage"] == "foundation" and out["state"]["pending"]["to"] == "build"


def test_a_proposal_takes_effect_at_the_next_block_start_and_not_before():
    pending = {**STATE0, "pending": {"to": "build", "proposed_on": "2026-11-15", "status": sm.PENDING, "eval_key": "E1"}}
    wait = sm.step(ORDER, pending, as_of="2026-11-22", next_verdict=sm.NOT_MET, boundaries=["2026-10-20"])
    assert wait["action"] == "pending" and wait["state"]["stage"] == "foundation"
    applied = sm.step(ORDER, pending, as_of="2026-12-06", next_verdict=sm.NOT_MET, boundaries=["2026-10-20", "2026-12-01"], eval_key="E3")
    assert applied["action"] == "applied"
    assert applied["transition"]["effective_on"] == "2026-12-01" and applied["transition"]["to"] == "build"
    assert applied["state"] == {**pending, "stage": "build", "since": "2026-12-01", "pending": None, "origin": sm.ORIGIN_EVALUATOR}


def test_an_unread_block_record_applies_nothing():
    pending = {**STATE0, "pending": {"to": "build", "proposed_on": "2026-11-15", "status": sm.PENDING}}
    out = sm.step(ORDER, pending, as_of="2026-12-06", next_verdict=sm.MET, boundaries=None)
    assert out["action"] == "pending_block_unread" and out["transition"] is None


def test_a_veto_holds_until_the_next_block_then_the_evaluator_may_propose_again():
    pending = {**STATE0, "pending": {"to": "build", "proposed_on": "2026-11-15", "status": sm.PENDING}}
    vetoed = sm.veto(pending, on="2026-11-17", words="not yet")
    held = sm.step(ORDER, vetoed, as_of="2026-11-22", next_verdict=sm.MET, boundaries=["2026-10-20"])
    assert held["action"] == "vetoed_until_next_block" and held["state"]["pending"]["status"] == sm.VETOED
    again = sm.step(ORDER, vetoed, as_of="2026-12-06", next_verdict=sm.MET, boundaries=["2026-10-20", "2026-12-01"])
    assert again["action"] == "proposed" and again["transition"] is None
    with pytest.raises(ValueError):
        sm.veto(STATE0, on="2026-11-17")


def test_the_phase_never_regresses():
    later = {**STATE0, "stage": "forge"}
    for to in ("build", "forge", "foundation"):
        with pytest.raises(ValueError):
            sm.override(ORDER, later, to=to, on="2026-11-20")
    moved = sm.override(ORDER, STATE0, to="build", on="2026-11-20", words="move me")
    assert moved["state"]["stage"] == "build" and moved["transition"]["origin"] == sm.ORIGIN_OVERRIDE
    # a stale proposal for an earlier phase never applies after an override moved past it
    stale = {**later, "pending": {"to": "build", "proposed_on": "2026-11-15", "status": sm.PENDING}}
    out = sm.step(ORDER, stale, as_of="2026-12-06", next_verdict=sm.NOT_MET, boundaries=["2026-12-01"])
    assert out["transition"] is None and out["state"]["stage"] == "forge"


def test_the_last_phase_has_nothing_to_propose():
    out = sm.step(ORDER, {**STATE0, "stage": "sustain"}, as_of="2026-11-15", next_verdict=sm.MET, boundaries=[])
    assert out["action"] == "final_stage" and out["proposal"] is None


# ── the gates ────────────────────────────────────────────────────────────────────────────────────────────────────────
def _inputs(**over: Any) -> dict[str, Any]:
    base = {
        "as_of": "2026-11-15",
        "weight_trend_7d_lb": [{"as_of": "2026-11-15", "mean_lbs": 270.0, "n": 6}, {"as_of": "2026-11-08", "mean_lbs": 272.0, "n": 5}],
        "sessions_by_week": [{"week_start": f"w{i}", "sessions": n} for i, n in enumerate([5, 4, 4, 4])],
        "pain_flags": {"window_start": "2026-11-02", "window_end": "2026-11-15", "live": []},
        "run_gate": {"gate_state": "closed", "weight_lb": 270.0, "gate_lb": 240, "holds_read": True},
    }
    return {**base, **over}


def _gate(ev: dict, gid: str) -> dict:
    return next(g for g in ev["gates"] if g["id"] == gid)


def test_foundation_to_build_meets_when_the_7d_trend_holds_two_weeks():
    ev = pe.evaluate_next(_CHARTER, "foundation", _inputs())
    assert ev["next"] == "build" and ev["verdict"] == pe.MET and ev["blocking_gate"] is None
    assert _gate(ev, "weight_at_deadlift_gate")["threshold"] == _CHARTER["gated_movements"]["conventional_deadlift"]["gate_lb"]


def test_one_week_under_the_gate_is_not_yet_held():
    ev = pe.evaluate_next(
        _CHARTER,
        "foundation",
        _inputs(
            weight_trend_7d_lb=[{"as_of": "2026-11-15", "mean_lbs": 270.0, "n": 6}, {"as_of": "2026-11-08", "mean_lbs": 280.0, "n": 6}]
        ),
    )
    assert _gate(ev, "weight_at_deadlift_gate")["verdict"] == pe.NOT_MET
    assert ev["blocking_gate"]["id"] == "weight_at_deadlift_gate"


def test_missing_data_is_unknown_never_not_met():
    ev = pe.evaluate_next(
        _CHARTER,
        "foundation",
        _inputs(
            weight_trend_7d_lb=[{"as_of": "2026-11-15", "mean_lbs": None, "n": 2}, {"as_of": "2026-11-08", "mean_lbs": 270.0, "n": 5}],
            sessions_by_week=[{"week_start": "a", "sessions": None}] * 4,
            pain_flags={"live": None, "error": "hevy unread"},
        ),
    )
    for gid in ("weight_at_deadlift_gate", "consistency", "no_pain_flag"):
        assert _gate(ev, gid)["verdict"] == pe.UNKNOWN, gid
    assert ev["verdict"] == pe.UNKNOWN and ev["blocking_gate"]["verdict"] == pe.UNKNOWN


def test_the_consistency_rule_reads_three_of_four_weeks():
    def v(counts):
        ev = pe.evaluate_next(
            _CHARTER, "foundation", _inputs(sessions_by_week=[{"week_start": str(i), "sessions": n} for i, n in enumerate(counts)])
        )
        return _gate(ev, "consistency")["verdict"]

    assert v([7, 7, 7, 5]) == pe.MET
    assert v([4, 4, 3, 4]) == pe.MET  # one disruption week is allowed
    assert v([4, 3, 3, 4]) == pe.NOT_MET
    assert v([4, 4, None, 3]) == pe.UNKNOWN  # the unmeasured week could still make it three
    assert v([3, 3, None, 4]) == pe.NOT_MET  # even a met unmeasured week cannot


def test_a_live_pain_flag_blocks_and_names_itself():
    ev = pe.evaluate_next(
        _CHARTER, "foundation", _inputs(pain_flags={"live": [{"movement": "Walking", "site": "left shin", "note_dates": ["2026-11-10"]}]})
    )
    assert _gate(ev, "no_pain_flag")["verdict"] == pe.NOT_MET and ev["blocking_gate"]["id"] == "no_pain_flag"


def test_the_run_gate_verdicts():
    assert pe.run_gate_verdict({"gate_state": "open"})[0] == pe.MET
    assert pe.run_gate_verdict({"gate_state": "closed"})[0] == pe.NOT_MET
    assert pe.run_gate_verdict({"gate_state": "held"})[0] == pe.NOT_MET
    assert pe.run_gate_verdict({"gate_state": "unknown"})[0] == pe.UNKNOWN
    assert pe.run_gate_verdict(None)[0] == pe.UNKNOWN
    assert pe.run_gate_verdict({"gate_state": "prep", "weight_lb": 245, "gate_lb": 240, "holds_read": False})[0] == pe.NOT_MET
    assert pe.run_gate_verdict({"gate_state": "prep", "weight_lb": 238, "gate_lb": 240, "holds_read": False})[0] == pe.UNKNOWN
    assert (
        pe.run_gate_verdict({"gate_state": "prep", "weight_lb": 238, "gate_lb": 240, "holds_read": True, "walking_unknown": True})[0]
        == pe.UNKNOWN
    )
    assert pe.run_gate_verdict({"gate_state": "prep", "weight_lb": 238, "gate_lb": 240, "holds_read": True})[0] == pe.NOT_MET


def test_build_to_forge_reads_the_run_gate():
    ev = pe.evaluate_next(_CHARTER, "build", _inputs(run_gate={"gate_state": "open"}))
    assert ev["next"] == "forge" and _gate(ev, "run_gate_open")["verdict"] == pe.MET and ev["verdict"] == pe.MET


def test_sustain_without_the_twin_is_unknown_and_never_met_by_weight():
    early = _inputs(as_of="2026-11-15", weight_trend_7d_lb=[{"as_of": "2026-11-15", "mean_lbs": 150.0, "n": 7}] * 2)
    ev = pe.evaluate_next(_CHARTER, "forge", early)  # the public charter alone: no twin
    goal = _gate(ev, "goal_weight_reached")
    assert goal["verdict"] == pe.UNKNOWN and goal["threshold_private"] is True and "threshold" not in goal
    assert _gate(ev, "phase_one_ended")["verdict"] == pe.NOT_MET
    assert ev["verdict"] == pe.UNKNOWN  # any_of(not_met, unknown)
    met = pe.evaluate_next(_with_twin(_CHARTER), "forge", early)
    assert _gate(met, "goal_weight_reached")["verdict"] == pe.MET and met["verdict"] == pe.MET
    dated = pe.evaluate_next(_CHARTER, "forge", {**early, "as_of": _CHARTER["governing_goal"]["target_date"]})
    assert dated["verdict"] == pe.MET


def test_no_row_ever_carries_the_owner_only_goal_weight():
    c = _with_twin(_CHARTER)
    ev = pe.evaluate_next(c, "forge", _inputs(weight_trend_7d_lb=[{"as_of": "2026-11-15", "mean_lbs": 190.0, "n": 7}] * 2))
    step = sm.step(pe.order(c), {**STATE0, "stage": "forge"}, as_of="2026-11-15", next_verdict=ev["verdict"], boundaries=[])
    row = pe.eval_row(
        c, week_start="2026-11-09", week_end="2026-11-15", state_before={"stage": "forge"}, evaluation=ev, step=step, reads={}
    )
    assert str(_GOAL) not in json.dumps(row)


def test_the_rows_are_owner_only_and_keyed_as_documented():
    ev = pe.evaluate_next(_CHARTER, "foundation", _inputs())
    step = sm.step(
        pe.order(_CHARTER), STATE0, as_of="2026-11-15", next_verdict=ev["verdict"], boundaries=[], eval_key="PHASE#EVAL#2026-11-09"
    )
    row = pe.eval_row(
        _CHARTER, week_start="2026-11-09", week_end="2026-11-15", state_before=STATE0, evaluation=ev, step=step, reads={"hevy": "ok"}
    )
    assert row["pk"] == "USER#matthew#SOURCE#training_constraints" and row["sk"] == "PHASE#EVAL#2026-11-09"
    assert row["tier"] == "owner_only" and row["action"] == "proposed" and row["pending"]["to"] == "build"
    st = pe.state_row(_CHARTER, step["state"], updated_at="t")
    assert st["sk"] == "PHASE#STATE" and st["title"] == "Foundation"
    tr = pe.transition_row(_CHARTER, {"from": "foundation", "to": "build", "effective_on": "2026-12-01"}, recorded_at="t")
    assert tr["sk"] == "PHASE#TRANSITION#2026-12-01#build" and tr["to_title"] == "Build"
    schema = (_REPO / "docs" / "SCHEMA.md").read_text()
    for fam in ("PHASE#EVAL#<monday>", "PHASE#STATE", "PHASE#TRANSITION#<effective_on>#<to>"):
        assert fam in schema, fam


def test_the_seed_is_the_hevy_titles_phase():
    assert pe.seed_state(_CHARTER, "Build", "2026-10-01")["stage"] == "build"
    assert pe.seed_state(_CHARTER, "Nonsense", None)["stage"] == "foundation"


# ── the leg: reads, store order, fail-soft wiring ────────────────────────────────────────────────────────────────────
class _Table:
    def __init__(self, items: dict | None = None):
        self.items = dict(items or {})
        self.puts: list[str] = []

    def put_item(self, Item):
        self.items[(Item["pk"], Item["sk"])] = Item
        self.puts.append(Item["sk"])

    def get_item(self, Key):
        it = self.items.get((Key["pk"], Key["sk"]))
        return {"Item": it} if it else {}

    def query(self, **kw):
        return {"Items": []}


def test_weight_checkpoints_use_the_trailing_7d_mean():
    from mcp.phase_evaluator_leg import weight_checkpoints

    rows = [{"date": d, "weight_lbs": w} for d, w in [("2026-11-09", 271), ("2026-11-11", 270), ("2026-11-14", 269), ("2026-11-03", 280)]]
    cps = weight_checkpoints(rows, ["2026-11-15", "2026-11-08"])
    assert cps[0]["mean_lbs"] == 270.0 and cps[0]["n"] == 3 and cps[0]["window_start"] == "2026-11-09"
    assert cps[1]["mean_lbs"] is None and cps[1]["n"] == 1  # one weigh-in makes no claim
    assert all(c["mean_lbs"] is None for c in weight_checkpoints(None, ["2026-11-15"]))


def test_sessions_by_week_counts_distinct_performed_workouts():
    from mcp.phase_evaluator_leg import sessions_by_week

    hevy = [
        {"date": "2026-11-10", "workout_uid": "hevy:a"},
        {"date": "2026-11-10", "workout_uid": "hevy:a"},  # the same workout twice counts once
        {"date": "2026-11-12", "workout_uid": "hevy:b"},
        {"date": "2026-11-04", "workout_uid": "hevy:c"},
    ]
    weeks = sessions_by_week(hevy, "2026-11-09", 2)
    assert [w["sessions"] for w in weeks] == [2, 1]
    assert [w["sessions"] for w in sessions_by_week(None, "2026-11-09", 2)] == [None, None]


def test_pain_with_unread_dismissals_is_unknown():
    from mcp.phase_evaluator_leg import pain_read

    hevy = [{"date": "2026-11-10", "exercises": [{"name": "Walking", "notes": "left shin pain"}]}]
    assert pain_read(hevy, "2026-11-02", "2026-11-15", None, False)["live"] is None
    assert pain_read(None, "2026-11-02", "2026-11-15", None, False)["live"] is None
    assert pain_read([], "2026-11-02", "2026-11-15", None, False)["live"] == []
    live = pain_read(hevy, "2026-11-02", "2026-11-15", [], True)["live"]
    assert live and live[0]["note_dates"] == ["2026-11-10"]


def _patch_leg(monkeypatch, *, inputs, boundaries, charter=_CHARTER):
    from training import training_charter

    from mcp import phase_evaluator_leg as leg

    monkeypatch.setattr(training_charter, "load_charter", lambda: copy.deepcopy(charter))
    monkeypatch.setattr(leg, "gather", lambda c, ws, we: (inputs, {"withings": "ok"}))
    monkeypatch.setattr(leg, "block_boundaries", lambda today: boundaries)
    monkeypatch.setattr(leg, "seeded_state", lambda c: pe.seed_state(c, "Foundation", "2026-09-06"))
    import experiment.phase_taxonomy as tax

    monkeypatch.setattr(tax, "experiment_stamp_for", lambda pk, sk="", **kw: {})
    return leg


def test_a_week_seeds_state_proposes_and_writes_the_eval_row_last(monkeypatch):
    leg = _patch_leg(monkeypatch, inputs=_inputs(), boundaries=["2026-10-20"])
    t = _Table()
    out = leg.evaluate_week("2026-11-15", today="2026-11-16", table=t)
    assert out["seeded"] and out["action"] == "proposed" and out["phase"] == "foundation"
    assert t.puts == ["PHASE#STATE", "PHASE#EVAL#2026-11-09"]
    state = t.items[(pe.pk(), pe.SK_STATE)]
    assert state["pending"]["to"] == "build" and state["last_eval"] == "PHASE#EVAL#2026-11-09"

    leg2 = _patch_leg(monkeypatch, inputs=_inputs(), boundaries=["2026-10-20", "2026-11-26"])
    out2 = leg2.evaluate_week("2026-11-29", today="2026-11-30", table=t)
    assert out2["action"] == "applied" and out2["phase"] == "build"
    assert t.puts[-3:] == ["PHASE#TRANSITION#2026-11-26#build", "PHASE#STATE", "PHASE#EVAL#2026-11-23"]


def test_the_weekly_leg_never_raises(monkeypatch):
    from mcp import phase_evaluator_leg as leg

    def boom(*a, **k):
        raise RuntimeError("ddb down")

    monkeypatch.setattr(leg, "evaluate_week", boom)
    assert leg.weekly_leg("2026-11-15") == {"outcome": "failed", "error": "RuntimeError"}


def test_the_panel_grade_run_carries_the_leg_and_keeps_its_own_status(monkeypatch, capsys):
    from mcp import panel_weekly_grade as pwg, phase_evaluator_leg as leg

    monkeypatch.setattr(pwg, "run", lambda week_end=None: {"week_end": "2026-11-15", "status": "graded"})
    monkeypatch.setattr(leg, "weekly_leg", lambda week_end=None: {"outcome": "failed", "error": "RuntimeError"})
    out = json.loads(pwg.lambda_entry({"job": "panel_weekly_grade"})["body"])
    assert out["status"] == "graded" and out["phase"] == {"outcome": "failed", "error": "RuntimeError"}
    assert '"PanelGradeOutcome": 1' in capsys.readouterr().out  # the grade's dead-man datapoint is untouched


# ── the owner's tool ─────────────────────────────────────────────────────────────────────────────────────────────────
def _tool_env(monkeypatch, state: dict | None):
    import experiment.phase_taxonomy as tax
    from common import pacific_time
    from training import training_charter

    from mcp import config, tools_training_phase as leg

    t = _Table({(pe.pk(), pe.SK_STATE): {"pk": pe.pk(), "sk": pe.SK_STATE, **state}} if state else {})
    monkeypatch.setattr(config, "table", t)
    monkeypatch.setattr(training_charter, "load_charter", lambda: copy.deepcopy(_CHARTER))
    monkeypatch.setattr(tax, "experiment_stamp_for", lambda pk, sk="", **kw: {})
    monkeypatch.setattr(pacific_time, "pacific_today", lambda: "2026-11-20")
    return leg, t


def test_the_tool_vetoes_a_pending_proposal(monkeypatch):
    pending = {**STATE0, "pending": {"to": "build", "proposed_on": "2026-11-15", "status": sm.PENDING}}
    leg, t = _tool_env(monkeypatch, pending)
    out = leg.tool_manage_training_phase({"action": "veto", "words": "not yet"})
    assert out["state"]["pending"]["status"] == sm.VETOED and t.puts == ["PHASE#STATE"]
    again = leg.tool_manage_training_phase({"action": "veto"})
    assert "error" in json.dumps(again).lower()


def test_the_tool_overrides_forward_by_title_and_refuses_backwards(monkeypatch):
    leg, t = _tool_env(monkeypatch, {**STATE0, "stage": "build"})
    out = leg.tool_manage_training_phase({"action": "override", "to": "Forge"})
    assert out["state"]["stage"] == "forge" and t.puts == ["PHASE#TRANSITION#2026-11-20#forge", "PHASE#STATE"]
    back = leg.tool_manage_training_phase({"action": "override", "to": "foundation"})
    assert "never moves backwards" in json.dumps(back)


def test_the_tool_refuses_a_write_before_any_state_exists(monkeypatch):
    leg, t = _tool_env(monkeypatch, None)
    assert "NOT_FOUND" in json.dumps(leg.tool_manage_training_phase({"action": "veto"}))
    assert leg.tool_manage_training_phase({})["stored"] is False and t.puts == []


# ── the dead-man ─────────────────────────────────────────────────────────────────────────────────────────────────────
def test_the_dead_man_reds_a_missing_week_and_waits_for_its_arming():
    from operational import phase_eval_qa as qa

    assert qa.expected_week("2026-11-17") == "2026-11-09"  # Tuesday: the week just ended is due
    assert qa.expected_week("2026-11-16") == "2026-11-02"  # Monday: the run may not have happened yet
    assert qa.assess("2026-11-09", "2026-11-18")[0] == "ok"
    assert qa.assess("2026-11-02", "2026-11-18")[0] == "fail"
    assert qa.assess(None, "2026-11-10")[0] == "not_armed"
    assert qa.assess(None, qa.ARMED_ON)[0] == "fail"


def test_the_dead_man_is_wired_into_the_qa_smoke_sweep():
    src = (_REPO / "lambdas" / "operational" / "qa_smoke_lambda.py").read_text()
    assert '("phase_eval_liveness", lambda: phase_eval_qa.check_phase_eval_liveness(' in src
