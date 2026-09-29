"""
tests/mcp_registry_ast.py — shared AST-structural parser for mcp/registry.py's
`TOOLS` dict (#3916).

Born because tests/test_mcp_orphan_tools.py's `_registered_tools()` and
tests/test_mcp_registry.py's `_get_tool_names()` each maintained their own
regex pass over registry.py, and the orphan-tools one matched `tool_[a-z_]+`
across the ENTIRE FILE, not just the registration table. Measured in #3891
(refs #3692): deleting a `TOOLS` dict entry while leaving its now-unused
import in place still read as "registered", because the regex saw the
surviving `from mcp.tools_x import tool_foo` line, not the (now-absent) dict
entry. Neither `test_mcp_orphan_tools.py` nor `test_r5_tool_count_in_range`
tripped, because both counted text tokens rather than the registration
structure.

This module parses `TOOLS = {...}` via `ast`, scoped to the dict literal
itself, so every caller derives its answer from ONE structural source of
truth instead of N independent regexes that can each drift differently.

Not a test module — no `test_` prefix, so pytest does not collect it.
"""

from __future__ import annotations

import ast
import os
from dataclasses import dataclass

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
REGISTRY_PATH = os.path.join(ROOT, "mcp", "registry.py")


@dataclass(frozen=True)
class ToolEntry:
    name: str  # the TOOLS dict key, e.g. "get_exercise_notes"
    fn_name: str  # the "fn" value's bound identifier, e.g. "tool_get_exercise_notes"


def _tools_dict_node(tree: ast.Module):
    """Find the module-level `TOOLS = {...}` assignment's dict literal."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "TOOLS":
                    return node.value
    return None


def parse_tool_entries(src: str) -> list[ToolEntry]:
    """Structurally extract every `"name": {"fn": <identifier>, ...}` entry
    from the `TOOLS` dict literal in `src`.

    Scoped to the dict literal's own AST nodes — an import line, a comment, or
    any other text elsewhere in the file can never contribute an entry here,
    which is the exact gap #3891 found in the old whole-file regex. Entries
    whose "fn" value isn't a plain identifier (`ast.Name`) are skipped; the
    real registry never does anything else, and skipping keeps this a
    structural parse rather than a re-implementation of Python's evaluator.
    """
    tree = ast.parse(src)
    tools_dict = _tools_dict_node(tree)
    entries: list[ToolEntry] = []
    if not isinstance(tools_dict, ast.Dict):
        return entries
    for key_node, value_node in zip(tools_dict.keys, tools_dict.values):
        if not (isinstance(key_node, ast.Constant) and isinstance(key_node.value, str)):
            continue
        if not isinstance(value_node, ast.Dict):
            continue
        fn_name = None
        for entry_key, entry_value in zip(value_node.keys, value_node.values):
            if isinstance(entry_key, ast.Constant) and entry_key.value == "fn" and isinstance(entry_value, ast.Name):
                fn_name = entry_value.id
                break
        if fn_name is not None:
            entries.append(ToolEntry(name=key_node.value, fn_name=fn_name))
    return entries


def registered_fn_names(src: str) -> set[str]:
    """The set of function identifiers actually bound as `"fn"` inside the
    `TOOLS` dict — i.e. genuinely registered, regardless of what else the
    file imports (#3891/#3916)."""
    return {entry.fn_name for entry in parse_tool_entries(src)}


def registered_tool_names(src: str) -> list[str]:
    """The `TOOLS` dict's own string keys, in source order. May contain
    duplicates — callers that care (e.g. an R4-style dup check) inspect that
    themselves; this function only reports what's structurally there."""
    return [entry.name for entry in parse_tool_entries(src)]


def read_registry_source() -> str:
    with open(REGISTRY_PATH, encoding="utf-8") as fh:
        return fh.read()


# ══════════════════════════════════════════════════════════════════════════════
# #4286: which registered tools structurally reach a DynamoDB write call.
#
# Used by test_mcp_registry.py's mutation-control check — a tool the registry
# derives `annotations.readOnlyHint` for must never claim True while its own
# implementing function can still run `table.put_item`/`update_item`/`delete_item`/
# `transact_write_items`/`batch_write_item`.
#
# The naive approach — walk only the tool's own FunctionDef — misses the
# `manage_*` fat-tool shape used across mcp/tools_{sick_days,pending_writes,
# reading,hevy_routine}.py: the tool body dispatches through a dict (either a
# local `VALID_ACTIONS = {...}` or a module-level `_DISPATCH = {...}` referenced
# by name), and the actual `.put_item(...)` etc. call lives in a per-action
# private helper the dict points at, not in the dispatcher's own AST.
#
# This resolves that by treating EVERY top-level symbol in a file — function
# defs AND simple-name assignments (`_DISPATCH = {...}`) alike — as a node with
# a "body" of referenced names, and taking the reachability closure from the
# tool's own function. Over-inclusive by design (a mere reference, not
# necessarily a call, counts) — the same fail-safe direction `is_write_tool`
# already takes ("unknown verb classifies as WRITE").
# ══════════════════════════════════════════════════════════════════════════════

_DDB_WRITE_METHODS = frozenset({"put_item", "update_item", "delete_item", "transact_write_items", "batch_write_item"})


def _module_symbol_bodies(tree: ast.Module) -> dict[str, ast.AST]:
    """Every top-level function def AND every top-level `NAME = <expr>` RHS in
    one module, keyed by name — the two shapes a same-module dispatch target
    takes in this codebase (a private helper function, or a dispatch dict
    bound to a module constant)."""
    bodies: dict[str, ast.AST] = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            bodies[node.name] = node
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    bodies[target.id] = node.value
    return bodies


def _referenced_names(node: ast.AST) -> set[str]:
    return {n.id for n in ast.walk(node) if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)}


