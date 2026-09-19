"""#3670 box 4 — the title counters cannot reach behind EXPERIMENT_START_DATE.

The measured defect, cycle 17 day 1: `Foundation - Push - 3 - 11`. Both numbers
were wrong and for the same reason — each opened its window on a date held in
`config/training_phases.json`, a file `deploy/restart_pipeline.py` does not own
and the Lambda bundle does not ship (the runtime reads the S3 copy). #3671
deleted Y's copy and derived it from the constant. N was left reading
`current_started`, on the reading that a phase may deliberately span cycles.

That reading is right about the phase and wrong about the counter, which is what
box 4 rules on: *the title counters* cannot reach behind genesis regardless of
what the config holds, "so a reset re-anchors them with no config edit". The
phase NAME still spans cycles untouched — `counter_anchor` floors the WINDOW
only, and a `current_started` on/after genesis is passed through unchanged (the
positive control below, which is what stops "floor it" from degenerating into
"ignore the config").

Scope note: this file is deliberately about the CODE. Re-anchoring the config
itself, and giving the reset pipeline ownership of it, is #3671's residual — the
point of the floor is that neither is needed for the counter to be honest.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import date, timedelta
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lambdas"))

from common.constants import EXPERIMENT_START_DATE  # noqa: E402
from training import routine_title as rt  # noqa: E402
from training.routine_ir import ExerciseBlock, RoutineSpec, Set  # noqa: E402

CONFIG = os.path.join(ROOT, "config", "training_phases.json")

# The exact value that shipped stuck for eleven resets (#3671's measurement).
STALE_ANCHOR = "2026-06-16"


def _day(offset: int) -> str:
    return (date.fromisoformat(EXPERIMENT_START_DATE) + timedelta(days=offset)).isoformat()


def _ir(archetype="push", target_date=None):
    return RoutineSpec(
        routine_id="r-floor",
        target_date=target_date or _day(1),
        archetype=archetype,
        variant="ideal",
        exercises=[ExerciseBlock(movement_key="db_bench_press_flat", sets=[Set(reps=10)])],
        rationale=["archetype=push; autoreg=0.85 (recovery=green, acwr=safe)"],
    )


def _state(started):
    return {"phases": ["Foundation", "Build"], "current": "Foundation", "current_started": started}


def _build(started, performed=None, index=None):
    """Run build_title_context against a planted config; return (ctx, windows)
    where `windows` is every start date the code actually queried on."""
    windows: list[str] = []
    rows = performed or []

    def _performed(start):
        windows.append(start)
        return [r for r in rows if r["date"] >= start]

    def _index(start):
        windows.append(start)
        return index or []

    with (
        patch.object(rt, "load_phase_state", return_value=_state(started)),
        patch.object(rt, "_query_performed", side_effect=_performed),
        patch.object(rt, "_load_routine_index", side_effect=_index),
    ):
        return rt.build_title_context(_ir()), windows


# ── the floor itself ──────────────────────────────────────────────────────────


def test_counter_anchor_floors_a_pre_genesis_date():
    assert rt.counter_anchor(STALE_ANCHOR) == EXPERIMENT_START_DATE


def test_counter_anchor_honours_an_anchor_on_or_after_genesis():
    """Positive control. A floor implemented as "always return the constant" would
    pass the test above and quietly delete the owner's hand-advanced phase window —
    N would stop resetting when a phase advances mid-cycle."""
    assert rt.counter_anchor(_day(0)) == _day(0)
    assert rt.counter_anchor(_day(21)) == _day(21)


def test_counter_anchor_treats_a_missing_anchor_as_genesis():
    assert rt.counter_anchor(None) == EXPERIMENT_START_DATE
    assert rt.counter_anchor("") == EXPERIMENT_START_DATE


# ── through build_title_context: what the code actually QUERIES ───────────────


def test_no_query_window_opens_before_genesis_with_a_stale_config():
    """The load-bearing assertion: not the returned number, the DATES QUERIED.
    A counter that returned the right total while still reading pre-genesis rows
    would be one join away from being wrong again."""
    ctx, windows = _build(STALE_ANCHOR)
    assert windows, "the fixture stopped exercising the query path — fix this test"
    assert all(w >= EXPERIMENT_START_DATE for w in windows), windows
    assert STALE_ANCHOR not in windows
    assert ctx["phase_started"] == EXPERIMENT_START_DATE


def test_a_pre_genesis_history_cannot_inflate_either_counter():
    """The issue's own repro: four pre-genesis sessions, a config left at the
    previous cycle's anchor, and a routine written on day 2. Pre-fix this rendered
    `- 3 - 11`-shaped inflation; the honest answer on day 2 of a fresh cycle is
    the first push and the first workout."""
    performed = [
        {"date": "2026-06-20", "workout_uid": "hevy:a"},
        {"date": "2026-07-04", "workout_uid": "hevy:b"},
        {"date": "2026-08-11", "workout_uid": "hevy:c"},
        {"date": "2026-08-30", "workout_uid": "hevy:d"},
    ]
    index = [{"archetype": "push", "target_date": r["date"], "variant": "ideal"} for r in performed]
    ctx, _ = _build(STALE_ANCHOR, performed, index)
    assert ctx["type_count_in_phase"] == 1
    assert ctx["all_time_count"] == 1
    assert rt.format_title(_ir(), ctx).endswith(" - 1 - 1")


def test_the_phase_name_still_spans_cycles():
    """What the floor must NOT do. The owner advances `current` by hand and a reset
    deliberately leaves it alone — only the window is floored."""
    ctx, _ = _build(STALE_ANCHOR)
    assert ctx["phase"] == "Foundation"


def test_a_post_genesis_phase_advance_still_windows_n():
    """Positive control through the real code path: the phase anchor is only
    floored, never replaced, so a mid-cycle advance still resets N while Y keeps
    counting from genesis."""
    performed = [
        {"date": _day(1), "workout_uid": "hevy:a"},
        {"date": _day(3), "workout_uid": "hevy:b"},
    ]
    index = [{"archetype": "push", "target_date": r["date"], "variant": "ideal"} for r in performed]
    ctx, windows = _build(_day(10), performed, index)
    assert _day(10) in windows, "the hand-advanced phase anchor must survive the floor"
    assert ctx["type_count_in_phase"] == 1, "N windows to the new phase"
    assert ctx["all_time_count"] == 3, "Y still counts both pre-advance sessions since genesis"


# ── "regardless of what training_phases.json holds" ───────────────────────────


def test_the_repo_config_cannot_move_a_counter_behind_genesis():
    """Run the floor over the config as committed, plus the values a future reset
    could plausibly leave behind. This is the acceptance clause verbatim: the
    outcome may not depend on the file."""
    with open(CONFIG, encoding="utf-8") as fh:
        committed = json.load(fh).get("current_started")
    candidates = [committed, STALE_ANCHOR, "1999-01-01", "2026-01-01", _day(-1), None, ""]
    for candidate in candidates:
        assert rt.counter_anchor(candidate) >= EXPERIMENT_START_DATE, candidate


def test_the_committed_config_is_not_what_makes_this_pass():
    """Guard against the floor looking healthy only because someone re-anchored the
    config by hand (which is #3671's residual, not this fix). Plant the stale value
    and assert the code is unmoved — if this file ever passes only because
    `current_started` happens to equal genesis, this reds."""
    assert rt.counter_anchor(STALE_ANCHOR) != STALE_ANCHOR
    ctx, windows = _build(STALE_ANCHOR)
    assert all(w == EXPERIMENT_START_DATE for w in windows), windows
    assert ctx["phase_started"] == EXPERIMENT_START_DATE
