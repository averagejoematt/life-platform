"""tests/test_tools_hevy_routine.py — MCP fat tool gates + dispatcher."""
from __future__ import annotations

import sys
from unittest.mock import patch

import pytest

# The MCP package depends on boto3 + config at import time; conftest sets the
# path. Importing the tool module is enough.
from mcp import tools_hevy_routine as t
from routine_ir import ExerciseBlock, RoutineSpec, Set


def test_invalid_action_returns_error():
    out = t.tool_manage_hevy_routine({"action": "nuke"})
    assert out.get("error") or out.get("status") == "error" or "INVALID_ACTION" in str(out)


def test_commit_requires_routine_id():
    out = t.tool_manage_hevy_routine({"action": "commit"})
    # mcp_error returns a dict with 'error' or 'message' field
    assert "MISSING_ARG" in str(out) or out.get("error_code") == "MISSING_ARG" or "routine_id" in str(out)


def test_archive_requires_routine_id():
    out = t.tool_manage_hevy_routine({"action": "archive"})
    assert "MISSING_ARG" in str(out) or out.get("error_code") == "MISSING_ARG" or "routine_id" in str(out)


def test_dry_run_does_not_call_write_client():
    ir = RoutineSpec(
        routine_id="r-1", target_date="2026-06-01", archetype="upper",
        exercises=[ExerciseBlock(movement_key="db_bench_press_flat",
                                 sets=[Set(reps=10)])],
    )
    with patch("routine_repo.get_current", return_value=ir), \
         patch("hevy_template_cache.resolve_movement", return_value="55E6546B"), \
         patch("hevy_write_client.create_routine") as create_mock, \
         patch("hevy_write_client.update_routine_with_guard") as update_mock:
        result = t.tool_manage_hevy_routine({"action": "dry_run", "routine_id": "r-1"})
    create_mock.assert_not_called()
    update_mock.assert_not_called()
    assert result["status"] == "preview"
    assert "wire_body" in result


def test_archive_calls_update_not_delete():
    ir = RoutineSpec(
        routine_id="r-1", target_date="2026-06-01", archetype="upper",
        title="Upper",
        hevy_routine_id="abc12345",
        hevy_updated_at="2026-05-31T10:00:00Z",
        exercises=[ExerciseBlock(movement_key="db_bench_press_flat",
                                 sets=[Set(reps=10)])],
    )
    with patch("routine_repo.get_current", return_value=ir), \
         patch("routine_repo.put_versioned"), \
         patch("hevy_template_cache.resolve_movement", return_value="55E6546B"), \
         patch("hevy_write_client.list_folders", return_value={"routine_folders": []}), \
         patch("hevy_write_client.create_folder", return_value={"routine_folder": {"id": 99}}), \
         patch("hevy_write_client.update_routine_with_guard",
               return_value={"routine": {"id": "abc12345", "updated_at": "2026-05-31T12:00:00Z"}}) as upd:
        result = t.tool_manage_hevy_routine({"action": "archive", "routine_id": "r-1"})
    upd.assert_called_once()
    assert result["status"] == "archived"
    assert result["archive_folder_id"] == 99


def test_commit_handles_orphan_created():
    """When Hevy 400s but the routine was actually created, link the id and return a warning."""
    import hevy_write_client as wc
    ir = RoutineSpec(
        routine_id="r-orphan", target_date="2026-06-01", archetype="upper",
        exercises=[ExerciseBlock(movement_key="db_bench_press_flat",
                                 sets=[Set(reps=10)])],
    )
    captured: dict = {}
    def fake_put(updated):
        captured["last"] = updated
        return updated
    orphan_exc = wc.HevyOrphanCreated(
        hevy_routine_id="orphan-id",
        hevy_updated_at="2026-06-01T03:00:00Z",
        status=400, body='{"error":"x"}',
    )
    with patch("routine_repo.get_current", return_value=ir), \
         patch("routine_repo.put_versioned", side_effect=fake_put), \
         patch("routine_repo.upsert_id_map") as upsert_mock, \
         patch("hevy_template_cache.resolve_movement", return_value="55E6546B"), \
         patch("hevy_write_client.create_routine", side_effect=orphan_exc):
        result = t.tool_manage_hevy_routine({"action": "commit", "routine_id": "r-orphan"})
    assert "HEVY_ORPHAN_CREATED" in str(result)
    assert captured["last"].hevy_routine_id == "orphan-id"
    upsert_mock.assert_called_once_with("r-orphan", "orphan-id")


def test_archive_local_only_when_never_pushed():
    ir = RoutineSpec(
        routine_id="r-2", target_date="2026-06-01", archetype="upper",
        hevy_routine_id=None,
        exercises=[],
    )
    with patch("routine_repo.get_current", return_value=ir), \
         patch("routine_repo.put_versioned"), \
         patch("hevy_write_client.list_folders") as folders_mock:
        result = t.tool_manage_hevy_routine({"action": "archive", "routine_id": "r-2"})
    folders_mock.assert_not_called()
    assert result["status"] == "archived_local_only"
