"""tests/test_routine_title.py — ADR-067 title + phase + WHY-note.

Verifies:
- N resets at phase_start boundary (per-phase, per-type)
- Y reflects performed Hevy workout history (not planned)
- Re-entry variant uses the gentle title; no counters surfaced
- WHY-note picks the right line per variant + rationale
- Title length capped at MAX_TITLE_CHARS
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from training import routine_title as rt
from training.routine_ir import ExerciseBlock, RoutineSpec, Set

_REAL_READ_STATE = rt.read_phase_state_row  # the autouse fixture below stubs it; two tests drive the real read


def _ir(archetype="upper", variant="ideal", target_date="2026-06-15", rationale=None) -> RoutineSpec:
    return RoutineSpec(
        routine_id="r-1",
        target_date=target_date,
        archetype=archetype,
        variant=variant,
        exercises=[ExerciseBlock(movement_key="db_bench_press_flat", sets=[Set(reps=10)])],
        rationale=rationale or ["archetype=upper; autoreg=0.85 (recovery=green, acwr=safe)"],
    )


@pytest.fixture(autouse=True)
def _reset():
    rt._reset_for_tests()
    # #5576: no PHASE#STATE row unless a test plants one — the file fallback, and no live DDB read
    with patch.object(rt, "read_phase_state_row", return_value=None):
        yield
    rt._reset_for_tests()


def test_format_title_renders_phase_type_n_y():
    ctx = {"phase": "Foundation", "type_count_in_phase": 3, "all_time_count": 47}
    title = rt.format_title(_ir(archetype="upper"), ctx)
    assert title == "Foundation - Upper - 3 - 47"


def test_format_title_truncates_at_limit():
    long_phase = "A" * 80
    ctx = {"phase": long_phase, "type_count_in_phase": 1, "all_time_count": 1}
    title = rt.format_title(_ir(), ctx)
    assert len(title) <= rt.MAX_TITLE_CHARS


def test_format_title_re_entry_is_gentle_no_counters():
    ctx = {"phase": "Foundation", "type_count_in_phase": 5, "all_time_count": 99}
    title = rt.format_title(_ir(variant="re_entry", archetype="lower"), ctx)
    assert title.startswith("Welcome back")
    assert "5" not in title and "99" not in title and "Foundation" not in title
    assert "Lower" in title


def test_why_note_re_entry_is_kind():
    note = rt.format_why_note(_ir(variant="re_entry"))
    assert "easing" in note.lower() or "gently" in note.lower()
    assert "missed" not in note.lower() and "skip" not in note.lower()


def test_why_note_picks_red_recovery():
    ir = _ir(rationale=["archetype=upper; autoreg=0.6 (recovery=red, acwr=safe)"])
    note = rt.format_why_note(ir)
    assert "red" in note.lower() or "deload" in note.lower()


def test_why_note_picks_portfolio_guard():
    ir = _ir(
        rationale=[
            "archetype=upper; autoreg=0.85 (recovery=yellow, acwr=safe)",
            "z2 7d=0 < floor 90; portfolio guard active",
        ]
    )
    note = rt.format_why_note(ir)
    assert "zone 2" in note.lower() or "aerobic" in note.lower()


def test_why_note_floor_variant_is_explicit():
    note = rt.format_why_note(_ir(variant="floor"))
    assert "floor" in note.lower() or "minimum" in note.lower()


# ── build_title_context: performed-derived N (per-phase) + Y (per reset epoch) ──
# 2026-06-16 work order: supersedes the 2026-05-31 amendment. N counts PERFORMED
# workouts of the type since current_started; Y counts distinct performed since
# EXPERIMENT_START_DATE. Both honest (skipped/planned never inflate).
#
# #3671 (2026-09-07): the Y anchor is DERIVED from constants, not read from the
# phase config. `reset` is kept as a parameter only so a caller can plant a stale
# `reset_epoch_date` and prove it is ignored — see the negative control below.


def _phase_state(current="Foundation", started="2026-06-16", reset=None):
    state = {
        "phases": ["Foundation", "Build", "Forge", "Sustain"],
        "current": current,
        "current_started": started,
    }
    if reset is not None:
        state["reset_epoch_date"] = reset
    return state


def test_build_context_n_and_y_from_performed():
    """Seed scenario: one performed 'upper' on 2026-06-16; index has a matching
    pushed routine. Next 'upper' → N=2, Y=2."""
    performed = [{"date": "2026-06-16", "workout_uid": "hevy:a"}]
    index = [{"archetype": "upper", "target_date": "2026-06-16", "variant": "ideal"}]
    with (
        patch.object(rt, "load_phase_state", return_value=_phase_state()),
        patch.object(rt, "_query_performed", return_value=performed),
        patch.object(rt, "_load_routine_index", return_value=index),
    ):
        ctx = rt.build_title_context(_ir(archetype="upper", target_date="2026-06-17"))
    assert ctx["type_count_in_phase"] == 2
    assert ctx["all_time_count"] == 2
    assert ctx["phase"] == "Foundation"
    assert ctx["phase_started"] == "2026-06-16"
    # Derived, not configured (#3671) — compare against the constant, never a literal,
    # or this assertion becomes the twelfth thing a reset has to remember to edit.
    assert ctx["reset_epoch"] == rt.EXPERIMENT_START_DATE


def test_build_context_first_of_type_is_n1_but_y_tracks_total():
    """A 'lower' with no prior performed lowers → N=1, but Y still counts all
    performed workouts (here one upper) → Y=2."""
    performed = [{"date": "2026-06-16", "workout_uid": "hevy:a"}]
    index = [{"archetype": "upper", "target_date": "2026-06-16", "variant": "ideal"}]
    with (
        patch.object(rt, "load_phase_state", return_value=_phase_state()),
        patch.object(rt, "_query_performed", return_value=performed),
        patch.object(rt, "_load_routine_index", return_value=index),
    ):
        ctx = rt.build_title_context(_ir(archetype="lower", target_date="2026-06-18"))
    assert ctx["type_count_in_phase"] == 1
    assert ctx["all_time_count"] == 2


def test_build_context_n_resets_on_phase_advance():
    """Advancing the phase (bump current_started) windows N to the new phase, so
    pre-advance performed workouts no longer count toward N — N resets to 1."""
    # phase started 2026-08-01; the only performed work is BEFORE that window, so
    # _query_performed(phase_started) returns nothing → N=1. Y uses reset epoch.
    with (
        patch.object(rt, "load_phase_state", return_value=_phase_state(current="Build", started="2026-08-01")),
        patch.object(
            rt,
            "_query_performed",
            side_effect=lambda start: [] if start == "2026-08-01" else [{"date": "2026-06-16", "workout_uid": "hevy:a"}],
        ),
        patch.object(rt, "_load_routine_index", return_value=[]),
    ):
        ctx = rt.build_title_context(_ir(archetype="upper", target_date="2026-08-02"))
    assert ctx["type_count_in_phase"] == 1  # N reset by the new phase window
    assert ctx["all_time_count"] == 2  # Y still counts the pre-advance workout


# #5576: the phase comes from the weekly evaluator's PHASE#STATE row (#5575), not the hand-edited file. A fixture STATE row
# exactly as `phase_evaluator.state_row` writes it after an applied transition: stage/title flipped, `since` = the
# TRANSITION's effective_on (the block start the stage machine applied it at).
_PERFORMED_ACROSS_THE_FLIP = [
    {"date": "2026-10-20", "workout_uid": "hevy:a", "archetype": "upper"},
    {"date": "2026-11-03", "workout_uid": "hevy:b", "archetype": "upper"},
    {"date": "2026-11-17", "workout_uid": "hevy:c", "archetype": "lower"},
]


def _performed_since(start):
    return [w for w in _PERFORMED_ACROSS_THE_FLIP if w["date"] >= start]


def _state_row(stage, title, since):
    from training import phase_evaluator as pe

    return {"pk": pe.pk(), "sk": pe.SK_STATE, "stage": stage, "title": title, "since": since, "origin": "evaluator", "pending": None}


def test_a_state_row_flipping_the_phase_changes_the_title_prefix_and_resets_n():
    """Mutation: keep reading `current`/`current_started` from training_phases.json (the prefix stays Foundation and N
    keeps counting the two pre-flip uppers), or anchor N on anything but the STATE row's `since`."""
    file_state = _phase_state(current="Foundation", started="2026-09-06")
    ir = _ir(archetype="upper", target_date="2026-11-18")
    with (
        patch.object(rt, "load_phase_state", return_value=file_state),
        patch.object(rt, "_query_performed", side_effect=_performed_since),
        patch.object(rt, "_load_routine_index", return_value=[]),
    ):
        with patch.object(rt, "read_phase_state_row", return_value=_state_row("foundation", "Foundation", "2026-09-06")):
            before = rt.build_title_context(ir)
        with patch.object(rt, "read_phase_state_row", return_value=_state_row("build", "Build", "2026-11-16")):
            after = rt.build_title_context(ir)
    assert rt.format_title(ir, before).startswith("Foundation - Upper - 3 - ")
    assert before["phase_source"] == rt.PHASE_SOURCE_STATE
    assert rt.format_title(ir, after).startswith("Build - Upper - 1 - ")  # the new prefix, N reset on the transition date
    assert after["phase_started"] == "2026-11-16" and after["phase_source"] == rt.PHASE_SOURCE_STATE
    # Y is untouched by the flip: still derived from EXPERIMENT_START_DATE (#3671), never from the STATE row
    assert after["reset_epoch"] == rt.EXPERIMENT_START_DATE
    assert after["all_time_count"] == before["all_time_count"]


