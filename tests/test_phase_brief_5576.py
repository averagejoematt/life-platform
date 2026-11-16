"""tests/test_phase_brief_5576.py — #5576: the computed phase reaches the coach packet and plan_next_session.

The weekly phase evaluator (#5575) writes PHASE#STATE / PHASE#EVAL rows. `training.phase_evaluator.phase_brief` arranges
them into the field both coaching surfaces carry — the current phase, the next phase, and the closest unmet gate WITH its
measured value — and `mcp.phase_evaluator_leg.phase_brief_field` is the one read both call. The rows below are built by
the evaluator's own row builders (`eval_row` / `state_row`), so the fixture is the wire, not a hand-typed shape.
"""

from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (ROOT, os.path.join(ROOT, "lambdas")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from training import phase_evaluator as pe  # noqa: E402

CHARTER = {
    "version": "test",
    "phases": {
        "order": ["foundation", "build", "forge", "sustain"],
        "definitions": {
            "foundation": {"title": "Foundation"},
            "build": {"title": "Build"},
            "forge": {"title": "Forge"},
            "sustain": {"title": "Sustain"},
        },
    },
}

WEIGHT_GATE = {
    "id": "weight_under_build_line",
    "group": "entry_gates",
    "metric": "weight_trend_7d_lb",
    "comparator": "<=",
    "value": [{"as_of": "2026-11-15", "mean_lbs": 231.4, "n": 5, "verdict": "not_met"}],
    "verdict": "not_met",
    "detail": "7-day mean at or under the threshold on 0 of 2 weekly checkpoints (1 measured)",
    "ref": "owner_twin:goal_weight",
    "threshold_private": True,
    "held_for": 2,
}
PAIN_GATE = {
    "id": "no_pain",
    "group": "every_transition",
    "metric": "joint_or_lower_leg_pain_flags",
    "comparator": "none_in_window",
    "value": {"live_flags": []},
    "verdict": "met",
    "detail": "no live pain flag in the window",
}


def _state(stage="foundation", since="2026-09-06"):
    return pe.state_row(CHARTER, {"stage": stage, "since": since, "pending": None, "origin": "seed"}, updated_at="2026-11-16T15:30:00Z")


def _eval(phase="foundation", gates=(WEIGHT_GATE, PAIN_GATE), blocking="weight_under_build_line"):
    blocking_gate = next(({"id": g["id"], "verdict": g["verdict"], "detail": g["detail"]} for g in gates if g["id"] == blocking), None)
    return pe.eval_row(
        CHARTER,
        week_start="2026-11-09",
        week_end="2026-11-15",
        state_before={"stage": phase},
        evaluation={
            "next": pe.sm.next_stage(pe.order(CHARTER), phase),
            "gates": list(gates),
            "verdict": "not_met",
            "blocking_gate": blocking_gate,
        },
        step={"action": "none", "state": {"stage": phase, "pending": None}},
        reads={},
    )


def test_brief_carries_current_next_and_the_closest_unmet_gate_with_its_value():
    """Mutation: drop the gate's measured value (the coach can only say 'a gate is unmet'), or re-rank the gates here."""
    brief = pe.phase_brief(_state(), _eval())
    assert (brief["phase"], brief["phase_title"], brief["since"]) == ("foundation", "Foundation", "2026-09-06")
    assert (brief["next_phase"], brief["next_phase_title"]) == ("build", "Build")
    gate = brief["closest_unmet_gate"]
    assert gate["id"] == "weight_under_build_line" and gate["verdict"] == "not_met"
    assert gate["value"] == WEIGHT_GATE["value"]  # the measured 7-day means, from the EVAL row
    assert gate["threshold_private"] is True and "threshold" not in gate  # the goal weight is never copied out
    assert brief["evaluated_week"] == {"start": "2026-11-09", "end": "2026-11-15"}


def test_an_any_of_blocking_unit_carries_each_members_value():
    a = {**PAIN_GATE, "id": "a", "verdict": "not_met", "value": 1}
    b = {**PAIN_GATE, "id": "b", "verdict": "unknown", "value": None}
    row = _eval(gates=(a, b), blocking="a")
    row["blocking_gate"] = {"id": "a | b", "verdict": "not_met", "detail": "any one of these gates"}
    gate = pe.phase_brief(_state(), row)["closest_unmet_gate"]
    assert [m["id"] for m in gate["members"]] == ["a", "b"] and gate["members"][0]["value"] == 1


def test_an_eval_about_the_previous_phase_is_not_reported_as_the_next_gate():
    """Mutation: report the old EVAL's blocking gate after a transition (it gated the phase he already entered)."""
    brief = pe.phase_brief(_state(stage="build", since="2026-11-16"), _eval(phase="foundation"), CHARTER)
    assert (brief["phase"], brief["phase_title"], brief["next_phase"], brief["next_phase_title"]) == ("build", "Build", "forge", "Forge")
    assert brief["closest_unmet_gate"] is None and "note" in brief


def test_no_state_row_is_no_brief():
    assert pe.phase_brief(None, _eval()) is None


def test_title_phase_reads_the_state_rows_title_and_since():
    assert pe.title_phase(_state(stage="build", since="2026-11-16")) == ("Build", "2026-11-16")
    assert pe.title_phase(None) is None
    assert pe.title_phase({"stage": "forge", "since": None}) == ("Forge", None)


# ── the one read both surfaces call ───────────────────────────────────────────────────────────
class _Table:
    def __init__(self, state=None, latest=None, boom=False):
        self.state, self.latest, self.boom = state, latest, boom

    def get_item(self, Key=None, **kw):
        if self.boom:
            raise RuntimeError("ddb down")
        return {"Item": self.state} if self.state else {}

    def query(self, **kw):
        return {"Items": [self.latest] if self.latest else []}


def test_field_states_measured_absent_and_read_failed():
    """Mutation: report a failed read as 'no phase' (absent), or a missing STATE row as a failure."""
    from mcp.phase_evaluator_leg import phase_brief_field

    value, status = phase_brief_field(_Table(_state(), _eval()))
    assert status["state"] == "measured" and value["closest_unmet_gate"]["id"] == "weight_under_build_line"
    value, status = phase_brief_field(_Table())
    assert value is None and status["state"] == "absent"
    value, status = phase_brief_field(_Table(boom=True))
    assert value is None and status["state"] == "read_failed" and "RuntimeError" in str(status.get("error"))


def test_coach_packet_and_plan_carry_the_same_field(monkeypatch):
    """Mutation: drop `training_phase` from the packet's READERS or from plan_next_session's output."""
    from mcp import phase_evaluator_leg as pel, tools_coach_packet as pkt, tools_plan

    monkeypatch.setattr(pel, "phase_brief_field", lambda table=None: (pe.phase_brief(_state(), _eval()), {"state": "measured"}))
    assert pkt.READERS["training_phase"] is pkt._training_phase and "training_phase" in pkt.SOURCES
    value, status = pkt._training_phase("2026-11-18")
    assert status["state"] == "measured" and value["next_phase"] == "build"
    field = tools_plan._training_phase_field()
    assert field["state"] == "measured" and field["value"]["closest_unmet_gate"]["value"] == WEIGHT_GATE["value"]
    src = open(os.path.join(ROOT, "mcp", "tools_plan.py"), encoding="utf-8").read()
    # #5772: the field is built beside exercise_unlocks by `_training_fields`, which plan_next_session merges into its output
    assert '"training_phase": _training_phase_field()' in src and "out.update(_training_fields(" in src
