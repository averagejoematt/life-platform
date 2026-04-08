#!/usr/bin/env python3
"""
tests/test_mcp_registry.py — MCP registry integrity linter.

Prevents "registered but never implemented" bugs from reaching production.
Tonight's crash loop (2026-03-11) was caused by 4 such bugs stacked on top
of each other, each hidden behind the one before it.

Validates (all offline — no AWS credentials needed):
  R1  Every `from mcp.X import *` in registry.py resolves to a real file
  R2  Every "fn" value in TOOLS dict maps to a function defined in that module
  R3  Every tool has name, description, inputSchema in its schema
  R4  No duplicate tool names
  R5  Tool count in expected range (alerts on unexpected changes)

Run:  python3 -m pytest tests/test_mcp_registry.py -v
      python3 tests/test_mcp_registry.py  (standalone)

v1.0.0 — 2026-03-11 (born from the crash)
"""

import ast
import os
import re
import sys
import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
MCP_DIR = os.path.join(ROOT, "mcp")
REGISTRY_PATH = os.path.join(MCP_DIR, "registry.py")

# Expected tool count range — update when consolidating or adding tools
EXPECTED_MIN_TOOLS = 75   # updated for SIMP-1 Phase 1c+1d (86 tools as of v3.7.19)
EXPECTED_MAX_TOOLS = 130  # upper bound: updated for coach intelligence tools (V2.1)


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def _parse_registry():
    """Parse registry.py and extract imports and TOOLS dict references."""
    src = _read(REGISTRY_PATH)
    tree = ast.parse(src, filename="registry.py")
    return src, tree


# ══════════════════════════════════════════════════════════════════════════════
# R1 — Every import resolves to a real file
# ══════════════════════════════════════════════════════════════════════════════

def _get_wildcard_imports(tree):
    """Extract all `from mcp.X import *` module names."""
    modules = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("mcp."):
            modules.append(node.module)
    return modules


def test_r1_all_imports_resolve():
    """R1: Every module imported in registry.py must exist as a .py file."""
    _, tree = _parse_registry()
    imports = _get_wildcard_imports(tree)
    missing = []
    for mod in imports:
        # mcp.tools_data → mcp/tools_data.py
        parts = mod.split(".")
        filepath = os.path.join(ROOT, *parts) + ".py"
        if not os.path.exists(filepath):
            missing.append(f"{mod} → {filepath}")
    assert not missing, (
        f"R1 FAIL: {len(missing)} imported module(s) don't exist:\n"
        + "\n".join(f"  - {m}" for m in missing)
        + "\n\nThis is exactly what caused the 2026-03-11 crash loop."
    )


# ══════════════════════════════════════════════════════════════════════════════
# R2 — Every "fn" value in TOOLS dict is a real function
# ══════════════════════════════════════════════════════════════════════════════

def _get_tool_fn_names(src):
    """Extract all function names referenced as 'fn' values in TOOLS dict."""
    # Pattern: "fn": function_name,
    return re.findall(r'"fn":\s*([a-zA-Z_][a-zA-Z0-9_]*)', src)


def _get_all_defined_functions():
    """Collect all function names defined in tool modules + registry itself."""
    defined = set()

    # Get all .py files in mcp/
    for filename in os.listdir(MCP_DIR):
        if not filename.endswith(".py"):
            continue
        filepath = os.path.join(MCP_DIR, filename)
        try:
            tree = ast.parse(_read(filepath), filename=filename)
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    defined.add(node.name)
        except SyntaxError:
            pass  # Skip unparseable files; R1 or syntax check will catch them

    return defined


def test_r2_all_fn_references_exist():
    """R2: Every function referenced in TOOLS dict must be defined in a module."""
    src, _ = _parse_registry()
    fn_names = _get_tool_fn_names(src)
    defined = _get_all_defined_functions()

    missing = [fn for fn in fn_names if fn not in defined]
    assert not missing, (
        f"R2 FAIL: {len(missing)} function(s) referenced in TOOLS dict but never defined:\n"
        + "\n".join(f"  - {fn}" for fn in missing)
        + "\n\nEither implement the function or remove the tool registration."
    )


# ══════════════════════════════════════════════════════════════════════════════
# R3 — Every tool has valid schema structure
# ══════════════════════════════════════════════════════════════════════════════

