"""mcp/tools_meta.py — the meta-tool implementation (`list_available_tools`).

WHY IT MOVED HERE (#3668)
-------------------------
Every other tool in this server lives in a `mcp/tools_*.py` module; `registry.py` is the
dispatch TABLE. This one function was the exception — it sat at the bottom of the table,
which is the seam #1400/#1654/#2604 keep re-cutting elsewhere in the tree (a facade plus
cohesive siblings). Lifting it out is the extraction the module-size ratchet asks for
BEFORE any number moves, and it puts the meta-tool next to `mcp/surface_index.py`, the
other "what can I ask?" surface.

`list_registered_tools(tools, args)` takes the registry as an ARGUMENT rather than
importing it: `registry.py` imports this module, so an import the other way would be a
cycle. The registry keeps a two-line binding, so the dispatch table still names the
callable it dispatches to.

#1477: like every other tool, the registry-facing wrapper takes a single `args` dict —
`mcp.handler.handle_tools_call` dispatches ALL tools positionally (`fn(arguments)`), so a
function written with named kwargs would get the whole arguments dict bound to its first
named parameter.
"""

from __future__ import annotations

MAX_RESULTS = 100


def list_registered_tools(tools: dict, args: dict | None = None) -> dict:
    """List MCP tools, optionally filtered by domain (module short-name) or keyword
    (substring of tool name or description). At most `limit` items, alphabetical."""
    args = args or {}
    domain = args.get("domain")
    keyword = args.get("keyword")
    limit = args.get("limit")
    if limit is None or limit < 1:
        limit = MAX_RESULTS
    if limit > MAX_RESULTS:
        limit = MAX_RESULTS
    matches = []
    kw_lower = (keyword or "").lower().strip()
    for tool_name, entry in tools.items():
        fn = entry.get("fn")
        schema = entry.get("schema", {})
        description = schema.get("description") or ""
        module = getattr(fn, "__module__", "") if fn else ""
        short_module = module.rsplit(".tools_", 1)[-1] if ".tools_" in module else module
        if domain and short_module != domain:
            continue
        if kw_lower and kw_lower not in (tool_name + " " + description).lower():
            continue
        matches.append(
            {"name": tool_name, "domain": short_module, "description": description[:200] + ("…" if len(description) > 200 else "")}
        )
    matches.sort(key=lambda m: m["name"])
    return {
        "total_matching": len(matches),
        "total_registered": len(tools),
        "tools": matches[:limit],
        # #1477: say so explicitly when `limit` cut the list short, so an honest partial
        # listing never reads like the full inventory.
        "truncated": len(matches) > limit,
        "filter": {"domain": domain, "keyword": keyword, "limit": limit},
    }