def test_no_state_row_falls_back_to_the_file():
    """Mutation: drop the fallback (the title breaks until the evaluator's first Monday run), or let it ignore the file."""
    with (
        patch.object(rt, "load_phase_state", return_value=_phase_state(current="Foundation", started="2026-09-06")),
        patch.object(rt, "_query_performed", side_effect=_performed_since),
        patch.object(rt, "_load_routine_index", return_value=[]),
    ):
        ctx = rt.build_title_context(_ir(archetype="upper", target_date="2026-11-18"))
    assert (ctx["phase"], ctx["phase_started"], ctx["phase_source"]) == ("Foundation", "2026-09-06", rt.PHASE_SOURCE_FILE)
    assert ctx["type_count_in_phase"] == 3


def test_an_unreadable_state_row_falls_back_to_the_file():
    """Mutation: let the STATE read's exception escape (a DDB blip would stop every routine push)."""

    class _Boom:
        def get_item(self, **kw):
            raise RuntimeError("ddb down")

    with (
        patch.object(rt, "read_phase_state_row", _REAL_READ_STATE),
        patch.object(rt, "_table", return_value=_Boom()),
        patch.object(rt, "load_phase_state", return_value=_phase_state(current="Foundation", started="2026-09-06")),
    ):
        assert rt.read_phase_state_row() is None
        assert rt.resolve_title_phase() == ("Foundation", "2026-09-06", rt.PHASE_SOURCE_FILE)


def test_the_state_read_names_the_evaluator_key():
    """Mutation: read any key but the evaluator's own PHASE#STATE row in the training_constraints partition."""
    from training import phase_evaluator as pe

    seen = {}

    class _Table:
        def get_item(self, Key=None, **kw):
            seen.update(Key)
            return {"Item": _state_row("build", "Build", "2026-11-16")}

    with patch.object(rt, "read_phase_state_row", _REAL_READ_STATE), patch.object(rt, "_table", return_value=_Table()):
        assert rt.resolve_title_phase() == ("Build", "2026-11-16", rt.PHASE_SOURCE_STATE)
    assert seen == {"pk": "USER#matthew#SOURCE#training_constraints", "sk": pe.SK_STATE}
