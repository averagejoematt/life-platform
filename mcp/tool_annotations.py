"""
mcp/tool_annotations.py — MCP `annotations` (readOnlyHint/destructiveHint/
idempotentHint) for every registered tool (#4286).

Before this module, `handle_tools_list` advertised name/description/inputSchema
only — a client had no way to tell a read from a write without calling
`tools/call` and finding out. This derives the three MCP-spec hint booleans
from facts the registry already carries, rather than hand-typing 86 literals:

  * readOnlyHint / destructiveHint — from `mcp.audit.is_write_tool`, the SAME
    write/read classification the #753 audit trail records against and the
    #4190 residue guard refuses on. (The R13-F12 rate limiter is NOT derived
    from it — `mcp/handler.py::_RATE_LIMITED_TOOLS` is its own explicit
    five-tool set, a subset of the write tools.) destructiveHint mirrors is_write_tool exactly
    (True for every write tool): that is the MCP spec's own default when
    annotations are absent, so stating it explicitly is a no-op for a
    conservative client, not a demotion. A finer split (e.g. an
    APPEND_BY_DESIGN write is additive, not destructive) is a later
    refinement, not required by #4286's acceptance box.
  * idempotentHint — for a write tool, from `mcp.idempotency.REPLAY_SEMANTICS`:
    a mechanism that converges on retry (DETERMINISTIC_KEY / CONTENT_KEY /
    CLAIM_LEDGER / READ_BEFORE_WRITE) is True; APPEND_BY_DESIGN / RESIDUAL (or
    an undeclared write) is False. A read tool is always idempotent.

THE THREE READ-VERB WRITERS (#4401): #4286's own AST mutation-control check
(`tests/mcp_registry_ast.py::ddb_write_tool_names`) found `get_exercise_notes`,
`get_coach_checkin_queue` and `plan_next_session` carrying a real DynamoDB write
behind a read-classified name verb. #4286 first corrected only their annotation
here, with a local override set; #4401 then moved the correction to its root —
`mcp.audit.WRITE_TOOLS_BEHIND_READ_VERB` — so `is_write_tool` itself now says
True for them. This module therefore derives readOnlyHint from `is_write_tool`
ALONE: the annotation, the #753 audit trail and the #4190 residue guard can no
longer disagree about which tools write.
"""

from __future__ import annotations

from typing import Any

from mcp.audit import is_write_tool
from mcp.idempotency import CLAIM_LEDGER, CONTENT_KEY, DETERMINISTIC_KEY, READ_BEFORE_WRITE, REPLAY_SEMANTICS, RESIDUAL

# Mechanisms under which a repeated call with the same arguments has no
# additional effect beyond the first (the MCP spec's idempotentHint semantics):
# the write converges on a deterministic/content-derived key, or a ledger/
# read-before-write guard suppresses the duplicate before it happens.
_IDEMPOTENT_MECHANISMS = frozenset({DETERMINISTIC_KEY, CONTENT_KEY, CLAIM_LEDGER, READ_BEFORE_WRITE})


def annotations_for(tool_name: str) -> dict[str, bool]:
    """The MCP `annotations` object for one registered tool name."""
    if not is_write_tool(tool_name):
        return {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True}
    mechanism, _reason = REPLAY_SEMANTICS.get(tool_name, (RESIDUAL, "undeclared"))
    return {
        "readOnlyHint": False,
        "destructiveHint": True,
        "idempotentHint": mechanism in _IDEMPOTENT_MECHANISMS,
    }


def annotate_tools(tools: dict[str, Any]) -> None:
    """Mutate every tool's `schema` in place to carry its derived `annotations`.

    Called once at import time from mcp/registry.py, after the `TOOLS` dict
    literal is built — `mcp/handler.py::handle_tools_list` already emits
    `t["schema"]` verbatim for every tool, so no handler change is needed for
    the annotations to reach the wire.
    """
    for name, entry in tools.items():
        entry["schema"]["annotations"] = annotations_for(name)
