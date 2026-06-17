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
import routine_title as rt
from routine_ir import ExerciseBlock, RoutineSpec, Set


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
# reset_epoch_date. Both honest (skipped/planned never inflate).


def _phase_state(current="Foundation", started="2026-06-16", reset="2026-06-16"):
    return {
        "phases": ["Foundation", "Build", "Forge", "Sustain"],
        "current": current,
        "current_started": started,
        "reset_epoch_date": reset,
    }


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
    assert ctx["phase_started"] == "2026-06-16" and ctx["reset_epoch"] == "2026-06-16"


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
        patch.object(rt, "load_phase_state", return_value=_phase_state(current="Build", started="2026-08-01", reset="2026-06-16")),
        patch.object(rt, "_query_performed", side_effect=lambda start: [] if start == "2026-08-01" else [{"date": "2026-06-16", "workout_uid": "hevy:a"}]),
        patch.object(rt, "_load_routine_index", return_value=[]),
    ):
        ctx = rt.build_title_context(_ir(archetype="upper", target_date="2026-08-02"))
    assert ctx["type_count_in_phase"] == 1  # N reset by the new phase window
    assert ctx["all_time_count"] == 2       # Y still counts the pre-advance workout
