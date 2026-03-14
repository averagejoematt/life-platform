#!/usr/bin/env python3
"""
tests/test_lambda_handlers.py — Lambda handler integration linter.

Uses ci/lambda_map.json as the authoritative registry of all deployable
Lambdas and validates each one structurally — no AWS credentials required.

Complements test_cdk_handler_consistency.py (which validates CDK stack
handler= values match source files) by treating lambda_map.json as the
CI source-of-truth and enforcing structural correctness on every handler.

Six rules:
  I1  Every Lambda registered in lambda_map.json exists on disk
  I2  Every Lambda registered in lambda_map.json parses without syntax errors
  I3  lambda_handler is defined with exactly 2 params: event + context
  I4  lambda_handler body has at least one top-level try/except block
      (error resilience — uncaught exceptions silently kill async Lambdas)
  I5  No orphaned Lambda files — every lambdas/*_lambda.py and
      lambdas/weather_handler.py is registered in lambda_map.json
      (or explicitly listed in skip_deploy)
  I6  MCP server entry point (mcp_server.py) also defines lambda_handler
      with correct arity — it's registered separately in lambda_map["mcp"]

Run:  python3 -m pytest tests/test_lambda_handlers.py -v
      python3 tests/test_lambda_handlers.py  (standalone)

v1.0.0 — 2026-03-13 (TB7-24)
"""

import ast
import json
import os
import sys
import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
LAMBDAS_DIR = os.path.join(ROOT, "lambdas")
LAMBDA_MAP_PATH = os.path.join(ROOT, "ci", "lambda_map.json")


# ── Load lambda_map.json ──────────────────────────────────────────────────────

def _load_lambda_map():
    with open(LAMBDA_MAP_PATH, encoding="utf-8") as f:
        return json.load(f)


LAMBDA_MAP = _load_lambda_map()

# All source files registered as regular Lambdas (excludes MCP, shared_layer, skip_deploy)
_REGISTERED_SOURCES = list(LAMBDA_MAP.get("lambdas", {}).keys())

# Files explicitly excluded from Lambda registration (layer modules, utilities)
_SKIP_DEPLOY = set(LAMBDA_MAP.get("skip_deploy", {}).get("files", []))

# MCP server entry point — registered separately under lambda_map["mcp"]
_MCP_SOURCE = LAMBDA_MAP.get("mcp", {}).get("source", "lambdas/mcp_server.py")


# ── AST helpers ───────────────────────────────────────────────────────────────

def _read(rel_path: str) -> str:
    with open(os.path.join(ROOT, rel_path), encoding="utf-8") as f:
        return f.read()


def _find_lambda_handler(tree: ast.Module):
    """Return the ast.FunctionDef node for lambda_handler, or None."""
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name == "lambda_handler":
                return node
    return None


def _handler_param_names(func_node) -> list:
    """Return parameter names from a FunctionDef node."""
    return [arg.arg for arg in func_node.args.args]


def _has_try_in_body(func_node) -> bool:
    """Return True if the top-level body of lambda_handler has a try block."""
    for stmt in func_node.body:
        if isinstance(stmt, ast.Try):
            return True
    return False


# ── I1 — All registered Lambda source files exist on disk ────────────────────

@pytest.mark.parametrize("rel_path", sorted(_REGISTERED_SOURCES))
def test_i1_source_file_exists(rel_path):
    """I1: Every Lambda registered in lambda_map.json must exist on disk."""
    full_path = os.path.join(ROOT, rel_path)
    assert os.path.exists(full_path), (
        f"I1 FAIL: {rel_path} registered in ci/lambda_map.json but not found on disk.\n"
        f"  Either add the file or remove the entry from lambda_map.json."
    )


# ── I2 — All registered Lambda source files parse without syntax errors ───────

@pytest.mark.parametrize("rel_path", sorted(_REGISTERED_SOURCES))
def test_i2_source_file_syntax_valid(rel_path):
    """I2: Every Lambda registered in lambda_map.json must have valid Python syntax."""
    full_path = os.path.join(ROOT, rel_path)
    if not os.path.exists(full_path):
        pytest.skip(f"{rel_path} not found (covered by I1)")
    src = _read(rel_path)
    try:
        ast.parse(src, filename=rel_path)
    except SyntaxError as e:
        pytest.fail(
            f"I2 FAIL: {rel_path} has a syntax error: {e}\n"
            f"  Fix the syntax before deploying."
        )


# ── I3 — lambda_handler has correct 2-param signature (event, context) ────────

@pytest.mark.parametrize("rel_path", sorted(_REGISTERED_SOURCES))
def test_i3_handler_signature(rel_path):
    """I3: lambda_handler must accept exactly 2 params: event and context."""
    full_path = os.path.join(ROOT, rel_path)
    if not os.path.exists(full_path):
        pytest.skip(f"{rel_path} not found (covered by I1)")

    src = _read(rel_path)
    try:
        tree = ast.parse(src, filename=rel_path)
    except SyntaxError:
        pytest.skip(f"{rel_path} has syntax error (covered by I2)")

    func = _find_lambda_handler(tree)
    assert func is not None, (
        f"I3 FAIL: {rel_path} has no lambda_handler function.\n"
        f"  Every Lambda must define: def lambda_handler(event, context):"
    )

    params = _handler_param_names(func)
    assert len(params) == 2, (
        f"I3 FAIL: {rel_path} lambda_handler has {len(params)} param(s): {params}.\n"
        f"  Expected exactly 2: (event, context)."
    )
    assert params[0] == "event", (
        f"I3 FAIL: {rel_path} lambda_handler first param is '{params[0]}', expected 'event'."
    )
    assert params[1] == "context", (
        f"I3 FAIL: {rel_path} lambda_handler second param is '{params[1]}', expected 'context'."
    )


