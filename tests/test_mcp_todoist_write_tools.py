"""tests/test_mcp_todoist_write_tools.py — #1495: todoist write trio (update/
create/close_todoist_task) joins the args-dict dispatch convention.

Root cause (the same bug class as #1477, mcp/registry.py::tool_list_available_tools):
mcp.handler.handle_tools_call dispatches every tool positionally —
`_pool.submit(TOOLS[name]["fn"], arguments)`, i.e. `fn(arguments)` — passing the
WHOLE arguments dict as the tool function's first parameter. Every function in
the registry follows the fleet convention of a single positional dict param
(`def tool_xxx(args): ...`, unpacked internally via `args.get(...)`) precisely
so this positional call works.

update_todoist_task, create_todoist_task, and close_todoist_task
(mcp/tools_todoist.py) were written with named kwargs instead
(`def update_todoist_task(task_id, due_string=None, ...)`), so the whole
`arguments` dict bound to their FIRST kwarg:
  - update_todoist_task: `task_id` became the entire arguments dict, every
    other field stayed at its None default, so `payload` was always empty and
    the tool always returned "No fields provided to update".
  - create_todoist_task: `content` became the entire arguments dict, so the
    tool POSTed a dict (not a string) as the task's content.
  - close_todoist_task: `task_id` became the entire arguments dict, so the
    tool built `POST /tasks/{the whole dict}/close` — a URL that can never
    match a real task.

The mcp-audit/ S3 write-tool trail was empty for all three — zero evidence
they ever worked live.

These tests exercise the REAL dispatch path (`mcp.handler.handle_tools_call`),
not the bare functions, so they catch exactly this class of calling-convention
mismatch. `_todoist_request` (the only network call each function makes) is
mocked — no real HTTP/AWS call happens. A second layer of tests calls the bare
functions directly with a missing required field, to prove the function itself
(not just the dispatcher's SEC-3 schema check) fails cleanly rather than
raising a KeyError/TypeError.
"""

from __future__ import annotations

import json
import os
from unittest.mock import patch

import pytest

# mcp.config reads these at import; mcp.handler pulls the full registry.
os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")

from mcp import handler as h  # noqa: E402
from mcp.tools_todoist import (  # noqa: E402
    close_todoist_task,
    create_todoist_task,
    update_todoist_task,
)


def _call(name, arguments):
    """Invoke a tool through the real MCP dispatch path and decode the JSON
    text payload the tool-call handler returns."""
    result = h.handle_tools_call({"name": name, "arguments": arguments})
    return json.loads(result["content"][0]["text"])


# ── update_todoist_task ──────────────────────────────────────────────────────


def test_update_todoist_task_sends_correct_payload_through_dispatch():
    """The #1495 bug: task_id bound to the WHOLE arguments dict, every other
    field stayed None, payload was always empty -> always 'No fields provided
    to update'. A correct binding must build the payload from the individual
    fields and hit the right task_id path."""
    fake_result = {"content": "Buy milk", "due": {"date": "2026-07-25"}, "priority": 2}
    with patch("mcp.tools_todoist._todoist_request", return_value=fake_result) as mock_req:
        payload = _call(
            "update_todoist_task",
            {"task_id": "12345", "content": "Buy milk", "priority": 2, "due_string": "every! week"},
        )

    assert mock_req.call_count == 1, f"_todoist_request was not called as expected: {mock_req.call_args_list}"
    method, path, body = mock_req.call_args[0]
    assert method == "POST"
    assert path == "/tasks/12345", f"task_id leaked into the path wrong: {path!r}"
    assert body == {"content": "Buy milk", "priority": 2, "due_string": "every! week"}, body
    assert payload.get("error") is None, f"tool returned an error: {payload}"
    assert payload["updated"] is True
    assert payload["task_id"] == "12345"


