"""#3671 — the Hevy Y counter's anchor is DERIVED, and the second copy is gone.

The defect this pins, measured 2026-09-07: `config/training_phases.json` carried a
hand-maintained `reset_epoch_date` that `deploy/restart_pipeline.py` does not own —
ADR-077's phase taxonomy classifies DynamoDB partitions and has no jurisdiction over
config files. It sat at `2026-06-16` through ELEVEN resets while `EXPERIMENT_START_DATE`
moved to `2026-09-06`, so day 1 of a cycle rendered `Foundation - Push - 3 - 11` instead
of `- 1 - 1` and the owner could not read "first workout since genesis, or ninety-fifth?"
off a title.

Two things made it invisible rather than merely wrong, and both are guarded here:

1. `build_bundle.py` stages only `food_vocabulary.json`, `personas.json` and
   `config/coaches/*` — NOT `training_phases.json`. So `load_phase_state()` fell through
   to S3, and hand-editing the repo copy (as #3675 did) did not move the live counter.
2. Nothing failed. A stale anchor produces a plausible number, not an error.

The fix is a deletion, not a new writer: Y derives from `EXPERIMENT_START_DATE`, which
every reset regenerates and which ships in every bundle (#781). These tests fail if the
second copy is reintroduced, or if the derivation is routed back through config.
"""

from __future__ import annotations

import json
import os
import sys
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lambdas"))

from common.constants import EXPERIMENT_START_DATE  # noqa: E402
from training import routine_title as rt  # noqa: E402
from training.routine_ir import ExerciseBlock, RoutineSpec, Set  # noqa: E402

CONFIG = os.path.join(ROOT, "config", "training_phases.json")


def _ir(archetype="upper", target_date="2026-09-07"):
    return RoutineSpec(
        routine_id="r-1",
        target_date=target_date,
        archetype=archetype,
        variant="ideal",
        exercises=[ExerciseBlock(movement_key="db_bench_press_flat", sets=[Set(reps=10)])],
        rationale=["archetype=upper; autoreg=0.85 (recovery=green, acwr=safe)"],
    )


def _state(**over):
    state = {
        "phases": ["Foundation", "Build", "Forge", "Sustain"],
        "current": "Foundation",
        "current_started": "2026-06-16",
    }
    state.update(over)
    return state


def _context(state, performed, index):
    with (
        patch.object(rt, "load_phase_state", return_value=state),
        patch.object(rt, "_query_performed", return_value=performed),
        patch.object(rt, "_load_routine_index", return_value=index),
    ):
        return rt.build_title_context(_ir())


# ── the config no longer carries the second copy ──────────────────────────────


def test_training_phases_config_has_no_reset_epoch_date():
    """The whole point of #3671: one anchor, in constants, not two.

    A reintroduced `reset_epoch_date` is not a harmless duplicate — it is a date
    the reset pipeline does not own, in a file the Lambda bundle does not ship,
    read from an S3 copy nobody diffs against the repo.
    """
    with open(CONFIG, encoding="utf-8") as fh:
        cfg = json.load(fh)
    assert "reset_epoch_date" not in cfg, (
        "config/training_phases.json reintroduced `reset_epoch_date`. The Y anchor is "
        "derived from EXPERIMENT_START_DATE (#3671) — deleting it was the fix. If a "
        "config-held anchor is genuinely needed again, give restart_pipeline.py "
        "ownership of this file first, or it will drift through the next eleven resets."
    )


def test_training_phases_config_still_carries_the_phase_anchors():
    """Negative control for the test above: it must reject the second copy WITHOUT
    licensing the deletion of `current_started`, which the owner advances by hand
    and which a reset deliberately does NOT touch (a phase may span cycles)."""
    with open(CONFIG, encoding="utf-8") as fh:
        cfg = json.load(fh)
    assert cfg["current"] in cfg["phases"]
    assert cfg["current_started"] == "2026-06-16"


# ── the derivation itself ─────────────────────────────────────────────────────


def test_y_anchor_is_the_experiment_start_date():
    ctx = _context(_state(), [], [])
    assert ctx["reset_epoch"] == EXPERIMENT_START_DATE


