"""tests/test_routine_ir.py — IR serialize/deserialize round-trip + Decimal safety."""
from __future__ import annotations

from decimal import Decimal

from routine_ir import (
    IR_SCHEMA_VERSION,
    ExerciseBlock,
    RoutineSpec,
    Set,
    deserialize,
    serialize,
)


def _example_ir() -> RoutineSpec:
    return RoutineSpec(
        routine_id="r-1",
        target_date="2026-06-01",
        archetype="upper",
        version=1,
        created_at="2026-06-01T10:00:00Z",
        exercises=[
            ExerciseBlock(
                movement_key="db_bench_press_flat",
                sets=[
                    Set(type="normal", weight_kg=22.5, reps=10, rep_range_start=8, rep_range_end=12),
                    Set(type="normal", weight_kg=22.5, reps=9, rep_range_start=8, rep_range_end=12),
                ],
                rest_seconds=120,
                joint_friendly_score=3,
                skill_tier=2,
                rationale_tag="chest_MEV",
            ),
        ],
        budget_used={"chest": 2},
        caps={"total_sets": 25, "session_minutes": 75},
    )


def test_round_trip_preserves_structure():
    ir = _example_ir()
    body = serialize(ir)
    body["pk"] = "USER#matthew#ROUTINE#r-1"
    body["sk"] = "VERSION#current"
    body["ttl"] = Decimal("0")
    restored = deserialize(body)
    assert restored.routine_id == ir.routine_id
    assert restored.archetype == ir.archetype
    assert len(restored.exercises) == 1
    assert len(restored.exercises[0].sets) == 2
    assert restored.exercises[0].sets[0].weight_kg == 22.5


def test_serialize_emits_decimal_for_floats():
    ir = _example_ir()
    body = serialize(ir)
    weight = body["exercises"][0]["sets"][0]["weight_kg"]
    assert isinstance(weight, Decimal)


def test_deserialize_empty_raises():
    import pytest
    with pytest.raises(ValueError):
        deserialize({})


def test_schema_version_pinned():
    ir = _example_ir()
    assert ir.schema_version == IR_SCHEMA_VERSION == 1