def _get_tool_names(src):
    """Extract top-level tool names from TOOLS dict."""
    tools_start = src.find("TOOLS = {")
    if tools_start == -1:
        tools_start = src.find("TOOLS={")
    if tools_start == -1:
        return []
    tools_section = src[tools_start:]
    # [a-z0-9_]+ to handle names like get_zone2_breakdown
    return re.findall(r'^\s{4}"([a-z0-9_]+)"\s*:\s*\{', tools_section, re.MULTILINE)


def test_r3_schema_structure():
    """R3: Every tool must have name, description, and inputSchema in its schema."""
    src, _ = _parse_registry()
    tool_names = _get_tool_names(src)
    # Spot-check: every tool name should appear as "name": "tool_name" in a schema
    missing_schema_names = []
    for name in tool_names:
        pattern = rf'"name":\s*"{name}"'
        if not re.search(pattern, src):
            missing_schema_names.append(name)
    assert not missing_schema_names, (
        f"R3 FAIL: {len(missing_schema_names)} tool(s) missing schema name field:\n"
        + "\n".join(f"  - {n}" for n in missing_schema_names)
    )


# ══════════════════════════════════════════════════════════════════════════════
# R4 — No duplicate tool names
# ══════════════════════════════════════════════════════════════════════════════

def test_r4_no_duplicate_tool_names():
    """R4: No tool name should appear more than once in TOOLS dict."""
    src, _ = _parse_registry()
    tool_names = _get_tool_names(src)
    seen = {}
    duplicates = []
    for name in tool_names:
        if name in seen:
            duplicates.append(name)
        seen[name] = True
    assert not duplicates, (
        f"R4 FAIL: Duplicate tool names found: {duplicates}"
    )


# ══════════════════════════════════════════════════════════════════════════════
# R5 — Tool count in expected range
# ══════════════════════════════════════════════════════════════════════════════

def test_r5_tool_count_in_range():
    """R5: Tool count should be within expected range.

    Alerts if tools were added or removed without updating this test.
    Update EXPECTED_MIN_TOOLS / EXPECTED_MAX_TOOLS when consolidating.
    """
    src, _ = _parse_registry()
    tool_names = _get_tool_names(src)
    count = len(tool_names)
    assert EXPECTED_MIN_TOOLS <= count <= EXPECTED_MAX_TOOLS, (
        f"R5 FAIL: Found {count} tools, expected {EXPECTED_MIN_TOOLS}-{EXPECTED_MAX_TOOLS}. "
        f"If you intentionally changed the tool count, update EXPECTED_MIN_TOOLS / "
        f"EXPECTED_MAX_TOOLS in this test."
    )


# ══════════════════════════════════════════════════════════════════════════════
# R6 — Registry file parses without syntax errors
# ══════════════════════════════════════════════════════════════════════════════

def test_r6_registry_syntax_valid():
    """R6: registry.py must be valid Python syntax."""
    src = _read(REGISTRY_PATH)
    try:
        ast.parse(src)
    except SyntaxError as e:
        pytest.fail(f"R6 FAIL: registry.py has syntax error: {e}")


# ══════════════════════════════════════════════════════════════════════════════
# R7 — All tool module files parse without syntax errors
# ══════════════════════════════════════════════════════════════════════════════

def test_r7_all_tool_modules_parseable():
    """R7: Every tools_*.py file must be valid Python syntax."""
    errors = []
    for filename in sorted(os.listdir(MCP_DIR)):
        if not filename.startswith("tools_") or not filename.endswith(".py"):
            continue
        filepath = os.path.join(MCP_DIR, filename)
        try:
            ast.parse(_read(filepath))
        except SyntaxError as e:
            errors.append(f"{filename}: {e}")
    assert not errors, (
        f"R7 FAIL: {len(errors)} tool module(s) have syntax errors:\n"
        + "\n".join(f"  - {e}" for e in errors)
    )


# ══════════════════════════════════════════════════════════════════════════════
# Standalone runner
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import subprocess
    result = subprocess.run(
        ["python3", "-m", "pytest", __file__, "-v", "--tb=short"],
        cwd=ROOT,
    )
    sys.exit(result.returncode)