def test_a_stale_config_reset_epoch_is_ignored_negative_control():
    """THE regression. Plant the exact stale value that shipped for 83 days and
    assert it cannot reach the counter."""
    ctx = _context(_state(reset_epoch_date="2026-06-16"), [], [])
    assert ctx["reset_epoch"] == EXPERIMENT_START_DATE
    assert ctx["reset_epoch"] != "2026-06-16"


def test_the_measured_failure_day_one_of_a_cycle_renders_one_one():
    """The issue's own repro, as a fixture: four pre-genesis performed workouts
    (three of them 'upper'), a stale `reset_epoch_date`, and a routine written on
    day 2 of cycle 17. Pre-fix this rendered `- 3 - 11`-shaped inflation because
    both windows opened at 2026-06-16; post-fix Y opens at genesis and sees none
    of them.
    """
    performed = [
        {"date": "2026-06-20", "workout_uid": "hevy:a"},
        {"date": "2026-07-04", "workout_uid": "hevy:b"},
        {"date": "2026-08-11", "workout_uid": "hevy:c"},
        {"date": "2026-08-30", "workout_uid": "hevy:d"},
    ]
    index = [{"archetype": "upper", "target_date": d["date"], "variant": "ideal"} for d in performed]

    def _performed_since(start):
        return [r for r in performed if r["date"] >= start]

    with (
        patch.object(rt, "load_phase_state", return_value=_state(reset_epoch_date="2026-06-16")),
        patch.object(rt, "_query_performed", side_effect=_performed_since),
        patch.object(rt, "_load_routine_index", return_value=index),
    ):
        ctx = rt.build_title_context(_ir(archetype="upper", target_date="2026-09-07"))

    # N still counts within the phase, which the owner has NOT advanced — all four
    # prior sessions resolve to 'upper' and all four are on/after current_started,
    # so this is the fifth. That is CORRECT and is the owner's ruling: a phase may
    # deliberately span cycles, so N does not zero at genesis.
    assert ctx["type_count_in_phase"] == 5
    # Y is the number the owner actually asked for: nothing performed since genesis,
    # so this is workout 1 of the experiment.
    assert ctx["all_time_count"] == 1, "Y must zero at genesis — this is the #3671 defect"


def test_title_renders_the_derived_counters():
    performed = [{"date": "2026-06-20", "workout_uid": "hevy:a"}]
    index = [{"archetype": "upper", "target_date": "2026-06-20", "variant": "ideal"}]
    with (
        patch.object(rt, "load_phase_state", return_value=_state(reset_epoch_date="2026-06-16")),
        patch.object(rt, "_query_performed", side_effect=lambda s: [r for r in performed if r["date"] >= s]),
        patch.object(rt, "_load_routine_index", return_value=index),
    ):
        ir = _ir(archetype="upper", target_date="2026-09-07")
        title = rt.format_title(ir, rt.build_title_context(ir))
    assert title.endswith(" - 2 - 1"), title


# ── the reason the repo-side hand fix was inert ───────────────────────────────


def test_training_phases_is_not_staged_into_the_bundle():
    """Guards the fact that made #3675's hand re-anchor a no-op: this config does
    not ship in the Lambda zip, so the runtime reads S3. If someone later stages
    it, this test should be updated deliberately — with the S3 copy's fate decided
    in the same change, not left as a silent third copy.
    """
    sys.path.insert(0, os.path.join(ROOT, "deploy"))
    import build_bundle  # noqa: PLC0415

    staged = build_bundle.bundled_extra_paths(ROOT)
    assert staged, "bundled_extra_paths returned nothing — the enumerator moved, fix this test"
    assert not any(p.endswith("training_phases.json") for p in staged), (
        "training_phases.json is now staged into the bundle. That is a real change: the "
        "runtime would read the zip copy instead of S3. Decide the S3 copy's fate in the "
        "same change rather than leaving a silent third copy, then update this test. " + repr(staged)
    )
    # Positive control — the enumerator really does find the configs that ARE staged,
    # so the assertion above is not passing on an empty list.
    assert any(p.endswith("personas.json") for p in staged), staged
