"""tests/test_progression_record_5762.py — the engine records the load steps it prescribes (#5762).

The block-1 retro (#5496) had to grade "Engine progression logic" from a session proxy that could not tell an
engine step from a load the owner raised himself. These pin the four acceptance boxes:

  1. each drafted routine records, per movement, the basis it applied and whether it was a `step_due` step
     (`inputs_snapshot.progression_basis`, stamped at `routine_repo.draft_versioned`);
  2. `block_progression` returns `steps_taken` (engine steps he then performed), `step_due` and `stalls` for a
     window, and `block_retro` reads it instead of a hand-supplied count;
  3. a self-raised load is counted as `progressed`, never as an engine step;
  4. the weekly panel's double-progression criterion reads the same record.
"""

from __future__ import annotations

import copy
import os
import sys
from unittest.mock import patch

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))

from training import block_retro, panel_rubric, progression_record as pr, routine_ir, routine_repo  # noqa: E402
from training.routine_ir import ExerciseBlock, RoutineSpec, Set  # noqa: E402

LB = 0.45359237
TID_PRESS, TID_ROW, TID_CURL = "AAAA0001", "BBBB0002", "CCCC0003"


def _block(key: str, lb: float, reps: int = 8) -> ExerciseBlock:
    return ExerciseBlock(movement_key=key, sets=[Set(weight_kg=lb * LB, reps=reps, rep_range_start=6, rep_range_end=10)] * 3)


def _generator_ir(day: str, status: str = "active", **progs) -> RoutineSpec:
    """A cron draft: `load_floors.movements[*].progression` as `routine_generator._progress_block` writes it."""
    loads = {"press": (TID_PRESS, 100.0), "row": (TID_ROW, 120.0), "curl": (TID_CURL, 30.0)}
    moves = {}
    for key, prog in progs.items():
        moves[key] = {"status": "ok", "template_id": loads[key][0], "progression": prog}
    return RoutineSpec(
        routine_id=f"r-{day}",
        target_date=day,
        archetype="upper",
        status=status,
        source_action="cron_generated",
        hevy_pushed_at="2026-10-01T00:00:00Z" if status != "draft" else None,
        exercises=[_block(k, loads[k][1]) for k in progs],
        inputs_snapshot={"load_floors": {"source": "routine_generator", "status": "applied", "movements": moves}},
    )


STEP_GAIN = {"basis": "step", "trigger": "gain_rule", "step_kind": "load", "next_load_kg": 100.0 * LB, "next_reps": 6, "reason": "+5 lb"}
STEP_DUE = {"basis": "step", "trigger": "stall_rule", "step_kind": "reps", "next_load_kg": 120.0 * LB, "next_reps": 9, "reason": "+1 rep"}
HOLD = {"basis": "hold", "reason": "hold 30 lb: 1 of 2 top sets"}
FLOOR = {"basis": "floor_raise", "reason": "floor 100 lb: you raised it"}


def _sess(day: str, lb: float, reps: int, rpe: float = 7.0) -> dict:
    return {"date": day, "sets": [{"weight_kg": lb * LB, "reps": reps, "rpe": rpe}], "top_weight_kg": lb * LB}


CATALOG = {
    "movements": {
        "press": {"hevy_template_id_hint": TID_PRESS, "anchor_family": "press"},
        "row": {"hevy_template_id_hint": TID_ROW, "anchor_family": "row"},
        "curl": {"hevy_template_id_hint": TID_CURL},
    }
}


# ── box 1: the record ─────────────────────────────────────────────────────────────


def test_each_draft_records_the_basis_it_applied_and_whether_it_was_a_step_due_step():
    rec = pr.movement_record(_generator_ir("2026-10-23", press=STEP_GAIN, row=STEP_DUE, curl=HOLD))
    assert rec["press"]["basis"] == "step" and rec["press"]["step_due"] is False and rec["press"]["applied"] is True
    assert rec["row"]["basis"] == "step" and rec["row"]["step_due"] is True and rec["row"]["trigger"] == "stall_rule"
    assert rec["curl"]["basis"] == "hold" and rec["curl"]["step_due"] is False and rec["curl"]["applied"] is False
    assert {r["source"] for r in rec.values()} == {pr.SRC_GENERATOR}
    assert rec["press"]["template_id"] == TID_PRESS


