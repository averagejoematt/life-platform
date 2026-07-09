"""tests/test_hevy_compiler.py — IR <-> Hevy wire format."""

from __future__ import annotations

import pytest
from hevy_compiler import (
    HEVY_SET_TYPES,
    MovementUnmappable,
    from_hevy_response,
    normalize_set_type,
    render_branches_note,
    sanitize_note,
    to_create_body,
    to_update_body,
)
from routine_ir import ExerciseBlock, RoutineBranch, RoutineSpec, Set


def _ir() -> RoutineSpec:
    return RoutineSpec(
        routine_id="r-1",
        target_date="2026-06-01",
        archetype="upper",
        title="Upper — 2026-06-01",
        notes="MEV starter.",
        hevy_folder_id=42,
        exercises=[
            ExerciseBlock(
                movement_key="db_bench_press_flat",
                sets=[
                    Set(type="normal", weight_kg=22.5, reps=10, rep_range_start=8, rep_range_end=12),
                    Set(type="normal", weight_kg=22.5, reps=10),
                ],
                rest_seconds=120,
            ),
        ],
    )


def _resolver_fn(key: str) -> str:
    return {"db_bench_press_flat": "55E6546B"}.get(key)


def test_create_body_includes_folder_id_and_template():
    body = to_create_body(_ir(), _resolver_fn)
    assert body["routine"]["folder_id"] == 42
    assert body["routine"]["exercises"][0]["exercise_template_id"] == "55E6546B"
    sets = body["routine"]["exercises"][0]["sets"]
    assert sets[0]["weight_kg"] == 22.5
    assert sets[0]["rep_range"] == {"start": 8, "end": 12}


def test_update_body_omits_folder_id():
    body = to_update_body(_ir(), _resolver_fn)
    assert "folder_id" not in body["routine"]


def test_unmappable_movement_raises():
    ir = _ir()
    ir.exercises[0].movement_key = "made_up_key"
    with pytest.raises(MovementUnmappable):
        to_create_body(ir, _resolver_fn)


def test_from_hevy_response_extracts_diff_keys():
    raw = {
        "routine": {
            "id": "abc12345",
            "title": "Upper",
            "folder_id": 42,
            "notes": "",
            "updated_at": "2026-06-01T18:00:00Z",
            "created_at": "2026-06-01T17:55:00Z",
            "exercises": [{"exercise_template_id": "55E6546B", "sets": [{}, {}]}],
        }
    }
    parsed = from_hevy_response(raw)
    assert parsed["hevy_routine_id"] == "abc12345"
    assert parsed["updated_at"] == "2026-06-01T18:00:00Z"
    assert parsed["exercises"][0]["set_count"] == 2


def test_title_context_overrides_default_title():
    """ADR-067: when a title_context is supplied, the compiler uses format_title."""
    ctx = {"phase": "Foundation", "type_count_in_phase": 3, "all_time_count": 47}
    body = to_create_body(_ir(), _resolver_fn, title_context=ctx)
    assert body["routine"]["title"] == "Foundation - Upper - 3 - 47"


def test_why_note_overrides_default_notes():
    """ADR-067: WHY-note projected into Hevy notes; IR notes ignored."""
    ir = _ir()
    ir.notes = "multi\nline\nrationale\nthat should not reach Hevy"
    body = to_create_body(ir, _resolver_fn, why_note="Readiness green. Programmed.")
    assert body["routine"]["notes"] == "Readiness green. Programmed."


def test_update_body_also_takes_title_context():
    ctx = {"phase": "Build", "type_count_in_phase": 2, "all_time_count": 99}
    body = to_update_body(_ir(), _resolver_fn, title_context=ctx, why_note="x")
    assert body["routine"]["title"] == "Build - Upper - 2 - 99"
    assert body["routine"]["notes"] == "x"
    assert "folder_id" not in body["routine"]


