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

#3916: `_registered_tools()` used to regex `tool_[a-z_]+` across the WHOLE
registry.py file, which reads a tool as "registered" through a surviving
`from mcp.tools_x import tool_foo` import line even after its `TOOLS` dict
entry is deleted (measured in #3891, refs #3692 — deleting the
`get_platform_state` entry while leaving its import in place still passed
this test). `_registered_tools()` now delegates to
`mcp_registry_ast.registered_fn_names()`, an AST-structural parse scoped to
the `TOOLS` dict literal itself — see `test_repro_3891_deleted_entry_survives_import`
below for the reproduction this guards.

Run:  python3 -m pytest tests/test_mcp_orphan_tools.py -v
"""

import os
import re

from mcp_registry_ast import registered_fn_names

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
MCP_DIR = os.path.join(ROOT, "mcp")


def _defined_tools():
    """Find every `def tool_*` across all tools_*.py modules.

    #3916: `[a-z_]+` (no digits) used to silently truncate names like
    `tool_get_zone2_breakdown` to `tool_get_zone` at the `2`. That was masked
    before this fix because the old whole-file `_registered_tools()` regex
    had the identical truncation bug and truncated the SAME name the SAME
    way — the two canceled out. The AST-structural `_registered_tools()`
    below returns the real, untruncated identifier, so this one has to match
    real Python identifiers (`[a-z0-9_]+`) too, or every digit-bearing tool
    name reads as a phantom orphan.
    """
    found = set()
    for f in os.listdir(MCP_DIR):
        if not f.startswith("tools_") or not f.endswith(".py"):
            continue
        with open(os.path.join(MCP_DIR, f), encoding="utf-8") as fh:
            for m in re.finditer(r"^def (tool_[a-z0-9_]+)", fh.read(), re.MULTILINE):
                found.add(m.group(1))
    return found


def _registered_tools():
    """Find every tool registered in registry.py's `TOOLS` dict (structural —
    see module docstring, #3916)."""
    path = os.path.join(MCP_DIR, "registry.py")
    if not os.path.exists(path):
        return set()
    with open(path, encoding="utf-8") as fh:
        return registered_fn_names(fh.read())


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


# ══════════════════════════════════════════════════════════════════════════════
# #3916 — the planted must-fail control: reproduces #3891's exact shape (a
# TOOLS dict entry deleted, its import left behind) against the structural
# parser directly, so a future regression back to a whole-file regex trips
# THIS test even if nothing in the live registry happens to exercise it.
# ══════════════════════════════════════════════════════════════════════════════


def test_repro_3891_deleted_entry_survives_import():
    """#3891 repro: deleting a `TOOLS` dict entry while leaving its `import`
    line in place must NOT read as registered. Before #3916's fix, the
    whole-file regex matched `tool_get_platform_state` inside the surviving
    import line and counted it as registered even though no `TOOLS` entry
    referenced it — exactly what let a real registry deletion pass this
    guard silently."""
    src = (
        "from mcp.tools_surfaces import tool_get_platform_state, tool_get_platform_surface\n"
        "\n"
        "TOOLS = {\n"
        '    "get_platform_surface": {\n'
        '        "fn": tool_get_platform_surface,\n'
        '        "schema": {"name": "get_platform_surface"},\n'
        "    },\n"
        "}\n"
    )
    registered = registered_fn_names(src)
    assert "tool_get_platform_state" not in registered, (
        "#3891: a surviving import must never count as registration — the "
        "TOOLS dict entry for get_platform_state was deleted, so it must "
        "read as an orphan"
    )
    assert "tool_get_platform_surface" in registered, "the entry that IS still in TOOLS must still read as registered"


def test_defined_tools_matches_digit_bearing_names():
    """#3916 (found while landing the fix above, not the issue's named shape,
    but the same file's other regex): `_defined_tools()`'s character class
    used to be `[a-z_]+` (no digits), silently truncating a name like
    `tool_get_zone2_breakdown` to `tool_get_zone`. That was invisible before
    this fix because the old `_registered_tools()` truncated the identical
    way and the two canceled out; the AST-structural `_registered_tools()`
    returns the real name, so `_defined_tools()` must too."""
    import tempfile

    global MCP_DIR
    with tempfile.TemporaryDirectory() as tmp:
        with open(os.path.join(tmp, "tools_example.py"), "w", encoding="utf-8") as fh:
            fh.write("def tool_get_zone2_breakdown(args):\n    return {}\n")
        original = MCP_DIR
        MCP_DIR = tmp
        try:
            found = _defined_tools()
        finally:
            MCP_DIR = original
    assert "tool_get_zone2_breakdown" in found, f"digit-bearing tool name truncated: {found}"