def test_a_chat_draft_records_its_step_due_rows_and_names_the_rest_as_authored():
    ir = RoutineSpec(
        routine_id="r-chat",
        target_date="2026-10-25",
        archetype="upper",
        source_action="draft_custom",
        exercises=[_block("press", 100.0), _block("row", 120.0)],
        inputs_snapshot={"step_due": [{"movement_key": "row", "carried": False, **STEP_DUE}]},
    )
    rec = pr.movement_record(ir)
    assert rec["row"] == {**rec["row"], "basis": "step", "step_due": True, "applied": False, "source": pr.SRC_CHAT_STEP}
    assert rec["press"]["basis"] is None and rec["press"]["source"] == pr.SRC_CHAT  # the engine applied no basis: said so


def test_a_re_entry_variant_records_re_entry_on_every_movement():
    ir = RoutineSpec(routine_id="r-re", target_date="2026-10-25", archetype="upper", variant="re_entry", exercises=[_block("press", 60.0)])
    assert pr.movement_record(ir)["press"]["basis"] == "re_entry"


def test_draft_versioned_stamps_the_record_on_every_drafted_plan():
    written = []
    ir = _generator_ir("2026-10-23", status="draft", press=STEP_GAIN, row=STEP_DUE)
    with patch.object(routine_repo, "get_current", return_value=None), patch.object(routine_repo, "put_versioned", written.append):
        routine_repo.draft_versioned(ir)
    stamped = written[0].inputs_snapshot[pr.RECORD_KEY]
    assert stamped["recorded_by"] == pr.RECORDED_BY and stamped["movements"]["row"]["step_due"] is True
    # survives the DDB round trip the committed version takes
    back = routine_ir.deserialize(routine_ir.serialize(written[0]))
    assert pr.record_of(back)["recorded"] is True and pr.record_of(back)["movements"]["press"]["basis"] == "step"


def test_a_stamp_that_cannot_be_built_never_blocks_the_draft():
    ir = _generator_ir("2026-10-23", status="draft", press=STEP_GAIN)
    with patch.object(pr, "movement_record", side_effect=RuntimeError("boom")):
        routine_repo.stamp_progression_basis(ir)
    assert ir.inputs_snapshot[pr.RECORD_KEY]["status"] == "failed"
    assert pr.record_of(ir)["recorded"] is False and pr.record_of(ir)["movements"]["press"]["basis"] == "step"  # derived instead


# ── boxes 2 + 3: the block reader ─────────────────────────────────────────────────


def _block_fixture():
    routines = [
        # 10-20: an engine load step (press -> 100) he performed at 100; a stall-rule rep step (row 9 reps) he did 8 of
        _generator_ir("2026-10-20", press=STEP_GAIN, row=STEP_DUE, curl=HOLD),
        # 10-22: the engine held curl at 30; he raised it himself to 35 at RPE 8 — progressed, NOT an engine step
        _generator_ir("2026-10-22", press=HOLD, curl=HOLD),
        # 10-24: an engine step he never performed that day
        _generator_ir("2026-10-24", press=STEP_GAIN),
        # an uncommitted draft and an out-of-window routine are never counted
        _generator_ir("2026-10-21", status="draft", press=STEP_GAIN),
        _generator_ir("2026-11-30", press=STEP_GAIN),
    ]
    history = {
        TID_PRESS: [_sess("2026-10-22", 100.0, 8), _sess("2026-10-20", 100.0, 6)],
        TID_ROW: [_sess("2026-10-20", 120.0, 8)],
        TID_CURL: [_sess("2026-10-22", 35.0, 8, rpe=8.0), _sess("2026-10-20", 30.0, 8)],
    }
    return routines, history


def test_the_block_reader_counts_engine_steps_he_performed_step_due_and_self_raised_loads_apart():
    routines, history = _block_fixture()
    out = pr.block_progression(routines, history, start="2026-10-19", end="2026-10-25", catalog=CATALOG)
    assert out["committed_routines"] == 3 and out["routines_in_window"] == 4
    assert out["steps_prescribed"] == 3  # press 10-20, row 10-20, press 10-24
    assert out["steps_taken"] == 1, out["steps"]  # only the press step he performed at its load
    assert out["steps_short"] == 1 and out["steps_not_performed"] == 1
    assert out["step_due"] == 1
    assert out["progressed"] == 1  # the curl he raised himself
    assert out["derived_routines"] == 3 and out["recorded_routines"] == 0
    taken = {(r["date"], r["movement_key"]): r["taken"] for r in out["steps"]}
    assert taken == {("2026-10-20", "press"): True, ("2026-10-20", "row"): False, ("2026-10-24", "press"): False}