# ── I4 — lambda_handler body has at least one top-level try/except block ──────

@pytest.mark.parametrize("rel_path", sorted(_REGISTERED_SOURCES))
def test_i4_handler_has_try_except(rel_path):
    """I4: lambda_handler must have a top-level try/except for error resilience.

    Async Lambdas silently fail without returning errors to the caller if an
    uncaught exception propagates. All handlers must catch exceptions at the
    top level and either return a structured error response or re-raise after
    logging.
    """
    full_path = os.path.join(ROOT, rel_path)
    if not os.path.exists(full_path):
        pytest.skip(f"{rel_path} not found (covered by I1)")

    src = _read(rel_path)
    try:
        tree = ast.parse(src, filename=rel_path)
    except SyntaxError:
        pytest.skip(f"{rel_path} has syntax error (covered by I2)")

    func = _find_lambda_handler(tree)
    if func is None:
        pytest.skip(f"{rel_path} has no lambda_handler (covered by I3)")

    assert _has_try_in_body(func), (
        f"I4 FAIL: {rel_path} lambda_handler has no top-level try/except block.\n"
        f"  Wrap the handler body in try/except to prevent silent failures:\n"
        f"\n"
        f"  def lambda_handler(event, context):\n"
        f"      try:\n"
        f"          # ... handler logic ...\n"
        f"          return {{\"statusCode\": 200, ...}}\n"
        f"      except Exception as e:\n"
        f"          logger.error(\"Handler failed: %s\", e)\n"
        f"          raise"
    )


# ── I5 — No orphaned Lambda files ─────────────────────────────────────────────

def test_i5_no_orphaned_lambda_files():
    """I5: Every lambdas/*_lambda.py and weather_handler.py must be in lambda_map.json.

    Orphaned files — Lambda source files not registered in ci/lambda_map.json
    and not in skip_deploy — will be silently ignored by CI/CD and never deployed.
    This catches newly added Lambdas that were forgotten from the registry.
    """
    candidate_files = set()
    for fname in os.listdir(LAMBDAS_DIR):
        if fname.endswith("_lambda.py") or fname == "weather_handler.py":
            candidate_files.add(f"lambdas/{fname}")

    registered = set(_REGISTERED_SOURCES)
    mcp_source = _MCP_SOURCE  # e.g. "lambdas/mcp_server.py" — not an orphan

    orphans = []
    for rel_path in sorted(candidate_files):
        if rel_path in registered:
            continue
        if rel_path in _SKIP_DEPLOY:
            continue
        if rel_path == mcp_source:
            continue
        # Also match by basename in skip_deploy (some entries use short names)
        basename = os.path.basename(rel_path)
        if any(basename in skip for skip in _SKIP_DEPLOY):
            continue
        orphans.append(rel_path)

    assert not orphans, (
        f"I5 FAIL: {len(orphans)} Lambda file(s) found in lambdas/ but not registered "
        f"in ci/lambda_map.json:\n"
        + "\n".join(f"  - {p}" for p in orphans)
        + "\n\n"
        f"  Either add them to lambda_map.json[\"lambdas\"] or list them in "
        f"lambda_map.json[\"skip_deploy\"][\"files\"]."
    )


# ── I6 — MCP server entry point has correct lambda_handler ───────────────────

def test_i6_mcp_server_handler():
    """I6: MCP server entry point must define lambda_handler(event, context).

    The MCP server is deployed differently (full mcp/ package) but its
    entry point must follow the same handler contract as all other Lambdas.
    """
    full_path = os.path.join(ROOT, _MCP_SOURCE)
    assert os.path.exists(full_path), (
        f"I6 FAIL: MCP server entry point '{_MCP_SOURCE}' not found on disk."
    )

    src = _read(_MCP_SOURCE)
    try:
        tree = ast.parse(src, filename=_MCP_SOURCE)
    except SyntaxError as e:
        pytest.fail(f"I6 FAIL: MCP server entry point has syntax error: {e}")

    func = _find_lambda_handler(tree)
    assert func is not None, (
        f"I6 FAIL: {_MCP_SOURCE} has no lambda_handler function."
    )

    params = _handler_param_names(func)
    assert len(params) == 2 and params[0] == "event" and params[1] == "context", (
        f"I6 FAIL: {_MCP_SOURCE} lambda_handler signature is ({', '.join(params)}), "
        f"expected (event, context)."
    )


# ── Standalone runner ─────────────────────────────────────────────────────────

if __name__ == "__main__":
    import subprocess
    result = subprocess.run(
        ["python3", "-m", "pytest", __file__, "-v", "--tb=short"],
        cwd=ROOT,
    )
    sys.exit(result.returncode)
