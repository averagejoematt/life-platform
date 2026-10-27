"""tests/test_hevy_notes_golden_e2e_5428.py — #5428 D2: freshly RENDERED routines lint clean.

The acceptance box is "a style linter runs in the suite over freshly rendered golden routines". The corpus test
(test_hevy_note_lint_5428.py) proves the linter on hand-written A-grade notes; THIS test proves the producers write
them. It runs today's real producers — the session line (`routine_title.format_why_note`), the progression reason
(`routine_generator._progress_block`), the warm-up rows and cue (`warmup_sets.attach_warmups`), the cardio composer
(`cardio_note.compose`) — through the one compiler, then lints the wire body.

It is EXPECTED TO FAIL (strict xfail) until lanes A, B and C of #5428 land (the producers still write the old
grammar: "+5 lb to 190 lb: …", "Last: …", "Warm up: …, then the ramp sets.", "level 11 at 13.8 mph"). It is xfail,
not skipped, so it keeps running, and strict, so the merge that makes it pass reds until that lane removes the
marker. D2 then widens it to the real draft path for the five program roles plus one draft_custom session, through `_run_stage_2` with the recorded 10-26 critic verdicts, with
`inputs_snapshot["previous_loads"]` supplied, and flips HEVY_NOTE_LINT_MODE to enforce.
"""

from __future__ import annotations

import pytest
from training import hevy_note_lint, warmup_sets
from training.cardio_note import compose
from training.hevy_compiler import to_create_body
from training.routine_generator import _progress_block
from training.routine_ir import ExerciseBlock, RoutineSpec, Set
from training.routine_title import format_why_note

LB = 0.45359237
CATALOG = {
    "barbell_bench_press": {
        "hevy_template_id_hint": "79D0BB3A",
        "anchor_family": "bench",
        "equipment": "barbell",
        "title": "Bench Press (Barbell)",
    },
    "one_arm_db_row": {"hevy_template_id_hint": "F1E57334", "anchor_family": "row", "equipment": "dumbbell", "title": "Dumbbell Row"},
    "cycling": {"hevy_template_id_hint": "D8F7F851", "equipment": "machine", "primary_muscle": "cardio", "title": "Cycling"},
}


def _sess(date: str, kg: float, reps: int, rpe: float, n: int = 2) -> dict:
    return {"date": date, "sets": [{"weight_kg": kg, "reps": reps, "rpe": rpe} for _ in range(n)]}


def _working(kg: float, lo: int, hi: int, n: int = 3) -> list[Set]:
    return [Set(type="normal", weight_kg=kg, reps=lo, rep_range_start=lo, rep_range_end=hi) for _ in range(n)]


def _rendered_upper_heavy() -> tuple[RoutineSpec, str]:
    bench_kg = 185 * LB
    bench = ExerciseBlock(movement_key="barbell_bench_press", sets=_working(bench_kg, 6, 10), rest_seconds=180)
    hist = {"79D0BB3A": [_sess("2026-10-16", bench_kg, 10, 8), _sess("2026-10-14", bench_kg, 10, 8)]}
    _progress_block(bench, {"movements": CATALOG}, hist, {}, None, [])
    row = ExerciseBlock(movement_key="one_arm_db_row", sets=_working(90 * LB, 8, 12), rest_seconds=120)
    ride, _ = compose(
        movement_key="cycling", minutes=30, target_date="2026-10-28", kind="easy", facts={"last_level": 11}, verdict={"verdict": "hold"}
    )
    ir = RoutineSpec(
        routine_id="e2e-upper-heavy",
        target_date="2026-10-28",
        archetype="upper",
        source_action="draft",
        inputs_snapshot={
            "calendar": {"session_role": "upper_heavy"},
            hevy_note_lint.PREVIOUS_LOADS_KEY: {"barbell_bench_press": 185, "one_arm_db_row": 90},
        },
        exercises=[bench, row, ExerciseBlock(movement_key="cycling", sets=[Set(type="normal", duration_seconds=1800)], notes=ride)],
    )
    warmup_sets.attach_warmups(ir.exercises, CATALOG)
    return ir, format_why_note(ir)


@pytest.mark.xfail(
    reason="#5428: the producers still write the old note grammar until lanes A/B/C land; the lane that makes it pass removes this marker",
    strict=True,
)
def test_a_freshly_rendered_routine_lints_clean():
    ir, why = _rendered_upper_heavy()
    body = to_create_body(ir, lambda k: CATALOG.get(k, {}).get("hevy_template_id_hint", "X"), why_note=why)
    res = hevy_note_lint.lint_wire(body, ir, catalog=CATALOG)
    assert res.problems == [], res.lines()


def test_the_e2e_fixture_reaches_the_linter():
    """The xfail above must fail for the RIGHT reason: the fixture compiles, the linter runs on it with every kind
    resolved and PREVIOUS supplied, and the session block — routine_title's, D1's — is already clean."""
    ir, why = _rendered_upper_heavy()
    body = to_create_body(ir, lambda k: CATALOG.get(k, {}).get("hevy_template_id_hint", "X"), why_note=why)
    routine = hevy_note_lint.from_wire(body, ir, catalog=CATALOG)
    assert [e.kind for e in routine.exercises] == ["barbell", "dumbbell", "cardio"] and routine.previous_supplied
    res = hevy_note_lint.lint_routine(routine)
    assert not any(p.where in ("session line", "session block") for p in res.problems), res.lines()
    assert not any(p.rule == "L12" for p in res.problems), res.lines()