def test_a_self_raised_load_is_never_an_engine_step():
    """Box 3's control: the same curl raise, read with a hold — counted `progressed` and nowhere in the steps."""
    routines, history = _block_fixture()
    out = pr.block_progression(routines[1:2], history, start="2026-10-19", end="2026-10-25", catalog=CATALOG)
    assert out["progressed"] == 1 and out["steps_taken"] == 0 and out["steps_prescribed"] == 0 and out["steps"] == []


def test_without_a_catalog_the_self_raised_count_is_absent_not_zero():
    routines, history = _block_fixture()
    assert pr.block_progression(routines, history, start="2026-10-19", end="2026-10-25")["progressed"] is None


def test_the_stored_record_is_read_before_the_snapshot_it_was_built_from():
    ir = pr.stamp(_generator_ir("2026-10-20", press=STEP_GAIN))
    ir.inputs_snapshot["load_floors"]["movements"]["press"]["progression"] = HOLD  # a later rewrite of load_floors
    out = pr.block_progression([ir], {TID_PRESS: [_sess("2026-10-20", 100.0, 6)]}, start="2026-10-20", end="2026-10-20")
    assert out["recorded_routines"] == 1 and out["steps_taken"] == 1


def test_a_stall_is_called_from_the_blocks_prescribed_vs_performed_points():
    """Prescription climbs 100 -> 105 -> 110 lb x 8; he logs a flat e1RM: `assess_stall` calls a stall."""
    routines, history = [], {TID_PRESS: []}
    for day, lb in (("2026-10-20", 100.0), ("2026-10-22", 105.0), ("2026-10-24", 110.0), ("2026-10-26", 115.0)):
        routines.append(_generator_ir(day, press=HOLD))
        routines[-1].exercises[0].sets = [Set(weight_kg=lb * LB, reps=8)]
        history[TID_PRESS].insert(0, _sess(day, 100.0, 8, rpe=9.0))
    out = pr.block_progression(routines, history, start="2026-10-19", end="2026-10-31")
    assert out["stalls"] == 1 and out["stalled_movements"] == ["press"]


# ── box 2: the retro reads the record, never a hand count ─────────────────────────


def test_the_retro_grades_the_progression_row_from_the_record_and_ignores_a_hand_count():
    window = block_retro.block_window("2026-11-08")
    rec = {"steps_prescribed": 4, "steps_taken": 3, "step_due": 1, "stalls": 0, "progressed": 7}
    ev = block_retro.assemble_evidence(window, supplied={"progression": {"steps_taken": 99, "step_due": 0}}, progression=rec)
    cells = ev["progression"]
    assert cells["steps_taken"]["value"] == 3 and cells["step_due"]["value"] == 1 and cells["progressed"]["value"] == 7
    assert cells["step_opportunities"]["value"] == 4 and "progression_record" in cells["steps_taken"]["source"]
    no_record = block_retro.assemble_evidence(window, supplied={"progression": {"steps_taken": 99, "step_due": 0}})["progression"]
    assert all(c["state"] == block_retro.ABSENT for c in no_record.values()), "the hand count is retired: absent, never read"


# ── box 4: the weekly panel reads the same record ─────────────────────────────────


def _case(*routines: RoutineSpec) -> dict:
    return {"constraint_block": {}, "routines": [routine_ir.serialize(r) for r in routines]}


def test_the_panels_double_progression_criterion_reads_the_record():
    ir = pr.stamp(_generator_ir("2026-10-20", press=STEP_GAIN, row=STEP_DUE, curl=HOLD))
    ir.inputs_snapshot.pop("load_floors")  # only the stamped record is left
    feats = panel_rubric.plan_features(_case(ir), CATALOG)
    by_key = {r["key"]: r["progression"] for r in feats["lifts"]}
    assert by_key["row"]["step_due"] is True and by_key["press"]["basis"] == "step"
    score, why = panel_rubric.check_double_progression(feats)
    assert score == 10.0, why
    frozen = _case(ir)
    panel_rubric._freeze_progression({**frozen, "constraint_block": {}})
    assert panel_rubric.check_double_progression(panel_rubric.plan_features(frozen, CATALOG))[0] == 0.0, "the freeze control strips it"


def test_the_panel_and_the_block_reader_see_the_same_bases():
    ir = _generator_ir("2026-10-20", press=STEP_GAIN, row=STEP_DUE, curl=HOLD)
    feats = panel_rubric.plan_features(_case(copy.deepcopy(ir)), CATALOG)
    assert {r["key"]: r["progression"]["basis"] for r in feats["lifts"]} == {
        k: v["basis"] for k, v in pr.record_of(ir)["movements"].items()
    }
