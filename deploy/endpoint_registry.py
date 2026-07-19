#!/usr/bin/env python3
"""
deploy/endpoint_registry.py — the single AST-derived enumeration of every /api/*
endpoint path registered in lambdas/web/site_api_lambda.py (#1436).

Extracted from deploy/sync_doc_metadata.py::_auto_discover_endpoint_count (#1437),
which used to own this AST walk as a private implementation detail of a COUNT. #1436
needs the actual SET of path strings (to build a completeness gate over them), so the
walk moved here as the shared source of truth: sync_doc_metadata's doc-sync count and
tests/test_api_schema_completeness.py's completeness gate both call
discover_endpoint_records() and can never drift from each other — one AST walk, two
consumers.

lambdas/web/site_api_lambda.py registers routes through three mechanisms that grew
independently over time:
  1. The `ROUTES` dict — the primary GET dispatch table (`ROUTES.get(path)` at the
     bottom of `lambda_handler`). Some entries map to `None`: a placeholder that
     reserves the path while the real dispatch lives in mechanism #2 or #3, OR (for
     `/api/board_ask`, `/api/verify_subscriber`'s ROUTES entry) in a DIFFERENT lambda
     entirely (site_api_ai_lambda.py) that this module never parses.
  2. The `_SIMPLE_ROUTES` dict — the P4.5 scoped router for (mostly POST) "simple
     delegate" routes: `{path: (allowed_methods, handler_fn)}`, checked before ROUTES
     in `lambda_handler`. `allowed_methods` is a literal set of HTTP verbs, or `None`
     ("any method").
  3. Inline `if path == "/api/...":` / `if path.startswith("/api/coach/"):` branches
     inside `lambda_handler` itself.

A path can legitimately appear in more than one mechanism (a ROUTES `None` placeholder
whose real handler is `_SIMPLE_ROUTES` or an inline check) — that's one endpoint
registered twice for bookkeeping reasons, not two endpoints, so every record is keyed
by path and the mechanisms/methods observed are unioned onto it.

No AWS calls, no import of site_api_lambda.py itself (it pulls in boto3 clients
inappropriate to load at doc-sync/test-collection time) — pure `ast.parse`.
"""
from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SITE_API_PATH = ROOT / "lambdas" / "web" / "site_api_lambda.py"

# Sanity floor mirroring the other AST discoverers in sync_doc_metadata.py — a count
# below this means something structurally broke (wrong file, truncated parse), not a
# genuinely small router.
SANITY_FLOOR = 50


@dataclass
class EndpointRecord:
    """One discovered `/api/...` path and everything the AST walk could tell about it."""

    path: str
    mechanisms: set = field(default_factory=set)  # subset of {"routes", "simple_routes", "inline"}
    methods: set | None = None  # a concrete set of verbs when known; None = undetermined/any
    routes_placeholder: bool = False  # True if ROUTES maps this path to `None` (dispatch elsewhere)
    is_prefix: bool = False  # True for a `path.startswith(...)` inline match (e.g. "/api/coach/")

    def merge_methods(self, methods: set | None) -> None:
        """Union in another mechanism's method set. `None` (any/undetermined) only
        wins if nothing more specific has been recorded yet — a concrete set from one
        mechanism is more informative than "unknown" from another."""
        if methods is None:
            return
        if self.methods is None:
            self.methods = set(methods)
        else:
            self.methods |= methods