def test_drop_set_type_maps_to_dropset_on_wire():
    """A2: 'drop' is not a Hevy enum value (it 400'd 2026-06-21) — normalize to 'dropset'."""
    ir = _ir()
    ir.exercises[0].sets[0].type = "drop"
    body = to_create_body(ir, _resolver_fn)
    assert body["routine"]["exercises"][0]["sets"][0]["type"] == "dropset"


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("drop", "dropset"),
        ("Drop-Set", "dropset"),
        ("warm", "warmup"),
        ("WARMUP", "warmup"),
        ("fail", "failure"),
        ("normal", "normal"),
        (None, "normal"),
        ("", "normal"),
        ("nonsense", None),
    ],
)
def test_normalize_set_type(raw, expected):
    assert normalize_set_type(raw) == expected


def test_unmappable_set_type_coerces_to_normal_on_wire():
    """Defense in depth: even if the validator is skipped, an unknown type can't 400."""
    ir = _ir()
    ir.exercises[0].sets[0].type = "nonsense"
    body = to_create_body(ir, _resolver_fn)
    assert body["routine"]["exercises"][0]["sets"][0]["type"] == "normal"


def test_hevy_set_types_constant():
    assert HEVY_SET_TYPES == ("normal", "warmup", "failure", "dropset")


def test_sanitize_note_strips_control_chars_preserves_emoji():
    """A4: control chars (the JSON-breakers) are stripped; emoji are preserved."""
    assert sanitize_note("good\x00\x07note") == "goodnote"
    assert sanitize_note("line1\nline2\ttab") == "line1\nline2\ttab"
    assert sanitize_note("heavy 💪 day") == "heavy 💪 day"
    assert sanitize_note(None) == ""


def test_sanitize_note_applied_to_exercise_and_routine_notes():
    ir = _ir()
    ir.exercises[0].notes = "felt\x07strong"
    body = to_create_body(ir, _resolver_fn, why_note="why\x00note")
    assert body["routine"]["exercises"][0]["notes"] == "feltstrong"
    assert body["routine"]["notes"] == "whynote"


def _branched_ir() -> RoutineSpec:
    ir = _ir()
    ir.notes = "Upper day."
    ir.branches = [
        RoutineBranch(label="easier", cue="min dose", recommended=False, order=1),
        RoutineBranch(label="as-written", cue="the plan", recommended=True, order=0),
    ]
    return ir


def test_no_branches_notes_unchanged_backward_compat():
    """#417 criterion 5: a routine with no branches pushes EXACTLY as before."""
    ir = _ir()
    ir.notes = "MEV starter."
    assert ir.branches == []
    body = to_create_body(ir, _resolver_fn)
    assert body["routine"]["notes"] == "MEV starter."
    body_why = to_create_body(ir, _resolver_fn, why_note="Readiness green.")
    assert body_why["routine"]["notes"] == "Readiness green."


def test_branches_render_into_notes():
    """#417: the compiler renders branches; every branch is visible, recommended starred."""
    body = to_create_body(_branched_ir(), _resolver_fn, why_note="Readiness yellow.")
    notes = body["routine"]["notes"]
    assert notes.startswith("Readiness yellow.")
    assert "CHOOSE YOUR BRANCH" in notes
    assert "AS-WRITTEN" in notes and "EASIER" in notes  # every branch visible
    assert "★ AS-WRITTEN (recommended)" in notes  # highlighted, not removed
    # order respected: recommended (order 0) appears before easier (order 1)
    assert notes.index("AS-WRITTEN") < notes.index("EASIER")


def test_branches_render_in_update_body_too():
    body = to_update_body(_branched_ir(), _resolver_fn, why_note="x")
    assert "CHOOSE YOUR BRANCH" in body["routine"]["notes"]
    assert "folder_id" not in body["routine"]


def test_render_branches_note_empty_when_no_branches():
    assert render_branches_note([]) == ""


def test_branch_menu_reflects_reordering():
    """Re-stamp re-orders by `order`; the rendered menu must follow (recommended first)."""
    branches = [
        RoutineBranch(label="as-written", recommended=False, order=1),
        RoutineBranch(label="easier", recommended=True, order=0),
    ]
    note = render_branches_note(branches)
    assert note.index("EASIER") < note.index("AS-WRITTEN")
    assert "★ EASIER (recommended)" in note


