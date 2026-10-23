"""tests/test_draft_display_5202.py — #5202: the draft and the SHADOW diff show what the routine will carry.

(a) a note carries only the CURRENT load rationale; (b) the SHADOW working-set count excludes the cardio block and
equals the IR's; (c) the SHADOW row shows loads at the routine's precision. Nothing here reads the clock or AWS.
"""

from __future__ import annotations

import os

import pytest
from training import routine_generator as rg, training_charter as tc
from training.routine_ir import ExerciseBlock, RoutineSpec, Set

os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")

from mcp import predraft_shadow as ps  # noqa: E402

LB = 0.45359237


@pytest.fixture(autouse=True)
def _fresh_charter():
    tc.reset_cache()
    yield
    tc.reset_cache()


def test_a_superseded_floor_line_never_survives_a_progression_step():
    catalog = rg._load_json("movement_catalog.json")
    tid = catalog["movements"]["lat_pulldown"]["hevy_template_id_hint"]
    history = {
        tid: [
            {"date": d, "top_weight_kg": 160 * LB, "sets": [{"weight_kg": 160 * LB, "reps": 12, "rpe": 7.5}]}
            for d in ("2026-10-16", "2026-10-14")
        ]
    }
    weights = {"2026-10-14": 300.0, "2026-10-16": 300.0, "2026-10-18": 300.0}
    block = ExerciseBlock(movement_key="lat_pulldown", sets=[Set(type="normal", rep_range_start=8, rep_range_end=12)] * 2, notes="")
    rg._enforce_load_floors([block], catalog, history, weights, "2026-10-19", 1, 7, [])
    assert "+5 lb to 165 lb" in block.notes
    assert "Floor " not in block.notes and "Down on the day" not in block.notes and "capped at" not in block.notes


def _routine(top_kg: float):
    work = ExerciseBlock(movement_key="db_curl", sets=[Set(weight_kg=top_kg, reps=10)] * 3, rest_seconds=60)
    cardio = ExerciseBlock(movement_key="treadmill", sets=[Set(duration_seconds=1200)], rest_seconds=0)
    return RoutineSpec(routine_id="r", target_date="2026-10-21", archetype="upper", exercises=[work, cardio])


def test_the_shadow_working_set_count_excludes_the_cardio_block_and_equals_the_irs():
    ir = _routine(12.0)
    side = ps.charter_side(ir, {"session_role": "upper_heavy"}, {})
    ir_working = sum(len(b.sets) for b in ir.exercises if b.movement_key != "treadmill")
    assert side["total_sets"] == ir_working == 3
    assert [e["movement_key"] for e in side["exercises"]] == ["db_curl"]
    assert [c["movement_key"] for c in side["cardio_blocks"]] == ["treadmill"]


def test_the_shadow_row_keeps_the_routines_load_precision():
    side = ps.charter_side(_routine(27.5 * LB), {"session_role": "upper_heavy"}, {})
    assert side["exercises"][0]["top_load_lb"] == 27.5