def test_update_todoist_task_missing_required_field_via_dispatch_errors_cleanly():
    """Calling without task_id must not reach the tool body at all -- SEC-3
    (mcp.handler._validate_tool_args) rejects it up front because task_id is
    'required' in the tool's inputSchema."""
    with pytest.raises(ValueError, match="task_id"):
        h.handle_tools_call({"name": "update_todoist_task", "arguments": {"content": "no id given"}})


def test_update_todoist_task_missing_task_id_bare_function_errors_cleanly():
    """Even called directly (bypassing SEC-3), the function itself must fail
    cleanly -- no KeyError/TypeError -- matching the {"error": "..."}
    convention used elsewhere in this file (e.g. tools_habits.py, tools_decisions.py)."""
    with patch("mcp.tools_todoist._todoist_request", return_value={}) as mock_req:
        result = update_todoist_task({"content": "no id given"})
    assert mock_req.call_count == 0, "should never reach the network call without a task_id"
    assert result == {"error": "task_id is required"}


# ── create_todoist_task ──────────────────────────────────────────────────────


def test_create_todoist_task_sends_correct_payload_through_dispatch():
    """The #1495 bug: content bound to the WHOLE arguments dict, so the tool
    POSTed a dict (not the task title string) as `content`."""
    fake_result = {"id": 999, "content": "Buy milk", "due": None, "project_id": 42}
    with patch("mcp.tools_todoist._todoist_request", return_value=fake_result) as mock_req:
        payload = _call(
            "create_todoist_task",
            {"content": "Buy milk", "project_id": "42", "due_string": "every! Sunday"},
        )

    assert mock_req.call_count == 1, f"_todoist_request was not called as expected: {mock_req.call_args_list}"
    method, path, body = mock_req.call_args[0]
    assert method == "POST"
    assert path == "/tasks"
    assert body == {"content": "Buy milk", "priority": 4, "project_id": "42", "due_string": "every! Sunday"}, body
    assert payload.get("error") is None, f"tool returned an error: {payload}"
    assert payload["created"] is True
    assert payload["task_id"] == "999"


def test_create_todoist_task_missing_required_field_via_dispatch_errors_cleanly():
    with pytest.raises(ValueError, match="content"):
        h.handle_tools_call({"name": "create_todoist_task", "arguments": {"project_id": "42"}})


def test_create_todoist_task_missing_content_bare_function_errors_cleanly():
    with patch("mcp.tools_todoist._todoist_request", return_value={}) as mock_req:
        result = create_todoist_task({"project_id": "42"})
    assert mock_req.call_count == 0, "should never reach the network call without content"
    assert result == {"error": "content is required"}


# ── close_todoist_task ───────────────────────────────────────────────────────


def test_close_todoist_task_sends_correct_path_through_dispatch():
    """The #1495 bug: task_id bound to the WHOLE arguments dict, so the tool
    built POST /tasks/{'task_id': '777'}/close instead of /tasks/777/close."""
    with patch("mcp.tools_todoist._todoist_request", return_value={}) as mock_req:
        payload = _call("close_todoist_task", {"task_id": "777"})

    assert mock_req.call_count == 1, f"_todoist_request was not called as expected: {mock_req.call_args_list}"
    method, path = mock_req.call_args[0][0], mock_req.call_args[0][1]
    assert method == "POST"
    assert path == "/tasks/777/close", f"task_id leaked into the path wrong: {path!r}"
    assert payload.get("error") is None, f"tool returned an error: {payload}"
    assert payload["closed"] is True
    assert payload["task_id"] == "777"


def test_close_todoist_task_missing_required_field_via_dispatch_errors_cleanly():
    with pytest.raises(ValueError, match="task_id"):
        h.handle_tools_call({"name": "close_todoist_task", "arguments": {}})


def test_close_todoist_task_missing_task_id_bare_function_errors_cleanly():
    with patch("mcp.tools_todoist._todoist_request", return_value={}) as mock_req:
        result = close_todoist_task({})
    assert mock_req.call_count == 0, "should never reach the network call without a task_id"
    assert result == {"error": "task_id is required"}
