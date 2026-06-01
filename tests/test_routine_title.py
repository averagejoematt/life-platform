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


def _ir(archetype="upper", variant="ideal", target_date="2026-06-15",
        rationale=None) -> RoutineSpec:
    return RoutineSpec(
        routine_id="r-1",
        target_date=target_date,
        archetype=archetype,
        variant=variant,
        exercises=[ExerciseBlock(movement_key="db_bench_press_flat",
                                 sets=[Set(reps=10)])],
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
    ir = _ir(rationale=[
        "archetype=upper; autoreg=0.85 (recovery=yellow, acwr=safe)",
        "z2 7d=0 < floor 90; portfolio guard active",
    ])
    note = rt.format_why_note(ir)
    assert "zone 2" in note.lower() or "aerobic" in note.lower()


def test_why_note_floor_variant_is_explicit():
    note = rt.format_why_note(_ir(variant="floor"))
    assert "floor" in note.lower() or "minimum" in note.lower()


# ── build_title_context: all-time-per-type since EXPERIMENT_START_DATE ──

def _phase_state(current="Foundation"):
    return {
        "phases": ["Foundation", "Build", "Forge", "Sustain"],
        "current": current,
        "current_started": "2026-06-01",
    }


def test_build_context_y_counts_performed_workouts_since_experiment_start():
    """Y = workouts performed since EXPERIMENT_START_DATE + 1."""
    with patch.object(rt, "load_phase_state", return_value=_phase_state()), \
         patch.object(rt, "count_performed_workouts_since", return_value=46), \
         patch.object(rt, "count_experiment_archetype_routines", return_value=2):
        ctx = rt.build_title_context(_ir(target_date="2026-06-15"))
    assert ctx["all_time_count"] == 47
    assert ctx["type_count_in_phase"] == 3
    assert ctx["phase"] == "Foundation"
    assert ctx["experiment_started"] == rt.EXPERIMENT_START_DATE


def test_build_context_first_routine_n_is_1():
    """No prior routines of this type since experiment start → N=1."""
    with patch.object(rt, "load_phase_state", return_value=_phase_state(current="Build")), \
         patch.object(rt, "count_performed_workouts_since", return_value=99), \
         patch.object(rt, "count_experiment_archetype_routines", return_value=0):
        ctx = rt.build_title_context(_ir(target_date="2026-09-02"))
    assert ctx["type_count_in_phase"] == 1
    assert ctx["all_time_count"] == 100
    assert ctx["phase"] == "Build"


def test_count_experiment_archetype_filters_archetype_and_variant():
    """Index Query result filtered by archetype + skipping floor/re_entry variants."""
    fake_items = [
        {"routine_id": "r1", "target_date": "2026-06-02", "archetype": "upper", "variant": "ideal"},
        {"routine_id": "r2", "target_date": "2026-06-04", "archetype": "lower", "variant": "ideal"},
        {"routine_id": "r3", "target_date": "2026-06-09", "archetype": "upper", "variant": "ideal"},
        {"routine_id": "r4", "target_date": "2026-06-09", "archetype": "upper", "variant": "floor"},
        {"routine_id": "r5", "target_date": "2026-06-15", "archetype": "upper", "variant": "ideal"},
    ]

    class _FakeTable:
        def query(self, **_kwargs):
            return {"Items": fake_items}

    with patch.object(rt, "_table", return_value=_FakeTable()):
        # target_date_exclusive=2026-06-15 → r5 is the one being committed, excluded
        n = rt.count_experiment_archetype_routines("upper", "2026-06-15")
    # r1 + r3 = 2; r4 dropped (floor); r2 dropped (lower); r5 excluded (current)
    assert n == 2


def test_n_does_not_reset_on_phase_change():
    """ADR-067 amendment: N counts from EXPERIMENT_START_DATE regardless of phase."""
    fake_items = [
        {"routine_id": "old1", "target_date": "2026-06-02", "archetype": "upper", "variant": "ideal"},
        {"routine_id": "old2", "target_date": "2026-08-05", "archetype": "upper", "variant": "ideal"},
        {"routine_id": "new1", "target_date": "2026-09-02", "archetype": "upper", "variant": "ideal"},
    ]

    class _FakeTable:
        def query(self, **_kwargs):
            return {"Items": fake_items}

    with patch.object(rt, "_table", return_value=_FakeTable()):
        n = rt.count_experiment_archetype_routines("upper", "2026-09-09")
    # All 3 prior routines count, even though we'd be in a later phase.
    assert n == 3


def test_count_performed_workouts_since_paginates():
    """COUNT-only Query with sk>=DATE#... that paginates via LastEvaluatedKey."""
    pages = [
        {"Count": 100, "LastEvaluatedKey": {"pk": "USER#matthew#SOURCE#hevy", "sk": "DATE#2026-08"}},
        {"Count": 23},
    ]
    call_count = {"n": 0}

    class _FakeTable:
        def query(self, **kwargs):
            i = call_count["n"]
            call_count["n"] = i + 1
            return pages[i]

    with patch.object(rt, "_table", return_value=_FakeTable()):
        total = rt.count_performed_workouts_since("2026-06-01")
    assert total == 123
    assert call_count["n"] == 2
