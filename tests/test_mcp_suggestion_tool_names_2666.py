"""#2666 — an MCP error suggestion must not name a tool that does not exist.

Every MCP tool error carries `suggestions`: the recovery actions Claude reads and
acts on without re-prompting Matthew. A suggestion that says "Call get_data_freshness"
when no such tool is registered does not degrade to a no-op — Claude follows it and
gets a *second*, unrelated failure ("Unknown tool"), so the first error's real cause
is buried under a fabricated one.

GUARD THE SET, NOT THE INSTANCE. The issue named one bad string. Deriving the set by
AST found **two** distinct dead names across four sites:

    mcp/utils.py:164  NO_DATA         "Call get_data_freshness to check when this source last updated."
    mcp/utils.py:175  SOURCE_UNAVAIL  "Call get_data_freshness to see which sources are current."
    mcp/utils.py:180  PARTIAL_DATA    "Call get_data_freshness to see if the source is fully ingested."
    mcp/utils.py:184  QUERY_TOO_BROAD "Use get_longitudinal_summary for multi-year overviews instead."

Neither is in `mcp/registry.py`'s TOOLS. `get_freshness_status` is the tool that
answers the first three; nothing answers the fourth, so it is replaced with a
suggestion naming a tool that exists.

HOW THE SET IS DERIVED — every input is read out of source, nothing is hand-listed:

  * suggestion strings  = the `_DEFAULTS` dict in `_default_suggestions` PLUS every
    `suggestions=` kwarg / third positional argument at every `mcp_error(...)` call
    site under `mcp/`. A new suggestion anywhere is covered the day it lands.
  * registered tools    = the keys of the TOOLS dict in `mcp/registry.py`.
  * tool-name verbs     = the first `_`-segment of every registered tool name, so
    `get_`, `list_`, `manage_`, `end_`… come from the registry, not from a literal.
  * schema arg names    = the union of every `inputSchema.properties` key. This is
    what keeps `start_date`/`end_date` out of the candidate set: `end_experiment`
    makes `end` a tool verb, so `end_date` looks exactly like a tool reference
    until you subtract the arguments. Hand-excluding those two would re-introduce
    the same blind spot one rename later.

The planted-bad-name test below is what makes this a guard and not a snapshot: it
proves the extractor actually catches a fabricated tool name in a fresh suggestion.
"""

from __future__ import annotations

import ast
import os
import pathlib
import re
import sys

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO)
sys.path.insert(0, os.path.join(_REPO, "lambdas"))

os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "FAKE")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "FAKE")

import pytest  # noqa: E402

REPO = pathlib.Path(_REPO)
MCP_DIR = REPO / "mcp"

_SNAKE = re.compile(r"\b([a-z][a-z0-9]*(?:_[a-z0-9]+)+)\b")


def _string_constants(node: ast.AST) -> list[tuple[int, str]]:
    return [(n.lineno, n.value) for n in ast.walk(node) if isinstance(n, ast.Constant) and isinstance(n.value, str)]


def _registry() -> tuple[set[str], set[str], set[str]]:
    """(tool names, tool-name verbs, schema argument names) — all from registry.py."""
    tree = ast.parse((MCP_DIR / "registry.py").read_text())
    tools_node = None
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(getattr(t, "id", "") == "TOOLS" for t in node.targets):
            tools_node = node.value
    assert tools_node is not None, "TOOLS dict not found in mcp/registry.py"

    names = {k.value for k in tools_node.keys if isinstance(k, ast.Constant)}
    assert len(names) > 50, f"registry parse looks wrong — only {len(names)} tools"

    args: set[str] = set()
    for value in tools_node.values:
        for sub in ast.walk(value):
            if not isinstance(sub, ast.Dict):
                continue
            for k, v in zip(sub.keys, sub.values):
                if isinstance(k, ast.Constant) and k.value == "properties" and isinstance(v, ast.Dict):
                    args |= {pk.value for pk in v.keys if isinstance(pk, ast.Constant)}
    assert "start_date" in args and "end_date" in args, "schema-argument extraction failed"

    return names, {n.split("_", 1)[0] for n in names}, args


