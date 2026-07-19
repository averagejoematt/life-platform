"""tests/test_mcp_list_available_tools.py — #1477: list_available_tools domain
filter + honest full-registry listing.

Root cause: mcp.handler.handle_tools_call dispatches every tool the same way —
`_pool.submit(TOOLS[name]["fn"], arguments)` — i.e. it calls `fn(arguments)`
POSITIONALLY, passing the whole arguments dict as the tool function's first
parameter. Every other tool function in the registry follows the convention
`def tool_xxx(args): ...` (a single dict parameter, unpacked internally via
`args.get(...)`) precisely so this positional call works. `tool_list_available_tools`
was the one function written against a different, named-kwargs signature
(`def tool_list_available_tools(domain=None, keyword=None, limit=30)`), so the
whole `arguments` dict — e.g. `{"domain": "training"}` — got bound to its FIRST
parameter, `domain`. `domain` was then never the string a caller passed, it was
the dict `{"domain": "training"}` (or the value of whatever key came first),
which never equals any real `short_module`, so every filtered call matched zero
tools. See mcp/registry.py::tool_list_available_tools and
mcp/handler.py::handle_tools_call.

These tests exercise the real dispatch path (handle_tools_call), not the bare
function, so they catch exactly this class of calling-convention mismatch.
"""

from __future__ import annotations

import json
import os

# mcp.config reads these at import; mcp.handler pulls the full registry.
os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")

from mcp import handler as h  # noqa: E402
from mcp.registry import TOOLS  # noqa: E402


def _call(arguments):
    """Invoke list_available_tools through the real MCP dispatch path and
    decode the JSON text payload the tool-call handler returns."""
    result = h.handle_tools_call({"name": "list_available_tools", "arguments": arguments})
    return json.loads(result["content"][0]["text"])


def test_domain_filter_returns_only_that_domains_tools():
    """A domain-filtered call must return tools whose module is that domain,
    and it must not silently zero out (the #1477 bug: the whole arguments
    dict got bound to the `domain` positional param, so `short_module != domain`
    was always true and every filtered call returned 0 matches)."""
    payload = _call({"domain": "health"})
    assert payload["total_matching"] > 0, f"expected >0 'health' tools, got payload: {payload}"
    assert payload["tools"], "filtered call returned an empty tools list"
    for t in payload["tools"]:
        assert t["domain"] == "health", f"non-'health' tool leaked into filtered results: {t}"
    # The filter actually narrowed the result set vs. the full registry.
    assert payload["total_matching"] < payload["total_registered"]


def test_domain_filter_is_not_wrapped_under_domain_key():
    """Regression guard for the exact failure mode: passing a single keyword
    argument (of ANY name) must not get reinterpreted as the `domain` filter.
    Before the fix, a `limit`-only call bound the whole {"limit": 5} dict to
    `domain`, which broke filtering for every argument shape, not just 'domain'."""
    payload = _call({"limit": 5})
    # limit=5 with no domain/keyword filter must still see the whole registry,
    # not silently filter on some phantom domain derived from the raw arg dict.
    assert payload["total_registered"] == len(TOOLS)
    assert payload["filter"]["domain"] is None
    assert len(payload["tools"]) == 5


def test_no_arg_call_reports_full_registry_honestly():
    """A no-filter call must return the FULL registry (or, if truncated by an
    explicit smaller limit, say so honestly via total_matching/total_registered/
    truncated) — never silently cap at a fraction of the real tool count."""
    payload = _call({})
    assert payload["total_registered"] == len(TOOLS)
    assert payload["total_matching"] == len(TOOLS)
    assert len(payload["tools"]) == len(TOOLS), (
        f"no-arg call under-reported the registry: returned {len(payload['tools'])} of "
        f"{len(TOOLS)} tools. list_available_tools is the connector's inventory "
        f"discovery path — a silent partial listing misrepresents what's available."
    )
    assert payload.get("truncated") is False


def test_keyword_filter_still_works_through_dispatch():
    """Sanity: the keyword path was reachable before the fix (an empty {}
    dict binds falsy to `domain`), but confirm it survives the args-dict
    refactor unaffected."""
    payload = _call({"keyword": "readiness"})
    assert payload["total_matching"] >= 1
    assert any("readiness" in (t["name"] + t["description"]).lower() for t in payload["tools"])


def test_domain_and_keyword_combine():
    payload = _call({"domain": "health", "keyword": "readiness"})
    assert payload["total_matching"] >= 1
    for t in payload["tools"]:
        assert t["domain"] == "health"
