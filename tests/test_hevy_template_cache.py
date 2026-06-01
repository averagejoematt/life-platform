"""tests/test_hevy_template_cache.py — cache, reconcile, loud failure."""
from __future__ import annotations

import time
from unittest.mock import patch

import pytest

import hevy_template_cache as tc
from hevy_template_cache import MovementUnmappable


_CATALOG = {
    "movements": {
        "db_bench_press_flat": {
            "title": "Bench Press (Dumbbell)",
            "hevy_template_id_hint": "55E6546B",
            "primary_muscle": "chest",
        },
        "machine_chest_press": {
            "title": "Chest Press (Machine)",
            "hevy_template_id_hint": "79D0BB16",
            "primary_muscle": "chest",
        },
        "no_hint_movement": {
            "title": "Mystery Lift",
            "primary_muscle": "back",
        },
    },
}


@pytest.fixture(autouse=True)
def _reset_state(tmp_path):
    tc._reset_cache_for_tests()
    yield
    tc._reset_cache_for_tests()


def test_resolve_movement_returns_hint_on_miss(tmp_path):
    cache_state = {"movements": {}, "updated_at": 0, "loaded_at": time.time()}
    with patch.object(tc, "_load_cache", return_value=cache_state), \
         patch.object(tc, "_load_catalog", return_value=_CATALOG), \
         patch.object(tc, "_write_s3_json"):
        tid = tc.resolve_movement("db_bench_press_flat")
    assert tid == "55E6546B"


def test_resolve_movement_loud_fail_on_missing_key():
    with patch.object(tc, "_load_catalog", return_value=_CATALOG), \
         patch.object(tc, "_load_cache", return_value={"movements": {}, "loaded_at": time.time()}), \
         patch.object(tc, "_write_s3_json"):
        with pytest.raises(MovementUnmappable):
            tc.resolve_movement("not_in_catalog")


def test_resolve_movement_loud_fail_on_no_hint():
    with patch.object(tc, "_load_catalog", return_value=_CATALOG), \
         patch.object(tc, "_load_cache", return_value={"movements": {}, "loaded_at": time.time()}), \
         patch.object(tc, "_write_s3_json"):
        with pytest.raises(MovementUnmappable):
            tc.resolve_movement("no_hint_movement")


def test_reconcile_custom_picks_title_match():
    listed_pages = [
        {"exercise_templates": [
            {"id": "AAAAAAAA", "title": "Bench Press (Barbell)", "primary_muscle_group": "chest"},
            {"id": "BBBBBBBB", "title": "Bench Press (Dumbbell)", "primary_muscle_group": "chest"},
        ]},
    ]
    def fake_list(page=1, page_size=100):
        return listed_pages[page - 1] if page - 1 < len(listed_pages) else {"exercise_templates": []}
    with patch.object(tc, "_load_catalog", return_value=_CATALOG), \
         patch.object(tc, "_load_cache", return_value={"movements": {}, "loaded_at": time.time()}), \
         patch.object(tc, "_write_s3_json"):
        tid = tc.reconcile_custom("db_bench_press_flat", fake_list)
    assert tid == "BBBBBBBB"


def test_reconcile_custom_disambiguates_by_muscle():
    listed_pages = [
        {"exercise_templates": [
            {"id": "FIRST", "title": "Chest Press (Machine)", "primary_muscle_group": "shoulders"},
            {"id": "SECOND", "title": "Chest Press (Machine)", "primary_muscle_group": "chest"},
        ]},
    ]
    def fake_list(page=1, page_size=100):
        return listed_pages[page - 1] if page - 1 < len(listed_pages) else {"exercise_templates": []}
    with patch.object(tc, "_load_catalog", return_value=_CATALOG), \
         patch.object(tc, "_load_cache", return_value={"movements": {}, "loaded_at": time.time()}), \
         patch.object(tc, "_write_s3_json"):
        tid = tc.reconcile_custom("machine_chest_press", fake_list)
    assert tid == "SECOND"


def test_reconcile_custom_raises_on_no_match():
    def fake_list(page=1, page_size=100):
        return {"exercise_templates": []}
    with patch.object(tc, "_load_catalog", return_value=_CATALOG), \
         patch.object(tc, "_load_cache", return_value={"movements": {}, "loaded_at": time.time()}), \
         patch.object(tc, "_write_s3_json"):
        with pytest.raises(MovementUnmappable):
            tc.reconcile_custom("db_bench_press_flat", fake_list)
