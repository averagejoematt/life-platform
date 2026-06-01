"""tests/test_routine_repo.py — versioned write + id-map atomic + lookups."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

import routine_repo as repo
from routine_ir import ExerciseBlock, RoutineSpec, Set


def _ir(version: int = 1) -> RoutineSpec:
    return RoutineSpec(
        routine_id="r-1",
        target_date="2026-06-01",
        archetype="upper",
        version=version,
        exercises=[ExerciseBlock(movement_key="db_bench_press_flat", sets=[Set(reps=10)])],
    )


def _mock_table(items_by_key: dict | None = None):
    items_by_key = items_by_key or {}
    table = MagicMock()
    def get_item(Key):
        return {"Item": items_by_key.get((Key["pk"], Key["sk"]))} if items_by_key.get((Key["pk"], Key["sk"])) else {}
    table.get_item.side_effect = get_item
    return table


def test_put_versioned_writes_history_and_pointer():
    table = _mock_table()
    with patch.object(repo, "_table", table):
        repo.put_versioned(_ir(1))
    pks_written = [c.kwargs["Item"]["sk"] for c in table.put_item.call_args_list]
    assert "VERSION#000001" in pks_written
    assert "VERSION#current" in pks_written


def test_put_versioned_refuses_overwrite_on_conditional_failure():
    table = _mock_table()
    # Hook the conditional-check exception
    from botocore.exceptions import ClientError
    err = ClientError({"Error": {"Code": "ConditionalCheckFailedException"}}, "PutItem")
    table.put_item.side_effect = err
    ddb_meta = MagicMock()
    ddb_meta.meta.client.exceptions.ConditionalCheckFailedException = type(err)
    with patch.object(repo, "_table", table), patch.object(repo, "_ddb", ddb_meta):
        with pytest.raises(repo.RoutineConflict):
            repo.put_versioned(_ir(1))


def test_upsert_id_map_writes_both_directions():
    table = _mock_table()
    with patch.object(repo, "_table", table):
        repo.upsert_id_map("r-1", "abc12345")
    sks = [c.kwargs["Item"]["sk"] for c in table.put_item.call_args_list]
    assert "PLATFORM#r-1" in sks and "HEVY#abc12345" in sks


def test_lookup_round_trip():
    items = {
        (repo.ID_MAP_PK, "PLATFORM#r-1"): {"hevy_routine_id": "abc12345"},
        (repo.ID_MAP_PK, "HEVY#abc12345"): {"routine_id": "r-1"},
    }
    table = _mock_table(items)
    with patch.object(repo, "_table", table):
        assert repo.lookup_hevy_id("r-1") == "abc12345"
        assert repo.lookup_routine_id("abc12345") == "r-1"
