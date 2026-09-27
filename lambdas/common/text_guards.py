"""common/text_guards.py — detect tool-call XML residue leaked into a free-text field (#4190).

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

TWO CONSUMERS, TWO POSTURES — one pattern set
  1. The MCP write doors REFUSE (`mcp/handler.py::_refuse_tool_call_residue`, ahead
     of every classified write tool — `mcp/audit.py::is_write_tool` — so a new write
     tool inherits the guard for free rather than needing to be added to a hand
     list). A refusal is a structured error that names the field and the fragment;
     nothing is written and nothing is rewritten. The owner's words are never
     silently trimmed at the door: the call is bounced back to the client, which
     re-issues it clean. (The first cut of this guard, PR #4196, truncated at the
     door instead — that rewrote a stored argument the owner never saw, and a
     truncation that happens to land mid-sentence is a second, quieter leak.)
  2. The site-api decisions serializer STRIPS (`lambdas/web/site_api_thirdwall.py::
     handle_decisions`), because a row can ALREADY be stored dirty (the 2026-09-08
     record above) and a serve-time screen is the only thing between it and a
     reader until the owner scrubs the row. Serve time has no client to bounce to,
     so truncation is the honest option there: defence in depth, not the fix.

THE PATTERN SET
  `TOOL_CALL_ENVELOPE_RE` is the set of literal tool-call-envelope forms: the
  Anthropic tool-call XML (`<function_calls>`, `<invoke name=…>`, `<parameter
  name=…>`, `<function_results>`, and the `antml:`-namespaced spelling of each),
  the generic `<tool_call>` / `<tool_use>` / `<tool_result>` shapes other clients
  emit, and the ONE closing tag on record, `</decision>`. Every alternative is
  unambiguous on a rendered HTML page too, so the leak-token sweep
  (`tests/leak_token_sweep.py`) uses this exact object — one pattern, three doors.

  `TOOL_CALL_RESIDUE_RE` is the envelope set PLUS a generic closing tag
  (`</note>`, `</content>` — the field-closer half of the specimen for any other
  string argument) and a generic bare opening tag (`<decision>`). It is for ONE
  isolated argument string, never a whole page. It deliberately has NO bare-`<`
  catch-all: "keep HR < 150" and "x<y" are the owner's own words, and a refuser
  that bounced them would be the rewrite this module exists to prevent.

Stdlib-only, no boto3 — bundled (#781) and importable from the MCP lambda and
every site-API lambda alike (`from common.text_guards import ...`).
"""

from __future__ import annotations

import re

_ENVELOPE_ALTERNATIVES = (
    # the ONE closing tag on record: the `decision` parameter's closer (2026-09-08 specimen)
    r"</decision>",
    # Anthropic tool-call XML, plain and antml-namespaced
    r"<(?:antml:)?function_calls\b",
    r"</(?:antml:)?function_calls>",
    r"<(?:antml:)?invoke\b",
    r"</(?:antml:)?invoke>",
    r"<(?:antml:)?parameter\b",
    r"</(?:antml:)?parameter>",
    r"<(?:antml:)?function_results\b",
    r"</(?:antml:)?function_results>",
    # other clients' tool-call / tool-result envelopes
    r"<tool_call\b",
    r"</tool_call>",
    r"<tool_use\b",
    r"</tool_use>",
    r"<tool_result\b",
    r"</tool_result>",
)

#: The literal tool-call-envelope forms. Safe on a full rendered page (no HTML
#: element is spelled like any of these), so the leak-token sweep shares it.
TOOL_CALL_ENVELOPE_RE = re.compile("|".join(_ENVELOPE_ALTERNATIVES), re.IGNORECASE)

#: The envelope forms plus the generic tag shapes a leaked parameter wrapper takes
#: for ANY field name: a closing tag (`</note>`) and a bare opening tag (`<note>`).
#: For one isolated argument string only. No bare `<`: an inequality is prose.
TOOL_CALL_RESIDUE_RE = re.compile(
    "|".join(_ENVELOPE_ALTERNATIVES + (r"</[A-Za-z_][\w.:-]*\s*>", r"<[A-Za-z_][\w.:-]*>")),
    re.IGNORECASE,
)


def find_tool_call_residue(text) -> str | None:
    """The FIRST tool-call-XML fragment in `text`, or None.

    Returns the matched fragment itself (e.g. `</decision>`), which is what a
    refusal names back to the caller. Non-string input never carries residue.
    """
    if not isinstance(text, str):
        return None
    m = TOOL_CALL_RESIDUE_RE.search(text)
    return m.group(0) if m else None


def has_tool_call_residue(text) -> bool:
    """True if `text` is a string carrying a tool-call-XML fragment."""
    return find_tool_call_residue(text) is not None


def residue_fragments(value, _path: str = "") -> list[tuple[str, str]]:
    """Walk a JSON-shaped value (dict / list / scalars) and return every
    `(path, fragment)` pair where a string leaf carries tool-call residue.

    Paths are dotted, list indices bracketed: `content.summary`, `domains[0]`.
    An empty list means the structure is clean. This is the shape a refuser needs
    to NAME what it refused without rewriting anything.
    """
    found: list[tuple[str, str]] = []
    if isinstance(value, str):
        frag = find_tool_call_residue(value)
        if frag is not None:
            found.append((_path or "<root>", frag))
    elif isinstance(value, dict):
        for k, v in value.items():
            found.extend(residue_fragments(v, f"{_path}.{k}" if _path else str(k)))
    elif isinstance(value, list):
        for i, v in enumerate(value):
            found.extend(residue_fragments(v, f"{_path}[{i}]"))
    return found


def strip_tool_call_residue(text):
    """Truncate `text` at the first tool-call-XML fragment, right-stripped.

    SERVE-TIME ONLY (defence in depth for an already-stored row). The write doors
    refuse instead — see the module docstring. Non-string input is returned
    unchanged; a string with no residue is returned unchanged. Idempotent.
    """
    if not isinstance(text, str):
        return text
    m = TOOL_CALL_RESIDUE_RE.search(text)
    if m is None:
        return text
    return text[: m.start()].rstrip()
