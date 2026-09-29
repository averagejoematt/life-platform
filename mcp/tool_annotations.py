"""
mcp/tool_annotations.py — MCP `annotations` (readOnlyHint/destructiveHint/
idempotentHint) for every registered tool (#4286).

Before this module, `handle_tools_list` advertised name/description/inputSchema
only — a client had no way to tell a read from a write without calling
`tools/call` and finding out. This derives the three MCP-spec hint booleans
from facts the registry already carries, rather than hand-typing 86 literals:

  * readOnlyHint / destructiveHint — from `mcp.audit.is_write_tool`, the SAME
    write/read classification the R13-F12 rate limiter gates on and the #753
    audit trail records against. destructiveHint mirrors is_write_tool exactly
    (True for every write tool): that is the MCP spec's own default when
    annotations are absent, so stating it explicitly is a no-op for a
    conservative client, not a demotion. A finer split (e.g. an
    APPEND_BY_DESIGN write is additive, not destructive) is a later
    refinement, not required by #4286's acceptance box.
  * idempotentHint — for a write tool, from `mcp.idempotency.REPLAY_SEMANTICS`:
    a mechanism that converges on retry (DETERMINISTIC_KEY / CONTENT_KEY /
    CLAIM_LEDGER / READ_BEFORE_WRITE) is True; APPEND_BY_DESIGN / RESIDUAL (or
    an undeclared write) is False. A read tool is always idempotent.

THE THREE OVERRIDES (found running #4286's own AST mutation-control check,
`tests/mcp_registry_ast.py::ddb_write_tool_names`, against every registered
tool — see that check's docstring):

`mcp.audit.is_write_tool` classifies by the tool's NAME VERB, and three
registered tools carry a real DynamoDB write behind a read-classified verb:

  * `get_exercise_notes` — #4036 deliberately put an owner-only `action=dismiss`
    write on this existing tool rather than mint a new one (see its docstring
    in mcp/tools_training_notes.py); `_dismiss_pain_flag` calls `table.put_item`.
  * `get_coach_checkin_queue` — self-heals an empty question queue by
    generating and PERSISTING fresh questions (`_table_ref.put_item`, directly
    in `tool_get_coach_checkin_queue`'s own body) before returning them.
  * `plan_next_session` — stage 2 (`routine_id` supplied) runs `_run_stage_2` ->
    `_write_thread`, which `table.put_item`s the critics' verdicts as a coach
    thread row. This contradicts `mcp/audit.py`'s own READ_VERBS comment
    ("plan_next_session ... touches no partition") — filed as #4401.

An annotation must track the REAL capability, not the verb, so these three are
force-corrected here. This module does NOT change `is_write_tool` itself — that
would also change R13-F12 rate-limiting and #753 audit-trail behavior for
three tools that have never had either, which is a materially different,
higher-risk change than "add annotations" and belongs to its own issue (#4401).
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

# #4286/#4401: read-verb-classified tools with a real DDB write behind them —
# see the module docstring for the AST evidence on each. `is_write_tool` still
# says False for these (unchanged here); only the ANNOTATION is corrected.
WRITES_DESPITE_READ_VERB = frozenset({"get_exercise_notes", "get_coach_checkin_queue", "plan_next_session"})


def annotations_for(tool_name: str) -> dict[str, bool]:
    """The MCP `annotations` object for one registered tool name."""
    write = is_write_tool(tool_name) or tool_name in WRITES_DESPITE_READ_VERB
    if not write:
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
