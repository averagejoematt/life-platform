"""tests/test_adherence_calc.py — programmed-vs-performed."""

from __future__ import annotations

from adherence_calc import calculate_adherence
from routine_ir import ExerciseBlock, RoutineSpec, Set


def _ir() -> RoutineSpec:
    return RoutineSpec(
        routine_id="r-1",
        target_date="2026-06-01",
        archetype="upper",
        exercises=[
            ExerciseBlock(movement_key="db_bench_press_flat", sets=[Set(), Set(), Set()]),
            ExerciseBlock(movement_key="lat_pulldown", sets=[Set(), Set(), Set()]),
        ],
    )


def test_full_completion_is_100():
    # Hevy template IDs sourced from the live reconciled catalog (commit 989cbdf).
    performed = {
        "exercises": [
            {"exercise_template_id": "3601968B", "sets": [{}, {}, {}]},  # db_bench_press_flat
            {"exercise_template_id": "6A6C31A5", "sets": [{}, {}, {}]},  # lat_pulldown
        ]
    }
    result = calculate_adherence(_ir(), performed)
    assert result["overall_pct"] == 100.0
    assert result["per_muscle"]["chest"] == 100.0
    assert result["per_muscle"]["back"] == 100.0
    assert result["missing"] == []


def test_partial_completion_reports_per_muscle():
    performed = {
        "exercises": [
            {"exercise_template_id": "3601968B", "sets": [{}, {}]},  # 2 of 3
        ]
    }
    result = calculate_adherence(_ir(), performed)
    assert result["per_muscle"]["chest"] < 100.0
    assert result["per_muscle"]["back"] == 0.0
    assert "lat_pulldown" in result["missing"]


def test_extra_exercises_listed():
    performed = {
        "exercises": [
            {"exercise_template_id": "3601968B", "sets": [{}, {}, {}]},
            {"exercise_template_id": "6A6C31A5", "sets": [{}, {}, {}]},
            {"exercise_template_id": "DEADBEEF", "sets": [{}]},  # unprogrammed
        ]
    }
    result = calculate_adherence(_ir(), performed)
    assert "DEADBEEF" in result["extra"]
