"""Guard for #1239: verified-dead intelligence functions must stay deleted.

Six functions in ``lambdas/intelligence_common.py`` and two public fetchers in
``lambdas/character_engine.py`` were confirmed unreferenced by any live path and
deleted (they shipped in every Lambda bundle via the one-bundle rule, #781). This
test AST-scans the modules and asserts:

  1. None of the deleted symbols are DEFINED in the two modules.
  2. No live shipping module (``lambdas/`` or ``mcp/``) REFERENCES any of them --
     via a Name load, an attribute access, or an import.

Non-vacuity: on the pre-fix tree the symbols are still defined in
``intelligence_common.py``, so assertion (1) fails. See the PR body for the
captured pre-fix failure evidence.
"""

import ast
import os

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# The verified-dead symbols removed in #1239.
DELETED_SYMBOLS = {
    "write_action",
    "check_action_completion",
    "build_action_history_for_prompt",
    "compute_all_credibility",
    "summarize_coach_month",
    "read_thread_summaries",
    "fetch_character_sheet",
    "fetch_character_sheet_range",
}

# Modules the symbols were deleted from.
TARGET_MODULES = [
    os.path.join(REPO_ROOT, "lambdas", "intelligence_common.py"),
    os.path.join(REPO_ROOT, "lambdas", "character_engine.py"),
]

# Directories whose code ships in every bundle (#781) -- the "live" surface.
LIVE_DIRS = [
    os.path.join(REPO_ROOT, "lambdas"),
    os.path.join(REPO_ROOT, "mcp"),
]


def _defined_functions(path):
    """Return the set of function names defined anywhere in a module."""
    with open(path, encoding="utf-8") as fh:
        tree = ast.parse(fh.read(), filename=path)
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            names.add(node.name)
    return names


def _referenced_names(path):
    """Return every name a module references: Name loads, attribute accesses, imports."""
    with open(path, encoding="utf-8") as fh:
        tree = ast.parse(fh.read(), filename=path)
    refs = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            refs.add(node.id)
        elif isinstance(node, ast.Attribute):
            refs.add(node.attr)
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                refs.add(alias.name)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                refs.add(alias.name.split(".")[0])
    return refs


def _iter_py_files(dirs):
    for base in dirs:
        for root, _dirs, files in os.walk(base):
            for name in files:
                if name.endswith(".py"):
                    yield os.path.join(root, name)


def test_deleted_symbols_are_not_defined():
    """Assertion (1): none of the dead symbols are defined in the target modules."""
    for module in TARGET_MODULES:
        defined = _defined_functions(module)
        still_present = DELETED_SYMBOLS & defined
        assert not still_present, f"{os.path.relpath(module, REPO_ROOT)} still defines dead symbols: {sorted(still_present)}"


def test_no_live_module_references_deleted_symbols():
    """Assertion (2): no shipping module (lambdas/, mcp/) references the dead symbols."""
    offenders = {}
    for path in _iter_py_files(LIVE_DIRS):
        refs = _referenced_names(path) & DELETED_SYMBOLS
        if refs:
            offenders[os.path.relpath(path, REPO_ROOT)] = sorted(refs)
    assert not offenders, f"live modules still reference deleted symbols: {offenders}"
