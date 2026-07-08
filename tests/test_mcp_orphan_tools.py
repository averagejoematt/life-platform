"""
tests/test_mcp_orphan_tools.py — Phase 4.8 (2026-05-16): enforce MCP registry
wiring discipline.

Every `def tool_*` function in `mcp/tools_*.py` must be registered in
`mcp/registry.py` (the canonical wire). Internal view implementations that a
registered dispatcher routes to are named with a leading underscore (no
`tool_` prefix) so the wire stays unambiguous: `tool_*` == MCP-callable.

History (the AUDITED_AT ratchet — see docs/MCP_TOOL_AUDIT.md):
  2026-05-16  70 orphans allowlisted at birth (186 defined / 116 registered)
  2026-05-17  64 (V2 P4.1 — tools_calendar.py deleted, ADR-030)
  2026-07-08   0 (#395 ER-04 — every orphan deleted, renamed to a view
               implementation, or registered; allowlist retired EMPTY)

The allowlist is intentionally empty and should stay that way: a new orphan
fails CI immediately. Register the tool or delete the function.

Run:  python3 -m pytest tests/test_mcp_orphan_tools.py -v
"""

import os
import re

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
MCP_DIR = os.path.join(ROOT, "mcp")


def _defined_tools():
    """Find every `def tool_*` across all tools_*.py modules."""
    found = set()
    for f in os.listdir(MCP_DIR):
        if not f.startswith("tools_") or not f.endswith(".py"):
            continue
        with open(os.path.join(MCP_DIR, f), encoding="utf-8") as fh:
            for m in re.finditer(r"^def (tool_[a-z_]+)", fh.read(), re.MULTILINE):
                found.add(m.group(1))
    return found


def _registered_tools():
    """Find every tool registered in registry.py via `"some_name": tool_some_name`."""
    found = set()
    path = os.path.join(MCP_DIR, "registry.py")
    if not os.path.exists(path):
        return found
    with open(path, encoding="utf-8") as fh:
        for m in re.finditer(r"tool_[a-z_]+", fh.read()):
            found.add(m.group(0))
    return found


# #395 (2026-07-08): the allowlist ended the ER-04 story EMPTY — all 64 entries
# were deleted or converted to underscore-named view implementations behind
# registered dispatchers. Every removal cites the 30-day usage telemetry
# snapshotted in docs/MCP_TOOL_AUDIT.md. Do not repopulate this set.
KNOWN_ORPHANS: set[str] = set()

# The ratchet: total orphan count may only go DOWN. Reached zero 2026-07-08 (#395).
AUDITED_AT = 0


def test_no_unexpected_orphans():
    """Every tool_ function must be registered — the allowlist is empty (#395)."""
    defined = _defined_tools()
    registered = _registered_tools()
    orphans = defined - registered
    new_orphans = orphans - KNOWN_ORPHANS

    assert not new_orphans, (
        f"Found {len(new_orphans)} orphan tool(s):\n"
        + "\n".join(f"  - {t}" for t in sorted(new_orphans))
        + "\n\nFix: either register in mcp/registry.py, or (if it is an internal "
        "view implementation behind a registered dispatcher) rename it with a "
        "leading underscore and no tool_ prefix. The KNOWN_ORPHANS allowlist "
        "was retired empty by #395 — do not repopulate it."
    )


def test_orphan_count_doesnt_grow():
    """Catch accidental regression — the orphan count ratchet sits at zero."""
    defined = _defined_tools()
    registered = _registered_tools()
    orphans = defined - registered
    assert len(orphans) <= AUDITED_AT, (
        f"Orphan count is {len(orphans)} (ratchet is {AUDITED_AT}, reached 2026-07-08 "
        "via #395). Each orphan is tech debt — either register it or delete the function."
    )