def _branched_ir_with_content() -> RoutineSpec:
    """A branched IR where each branch carries its OWN distinct exercise content,
    like a routine emitted by routine_generator.emit_branch_model."""
    ir = _ir()
    ir.notes = "Upper day."
    as_written_ex = ExerciseBlock(
        movement_key="db_bench_press_flat",
        sets=[Set(type="normal", weight_kg=22.5, reps=10)],
        rest_seconds=120,
    )
    easier_ex = ExerciseBlock(
        movement_key="machine_chest_press",
        sets=[Set(type="normal", weight_kg=15.0, reps=12)],
        rest_seconds=90,
    )
    ir.exercises = [as_written_ex]
    ir.branches = [
        RoutineBranch(label="easier", cue="min dose", recommended=False, order=1, exercises=[easier_ex]),
        RoutineBranch(label="as-written", cue="the plan", recommended=True, order=0, exercises=[as_written_ex]),
    ]
    return ir


def _branch_resolver_fn(key: str) -> str:
    return {"db_bench_press_flat": "55E6546B", "machine_chest_press": "MACH001"}.get(key)


def test_recommended_branch_exercises_pushed_as_routine_content():
    """#417 2b: the RECOMMENDED branch's own exercises become the routine's
    pushed exercise list — not the (possibly stale) base ir.exercises."""
    ir = _branched_ir_with_content()
    body = to_create_body(ir, _branch_resolver_fn)
    pushed = body["routine"]["exercises"]
    assert len(pushed) == 1
    assert pushed[0]["exercise_template_id"] == "55E6546B"  # as-written (recommended)


def test_restamped_recommendation_flips_pushed_exercises():
    """When re-stamp flips `recommended` to a different branch, the NEXT
    to_update_body call pushes THAT branch's exercises — proving the overnight
    re-stamp changes what the reader's Hevy app shows, not just a note."""
    ir = _branched_ir_with_content()
    # Simulate what hevy_restamp_lambda.restamp_branches does: flip recommended.
    for b in ir.branches:
        b.recommended = b.label == "easier"
    body = to_update_body(ir, _branch_resolver_fn, why_note="Readiness red.")
    pushed = body["routine"]["exercises"]
    assert len(pushed) == 1
    assert pushed[0]["exercise_template_id"] == "MACH001"  # easier (now recommended)
    # The menu still shows BOTH branches — self-selection preserved.
    notes = body["routine"]["notes"]
    assert "AS-WRITTEN" in notes and "EASIER" in notes


def test_branch_with_no_own_exercises_falls_back_to_base_exercises():
    """A branch-light placeholder (recommended, but exercises=[]) must not
    blank out the pushed routine — falls back to ir.exercises."""
    ir = _branched_ir()  # branches carry no exercises of their own
    body = to_create_body(ir, _resolver_fn)
    pushed = body["routine"]["exercises"]
    assert len(pushed) == 1
    assert pushed[0]["exercise_template_id"] == "55E6546B"  # ir.exercises, unchanged


def test_branchless_routine_pushes_ir_exercises_byte_identical():
    """#417 criterion 5, extended to 2b: a routine with NO branches pushes
    ir.exercises exactly as before — the branch-aware exercise selection must
    be a strict no-op when there is nothing to choose between."""
    ir = _ir()
    assert ir.branches == []
    branchless_body = to_create_body(ir, _resolver_fn)

    # A branch-carrying IR sharing the identical base exercises, where the
    # recommended branch has no exercises of its own, must compile to the
    # SAME exercises payload as the branchless IR.
    ir_with_empty_branches = _ir()
    ir_with_empty_branches.branches = [RoutineBranch(label="as-written", recommended=True, order=0)]
    branched_body = to_create_body(ir_with_empty_branches, _resolver_fn)

    assert branchless_body["routine"]["exercises"] == branched_body["routine"]["exercises"]


def test_round_trip_response_to_diff():
    body = to_create_body(_ir(), _resolver_fn)
    simulated_response = {
        "routine": {
            "id": "abc12345",
            "title": body["routine"]["title"],
            "folder_id": body["routine"]["folder_id"],
            "notes": body["routine"]["notes"],
            "updated_at": "2026-06-01T18:00:00Z",
            "created_at": "2026-06-01T17:55:00Z",
            "exercises": body["routine"]["exercises"],
        }
    }
    parsed = from_hevy_response(simulated_response)
    assert parsed["hevy_routine_id"] == "abc12345"
    assert parsed["exercises"][0]["exercise_template_id"] == "55E6546B"