def _has_ddb_write_call(node: ast.AST) -> bool:
    return any(isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr in _DDB_WRITE_METHODS for n in ast.walk(node))


def _reaches_ddb_write(start: str, bodies: dict[str, ast.AST]) -> bool:
    """BFS closure from `start` over same-module symbol references, stopping
    the first time a reachable body contains a direct DDB write call."""
    seen = {start}
    frontier = [start]
    while frontier:
        name = frontier.pop()
        body = bodies.get(name)
        if body is None:
            continue
        if _has_ddb_write_call(body):
            return True
        for ref in _referenced_names(body) - seen:
            seen.add(ref)
            frontier.append(ref)
    return False


def ddb_write_tool_names() -> set[str]:
    """Registered tool names whose implementing function structurally reaches
    a DynamoDB write call, directly or via a same-module dispatch target.

    Scoped to `mcp/*.py` only — a tool that delegates to a write in a
    different package (e.g. `lambdas/privacy/diary_claims.py`) is not traced
    here. That is a real limitation, not a silent one: this function is a
    soundness check for the tools it CAN see into, not a completeness claim
    over the whole codebase.
    """
    entries = parse_tool_entries(read_registry_source())
    mcp_dir = os.path.join(ROOT, "mcp")
    fn_to_file: dict[str, str] = {}
    file_bodies: dict[str, dict[str, ast.AST]] = {}
    for fname in sorted(os.listdir(mcp_dir)):
        if not fname.endswith(".py"):
            continue
        fpath = os.path.join(mcp_dir, fname)
        try:
            with open(fpath, encoding="utf-8") as fh:
                tree = ast.parse(fh.read(), filename=fpath)
        except SyntaxError:
            continue
        bodies = _module_symbol_bodies(tree)
        file_bodies[fpath] = bodies
        for name, node in bodies.items():
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                fn_to_file.setdefault(name, fpath)

    result: set[str] = set()
    for entry in entries:
        fpath = fn_to_file.get(entry.fn_name)
        if fpath is None:
            continue
        if _reaches_ddb_write(entry.fn_name, file_bodies[fpath]):
            result.add(entry.name)
    return result
