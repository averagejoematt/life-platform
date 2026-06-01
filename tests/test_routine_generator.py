"""tests/test_routine_generator.py — deterministic engine invariants."""
from __future__ import annotations

import json
import os

import pytest

import routine_generator as rg
from routine_generator import GeneratorInputs, generate_routines

CONFIG = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "config"))


@pytest.fixture(autouse=True)
def _config_dir(monkeypatch):
    monkeypatch.setattr(rg, "CONFIG_DIR", CONFIG)


def _green_inputs(target_date: str = "2026-06-01") -> GeneratorInputs:
    return GeneratorInputs(
        target_date=target_date,
        recovery_tier="green",
        acwr_flag="safe",
        volume_7d={},
        z2_minutes_7d=120,
        days_since_last_workout=2,
        add_load_enabled=False,
    )


def test_generates_ideal_plus_floor_for_lifting_day():
    routines = generate_routines(_green_inputs("2026-06-01"))  # Monday upper
    variants = {r.variant for r in routines}
    assert {"ideal", "floor"}.issubset(variants)


def test_re_entry_triggered_after_seven_days():
    inputs = _green_inputs("2026-06-01")
    inputs.days_since_last_workout = 8
    routines = generate_routines(inputs)
    variants = {r.variant for r in routines}
    assert "re_entry" in variants


def test_subtract_only_invariant_red_recovery_shrinks_budget():
    green = generate_routines(_green_inputs("2026-06-01"))
    ideal_green = next(r for r in green if r.variant == "ideal")
    red_inputs = _green_inputs("2026-06-01")
    red_inputs.recovery_tier = "red"
    red = generate_routines(red_inputs)
    ideal_red = next(r for r in red if r.variant == "ideal")
    green_total = sum(len(e.sets) for e in ideal_green.exercises)
    red_total = sum(len(e.sets) for e in ideal_red.exercises)
    assert red_total <= green_total, "red recovery must not increase total session sets"


def test_add_load_flag_does_not_increase_budget_today():
    """Until validation passes, add_load_enabled is a no-op (subtract-only stance)."""
    off = generate_routines(_green_inputs("2026-06-01"))
    on_inputs = _green_inputs("2026-06-01")
    on_inputs.add_load_enabled = True
    on = generate_routines(on_inputs)
    off_total = sum(len(e.sets) for r in off if r.variant == "ideal" for e in r.exercises)
    on_total = sum(len(e.sets) for r in on if r.variant == "ideal" for e in r.exercises)
    assert on_total == off_total


def test_bounded_outputs_session_set_ceiling():
    inputs = _green_inputs("2026-06-01")
    inputs.volume_7d = {m: 0 for m in
                       ("chest", "back", "shoulders", "biceps", "triceps")}
    routines = generate_routines(inputs)
    week_cfg = json.load(open(os.path.join(CONFIG, "training_week.json")))
    cap = week_cfg["session_set_ceiling"]
    for r in routines:
        total = sum(len(e.sets) for e in r.exercises)
        assert total <= cap, f"{r.variant} variant: {total} sets > cap {cap}"


def test_catalog_has_skill_tier_1_for_each_landmark_muscle():
    catalog = json.load(open(os.path.join(CONFIG, "movement_catalog.json")))
    landmarks = json.load(open(os.path.join(CONFIG, "training_landmarks.json")))
    missing = []
    for muscle in landmarks["muscles"]:
        if landmarks["muscles"][muscle]["MEV"] == 0:
            continue
        tier_1 = [k for k, v in catalog["movements"].items()
                  if v.get("primary_muscle") == muscle and v.get("skill_tier") == 1]
        if not tier_1:
            missing.append(muscle)
    assert not missing, f"Catalog missing skill-tier-1 movements for: {missing}"


def test_floor_session_uses_skill_tier_1_only():
    routines = generate_routines(_green_inputs("2026-06-01"))
    floor = next(r for r in routines if r.variant == "floor")
    for ex in floor.exercises:
        assert ex.skill_tier == 1, f"floor exercise {ex.movement_key} has skill_tier {ex.skill_tier}"


def test_inputs_snapshot_recorded():
    routines = generate_routines(_green_inputs("2026-06-01"))
    ideal = next(r for r in routines if r.variant == "ideal")
    snap = ideal.inputs_snapshot
    assert "recovery_tier" in snap
    assert "landmarks_hash" in snap
    assert "catalog_hash" in snap


def test_rest_day_returns_placeholder_only():
    routines = generate_routines(_green_inputs("2026-06-07"))  # Sunday rest
    assert len(routines) == 1
    assert routines[0].archetype == "rest"
    assert routines[0].exercises == []
