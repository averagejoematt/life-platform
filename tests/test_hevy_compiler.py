"""tests/test_hevy_compiler.py — IR <-> Hevy wire format."""
from __future__ import annotations

import pytest

from hevy_compiler import MovementUnmappable, from_hevy_response, to_create_body, to_update_body
from routine_ir import ExerciseBlock, RoutineSpec, Set


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
    raw = {"routine": {
        "id": "abc12345",
        "title": "Upper",
        "folder_id": 42,
        "notes": "",
        "updated_at": "2026-06-01T18:00:00Z",
        "created_at": "2026-06-01T17:55:00Z",
        "exercises": [{"exercise_template_id": "55E6546B", "sets": [{}, {}]}],
    }}
    parsed = from_hevy_response(raw)
    assert parsed["hevy_routine_id"] == "abc12345"
    assert parsed["updated_at"] == "2026-06-01T18:00:00Z"
    assert parsed["exercises"][0]["set_count"] == 2


def test_round_trip_response_to_diff():
    body = to_create_body(_ir(), _resolver_fn)
    simulated_response = {"routine": {
        "id": "abc12345",
        "title": body["routine"]["title"],
        "folder_id": body["routine"]["folder_id"],
        "notes": body["routine"]["notes"],
        "updated_at": "2026-06-01T18:00:00Z",
        "created_at": "2026-06-01T17:55:00Z",
        "exercises": body["routine"]["exercises"],
    }}
    parsed = from_hevy_response(simulated_response)
    assert parsed["hevy_routine_id"] == "abc12345"
    assert parsed["exercises"][0]["exercise_template_id"] == "55E6546B"