def _suggestion_strings() -> list[tuple[str, int, str]]:
    """Every string that can reach a caller as an MCP error `suggestions` entry."""
    found: list[tuple[str, int, str]] = []
    for path in sorted(MCP_DIR.rglob("*.py")):
        tree = ast.parse(path.read_text())
        rel = str(path.relative_to(REPO))
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and any(getattr(t, "id", "") == "_DEFAULTS" for t in node.targets):
                found += [(rel, ln, s) for ln, s in _string_constants(node.value)]
            if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "mcp_error":
                for kw in node.keywords:
                    if kw.arg == "suggestions":
                        found += [(rel, ln, s) for ln, s in _string_constants(kw.value)]
                if len(node.args) >= 3:
                    found += [(rel, ln, s) for ln, s in _string_constants(node.args[2])]
    return found


def _tool_references(text: str, verbs: set[str], schema_args: set[str]) -> set[str]:
    """snake_case tokens in `text` that read as a tool name (verb prefix, not an argument)."""
    return {tok for tok in _SNAKE.findall(text) if tok.split("_", 1)[0] in verbs and tok not in schema_args}


def test_suggestion_extraction_is_not_vacuous():
    """The extractor must actually find suggestion strings — an empty set passes everything."""
    suggestions = _suggestion_strings()
    assert len(suggestions) >= 20, f"only {len(suggestions)} suggestion strings found — extractor broke"
    assert any("Split the request into smaller date windows" in s for _, _, s in suggestions)


def test_every_tool_named_in_a_suggestion_is_registered():
    names, verbs, schema_args = _registry()
    offenders = []
    for rel, lineno, text in _suggestion_strings():
        for ref in sorted(_tool_references(text, verbs, schema_args)):
            if ref not in names:
                offenders.append(f"{rel}:{lineno} names '{ref}', not in registry — {text!r}")
    assert not offenders, "MCP suggestions point at tools that do not exist:\n  " + "\n  ".join(offenders)


@pytest.mark.parametrize(
    "planted,expected",
    [
        ("Call get_data_freshness to check when this source last updated.", "get_data_freshness"),
        ("Use get_longitudinal_summary for multi-year overviews instead.", "get_longitudinal_summary"),
        ("Try list_everything_ever for a full dump.", "list_everything_ever"),
    ],
)
def test_extractor_catches_a_planted_bad_name(planted, expected):
    """Proof the guard is live: a fabricated tool name in a suggestion is flagged."""
    names, verbs, schema_args = _registry()
    refs = _tool_references(planted, verbs, schema_args)
    assert expected in refs, f"extractor missed {expected!r} in {planted!r}"
    assert expected not in names


def test_argument_names_are_not_mistaken_for_tools():
    """`end_date` shares a prefix with `end_experiment`; subtracting schema args is what saves it."""
    names, verbs, schema_args = _registry()
    text = "Use YYYY-MM-DD format for both start_date and end_date."
    assert _tool_references(text, verbs, schema_args) == set()
    assert "end" in verbs, "precondition: `end_experiment` makes `end` a tool verb"


def test_suggested_tools_are_importable_at_runtime():
    """Not just present in the AST — actually wired into the live TOOLS dict."""
    from mcp.registry import TOOLS
    from mcp.utils import _default_suggestions

    names, verbs, schema_args = _registry()
    for code in ("NO_DATA", "SOURCE_UNAVAIL", "PARTIAL_DATA", "QUERY_TOO_BROAD", "DATE_RANGE", "INTERNAL", "RATE_LIMIT", "MISSING_ARG"):
        for text in _default_suggestions(code):
            for ref in _tool_references(text, verbs, schema_args):
                assert ref in TOOLS, f"{code} suggests '{ref}', absent from the live TOOLS dict"
