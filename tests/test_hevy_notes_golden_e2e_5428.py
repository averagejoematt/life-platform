"""tests/test_hevy_notes_golden_e2e_5428.py — #5428: freshly RENDERED routines lint clean, with ONE session block.

The acceptance box is "a style linter runs in the suite over freshly rendered golden routines". The corpus test
(test_hevy_note_lint_5428.py) proves the linter on hand-written A-grade notes; THIS test proves the producers write
them. It runs the REAL generator (lane B's lift notes, warm-ups and loads) over two offline renders — the 10-18 upper
re-draft (`test_warmup_sets_5049._redraft`) and the first v0.4 lower-heavy (`test_program_session_4064_4147._generate`)
— adds lane C's composed cardio block and a stretching block, places lane A's session block the way the draft paths do
(`session_block.place_on_first`), compiles through the one compiler with the WHY every compile site passes
(`session_block.why_note_for`), and lints the wire body.

ONE session block on exercise 1, on every path: the draft paths (the MCP draft the nightly predraft calls, and the chat's
draft_custom) place it on the IR; the cron and the restamp compile the stored IR, and `why_note_for` suppresses the
compiler's WHY when the block is already there; a routine drafted before #5428 gets the block from the WHY instead
(`routine_title.format_why_note`). Exactly once either way.

Still open for D2: the full five-role draft path through `_run_stage_2` with the recorded critic verdicts, and enforce
mode at the commit gate.
"""

from __future__ import annotations

from training import hevy_note_lint, routine_title, session_block
from training.cardio_note import apply_after_lines, compose
from training.hevy_compiler import to_create_body
from training.routine_ir import ExerciseBlock, RoutineSpec, Set


def _with_cardio(ir: RoutineSpec) -> RoutineSpec:
    """Lane C's composed easy ride (the real composer), a stretching block after it, and its After line."""
    ride, _ = compose(
        movement_key="cycling", minutes=30, target_date=ir.target_date, kind="easy", facts={"last_level": 11}, verdict={"verdict": "hold"}
    )
    ir.exercises.append(ExerciseBlock(movement_key="cycling", sets=[Set(type="normal", duration_seconds=1800)], notes=ride))
    ir.exercises.append(ExerciseBlock(movement_key="stretching", sets=[Set(type="normal", duration_seconds=900)], notes=""))
    apply_after_lines(ir.exercises)
    return ir


def _renders() -> dict[str, RoutineSpec]:
    from test_program_session_4064_4147 import _generate
    from test_warmup_sets_5049 import _redraft

    return {"10-18 upper volume re-draft": _redraft(), "09-25 v0.4 lower heavy": _generate("2026-09-25")[0]}


def _compile(ir: RoutineSpec) -> dict:
    why = session_block.why_note_for(ir, routine_title.format_why_note(ir))
    return to_create_body(ir, lambda k: "T-" + k, why_note=why)


def test_freshly_rendered_routines_lint_clean():
    offenders = {}
    for name, ir in _renders().items():
        _with_cardio(ir)
        session_block.place_on_first(ir)  # what `_action_draft` / `_action_draft_custom` do before the draft is stored
        body = _compile(ir)
        res = hevy_note_lint.lint_wire(body, ir)
        if res.problems:
            offenders[name] = res.lines()
        # the linter read every kind and PREVIOUS (lane B writes it); nothing was skipped silently
        assert not [n for n in res.not_checked if n.startswith(("kinds", "L4 PREVIOUS"))], (name, res.not_checked)
        assert [e.kind for e in hevy_note_lint.from_wire(body, ir).exercises][-2:] == ["cardio", "mobility"]
    assert offenders == {}, offenders


def _block_count(body: dict) -> int:
    first = body["routine"]["exercises"][0]["notes"]
    return first.count(session_block.LOW_ENERGY_LINE)


def test_exercise_1_carries_the_session_block_exactly_once_on_every_path():
    ir = _renders()["10-18 upper volume re-draft"]
    legacy = _compile(ir)  # a routine drafted before #5428 (no block on the IR): the restamp/cron WHY carries it
    assert _block_count(legacy) == 1 and legacy["routine"]["exercises"][0]["notes"].startswith("Upper volume · RPE 8–9 on big lifts\n")
    session_block.place_on_first(ir)  # the draft path (predraft + MCP draft) and the chat's draft_custom
    session_block.place_on_first(ir)  # idempotent: a re-draft replaces, never stacks
    drafted = _compile(ir)  # the cron and the restamp compile the stored IR the same way
    assert _block_count(drafted) == 1, drafted["routine"]["exercises"][0]["notes"]
    # mutation control: a compile site that passed the raw WHY would put the block on twice
    doubled = to_create_body(ir, lambda k: "T-" + k, why_note=routine_title.format_why_note(ir))
    assert _block_count(doubled) == 2
    res = hevy_note_lint.lint_wire(doubled, ir)
    assert "L7" in res.rules() or "L3" in res.rules(), res.lines()


def test_routine_title_and_session_block_render_the_same_three_lines():
    for role in ("upper_heavy", "lower_heavy", "shoulders_arms", "upper_volume", "lower_volume"):
        ir = RoutineSpec(routine_id="r", target_date="2026-10-28", archetype="upper", inputs_snapshot={"calendar": {"session_role": role}})
        assert routine_title.format_why_note(ir) == session_block.render_for(ir), role