def _extract_routes_and_simple_routes(tree: ast.AST) -> dict[str, EndpointRecord]:
    """Walk top-level `ROUTES = {...}` and `_SIMPLE_ROUTES = {...}` assignments."""
    out: dict[str, EndpointRecord] = {}

    def _rec(path: str) -> EndpointRecord:
        return out.setdefault(path, EndpointRecord(path=path))

    for node in ast.walk(tree):
        if not (isinstance(node, ast.Assign) and isinstance(node.value, ast.Dict)):
            continue
        for target in node.targets:
            if not isinstance(target, ast.Name):
                continue
            if target.id == "ROUTES":
                for key, value in zip(node.value.keys, node.value.values):
                    if not (isinstance(key, ast.Constant) and isinstance(key.value, str)):
                        continue
                    rec = _rec(key.value)
                    rec.mechanisms.add("routes")
                    is_none = isinstance(value, ast.Constant) and value.value is None
                    rec.routes_placeholder = rec.routes_placeholder or is_none
                    if not is_none:
                        # ROUTES only ever dispatches after the fallback `if method !=
                        # "GET": return 405` guard in lambda_handler — a non-None
                        # ROUTES entry is GET-only.
                        rec.merge_methods({"GET"})
            elif target.id == "_SIMPLE_ROUTES":
                for key, value in zip(node.value.keys, node.value.values):
                    if not (isinstance(key, ast.Constant) and isinstance(key.value, str)):
                        continue
                    rec = _rec(key.value)
                    rec.mechanisms.add("simple_routes")
                    methods = None
                    if isinstance(value, ast.Tuple) and value.elts:
                        methods_node = value.elts[0]
                        if isinstance(methods_node, (ast.Set, ast.List, ast.Tuple)):
                            methods = {e.value for e in methods_node.elts if isinstance(e, ast.Constant) and isinstance(e.value, str)}
                        elif isinstance(methods_node, ast.Constant) and methods_node.value is None:
                            methods = None  # explicit "any method"
                    rec.merge_methods(methods)
    return out


def _extract_inline_paths(tree: ast.AST) -> dict[str, EndpointRecord]:
    """Walk `lambda_handler`'s body for `path == "..."` / `path.startswith("...")`."""
    handler_fn = None
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "lambda_handler":
            handler_fn = node
            break
    if handler_fn is None:
        return {}

    out: dict[str, EndpointRecord] = {}
    for node in ast.walk(handler_fn):
        if (
            isinstance(node, ast.Compare)
            and isinstance(node.left, ast.Name)
            and node.left.id == "path"
            and len(node.ops) == 1
            and isinstance(node.ops[0], ast.Eq)
            and len(node.comparators) == 1
            and isinstance(node.comparators[0], ast.Constant)
            and isinstance(node.comparators[0].value, str)
        ):
            p = node.comparators[0].value
            rec = out.setdefault(p, EndpointRecord(path=p))
            rec.mechanisms.add("inline")
        elif (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "startswith"
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "path"
            and len(node.args) == 1
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
        ):
            p = node.args[0].value
            rec = out.setdefault(p, EndpointRecord(path=p))
            rec.mechanisms.add("inline")
            rec.is_prefix = True
    return out


def discover_endpoint_records(source: str | None = None, path: Path | None = None) -> dict[str, EndpointRecord]:
    """AST-parse site_api_lambda.py and return `{path: EndpointRecord}`.

    Pass `source` directly (already-read text — the caller controls I/O and errors),
    or `path` (defaults to SITE_API_PATH). Raises the same exceptions `ast.parse`
    would on unreadable/unparseable source — mirrors the pre-refactor
    `_auto_discover_endpoint_count` contract, where the caller decides whether a soft
    None-on-failure is appropriate (doc-sync: yes; a test that wants to see the real
    error: no).

    Returns {} (not an error) if neither ROUTES nor _SIMPLE_ROUTES nor any inline
    check is found — callers apply their own sanity floor (see `SANITY_FLOOR`).
    """
    target_path = path or SITE_API_PATH
    if source is None:
        source = target_path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(target_path))

    merged = _extract_routes_and_simple_routes(tree)
    inline = _extract_inline_paths(tree)
    for p, inline_rec in inline.items():
        if p in merged:
            merged[p].mechanisms |= inline_rec.mechanisms
            merged[p].is_prefix = merged[p].is_prefix or inline_rec.is_prefix
        else:
            merged[p] = inline_rec
    return merged


def discover_endpoint_paths(source: str | None = None, path: Path | None = None) -> set[str]:
    """The bare path-string set — what `_auto_discover_endpoint_count` counts."""
    return set(discover_endpoint_records(source=source, path=path).keys())


if __name__ == "__main__":
    records = discover_endpoint_records()
    print(f"{len(records)} distinct /api/* endpoint paths discovered in {SITE_API_PATH}")
    for p in sorted(records):
        r = records[p]
        methods = "/".join(sorted(r.methods)) if r.methods else "ANY/unknown"
        flags = []
        if r.routes_placeholder:
            flags.append("routes-placeholder")
        if r.is_prefix:
            flags.append("prefix")
        flag_str = f" [{', '.join(flags)}]" if flags else ""
        print(f"  {p:<40} {methods:<14} via {'+'.join(sorted(r.mechanisms))}{flag_str}")
