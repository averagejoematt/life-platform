"""MCP resources: the platform-surface index, served as a resource (#4286 box 3).

`describe_platform_surfaces` answers "which surfaces exist and what rule does each apply"
with a tool call. A client that supports MCP resources can load the same index once, as
context, without a tool round-trip. This module serves it as one resource, built by the SAME
function the tool calls (`tools_surfaces.tool_describe_platform_surfaces`), so the resource
and the tool cannot disagree.

`resources/list` and `resources/read` go through `handler._process_jsonrpc`, behind the same
transport auth (`_validate_bearer` on the remote path, IAM on the bridge) as `tools/*`.
"""

from __future__ import annotations

import json

SURFACE_INDEX_URI = "life-platform://surfaces/index"

# JSON-RPC code the MCP spec (2025-06-18, "Resources") assigns to an unknown resource URI.
RESOURCE_NOT_FOUND_CODE = -32002


class ResourceNotFound(Exception):
    """A `resources/read` for a URI this server does not serve."""


def _surface_index_text() -> str:
    from mcp.tools_surfaces import tool_describe_platform_surfaces

    return json.dumps(tool_describe_platform_surfaces({}), default=str)


# uri -> (resource descriptor, content builder). One entry today; a second resource is one line.
_RESOURCES = {
    SURFACE_INDEX_URI: (
        {
            "uri": SURFACE_INDEX_URI,
            "name": "platform-surfaces",
            "title": "Platform surface index",
            "description": (
                "Every data surface the platform can answer from, with the phase filter, date basis and "
                "row provenance each one applies. The same index describe_platform_surfaces returns; fetch "
                "one surface with get_platform_surface(name=...)."
            ),
            "mimeType": "application/json",
        },
        _surface_index_text,
    ),
}


def handle_resources_list(_params):
    return {"resources": [descriptor for descriptor, _build in _RESOURCES.values()]}


def handle_resources_read(params):
    uri = (params or {}).get("uri", "")
    entry = _RESOURCES.get(uri)
    if entry is None:
        raise ResourceNotFound(f"Resource not found: {uri}")
    descriptor, build = entry
    return {"contents": [{"uri": uri, "mimeType": descriptor["mimeType"], "text": build()}]}
