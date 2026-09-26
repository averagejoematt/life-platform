"""common/text_guards.py — strip tool-call XML residue leaked into a free-text field (#4190).

WHY THIS EXISTS
  A `log_decision` record dated 2026-09-08 (`source: mcp`) was stored with its
  `decision` field ending:

      …Committed to Hevy as Foundation - Push - 3 - 11.</decision>
      <parameter name="followed">true

  That tail is not something Matthew typed. It is the CLOSING half of the calling
  MCP client's OWN tool-call envelope — the `<function_calls><invoke name="log_decision">
  <parameter name="decision">…</parameter></invoke></function_calls>` XML a client
  emits to invoke a tool — echoed back INTO the string argument the client was
  assembling, by a client-side parsing bug outside this platform's control. The
  write door stored the argument verbatim, and `/api/decisions` served it straight
  through to `/protocols/experiments/`, where a reader saw raw tool-call markup in
  the middle of an experiment log (#4190).

  Stripped, not rejected: everything BEFORE the residue is still Matthew's own
  words (or the platform's own recommendation text) and stays valuable — the door
  truncates rather than 400s, the same "his call, in his words" bias that keeps
  `note` opt-in instead of format-policed.

  Applied at TWO points, defence in depth:
    1. Every free-text MCP write door (`mcp/handler.py::handle_tools_call`, ahead
       of every classified write tool — `mcp/audit.py::is_write_tool` — so a new
       write tool inherits the guard for free rather than needing to be added to a
       hand list).
    2. The site-api decisions serializer (`lambdas/web/site_api_thirdwall.py::
       handle_decisions`), because the 2026-09-08 record is ALREADY stored dirty
       and a serve-time screen is the only thing between it and a reader until the
       owner scrubs the row (an owner-approved DDB write, out of scope here).

Stdlib-only, no boto3 — bundled (#781) and importable from the MCP lambda and
every site-API lambda alike (`from common.text_guards import ...`).
"""

from __future__ import annotations

import re

#: Matches the EARLIEST tool-call-XML fragment in a string. The listed literal
#: alternatives are the forms actually seen live: the closing tag matching the
#: field name a client's tool-call XML wraps a string argument in (`</decision>`
#: here; other fields would close as `</note>`, `</content>`, etc. — the generic
#: `<` catch-all below is what actually covers those, this alternative documents
#: the one instance on record), an opening `<parameter name=` tag, its
#: `</parameter>` close, `<invoke`/`</invoke>`, and `<function_calls`/
#: `</function_calls>`. The trailing bare `<` is the deliberate catch-all: every
#: one of the specific forms above already starts with `<`, so it only ever fires
#: when none of the more specific ones matched first — in practice, ANY leftover
#: `<` in a stored field. A genuinely typed "<" (e.g. "keep HR < 150") is the
#: known, accepted false positive of that catch-all: the class of harm from raw
#: tool-call markup reaching a reader outweighs the rare truncated inequality, and
#: the truncation is silent (never a rejected write) — see `strip_tool_call_residue`.
TOOL_CALL_RESIDUE_RE = re.compile(
    r"</decision>|<parameter\s+name\s*=|</parameter>|<invoke|</invoke>|<function_calls|</function_calls>|<",
    re.IGNORECASE,
)


def has_tool_call_residue(text) -> bool:
    """True if `text` is a string carrying a tool-call-XML fragment."""
    return isinstance(text, str) and bool(TOOL_CALL_RESIDUE_RE.search(text))


def strip_tool_call_residue(text):
    """Truncate `text` at the first tool-call-XML fragment, right-stripped.

    Non-string input is returned unchanged — this module is not a general type
    coercer; the caller's own type guard runs first. A string with no residue is
    returned unchanged. Idempotent: stripping an already-clean string (or an
    already-stripped one) is a no-op.
    """
    if not isinstance(text, str):
        return text
    m = TOOL_CALL_RESIDUE_RE.search(text)
    if m is None:
        return text
    return text[: m.start()].rstrip()
