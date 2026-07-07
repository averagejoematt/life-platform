"""
tests/test_lambda_map_imports.py — AST-check ci/lambda_map.json annotations against real imports (#799, R22-CI-03).

Background (read before touching this file — the packaging model changed under it):

CI's "Check lambda_map coverage" step (.github/workflows/ci-cd.yml ~L179-198) and
tests/test_lambda_handlers.py's I5 only verify every Lambda source file HAS an entry
in ci/lambda_map.json. Neither ever validated that an entry's hand-maintained
`cdk_only` / `extra_files` annotations are actually CORRECT — i.e. that the handler's
real imports would resolve inside whatever gets deployed. That's the gap this file
closes.

Pre-#781 world (what cdk_only/extra_files were invented for): deploy_lambda.sh shipped
ONLY the single target .py file (+ whatever --extra-files listed) plus the shared
Lambda layer. A handler with a bundled-sibling import (not in the layer, not in
--extra-files) would deploy "successfully" and then die at next cold start with
Runtime.ImportModuleError — the "single-file deploy strips siblings" bug class. Entries
were hand-flagged `cdk_only: true` to steer engineers away from the unsafe path.

Post-#781 world (2026-07-06, ADR-131): the shared layer is RETIRED. deploy_lambda.sh,
deploy_fleet.sh, AND the CDK asset (cdk/stacks/lambda_helpers.py) ALL stage through the
exact same deploy/build_bundle.py — the WHOLE lambdas/ tree (+ food_vocabulary.json),
byte-identical regardless of path. life-platform-mcp / life-platform-mcp-warmer
additionally get mcp_server.py + the mcp/ package (build_bundle.stage_mcp). Verified by
reading deploy_lambda.sh (Step 2: `build_bundle.py $BUNDLE_FLAG --out ... --zip ...`,
unconditionally) and deploy_fleet.sh (same call, once, fleet-wide) and
cdk/stacks/lambda_helpers.py (`staged_tree_asset()` calls `build_bundle.stage_tree`).
`cdk_only`/`extra_files` are NOT read by any of the three deploy paths any more (grep
confirms zero references outside ci/lambda_map.json itself) — they are pure
documentation now, describing a bug class that can no longer occur via any sanctioned
deploy path. That doesn't make them wrong to keep (they're useful history + steer
engineers away from ever hand-rolling a single-file `aws lambda update-function-code`
outside these scripts), but it does mean the ACTUALLY valuable, mechanically-checkable
invariant today is different from "does cdk_only match some deploy-path branch":

  (a) Every mapped handler's un-guarded imports must resolve inside the ONE real bundle
      (stdlib | the full lambdas/ tree, exactly as build_bundle.py would stage it | a
      declared dependency layer {garth, garminconnect, PIL} | boto3/botocore, which ship
      in the base Lambda Python 3.12 runtime). An unresolvable import here means the
      handler will Runtime.ImportModuleError at cold start no matter which of the three
      identical deploy paths ships it — this is the live descendant of the bug class in
      #799, just no longer gated on which path you pick.

  (b) `cdk_only: true` annotations should correlate with a REAL reason to exist: the
      handler actually depends on a bundled sibling module (something beyond
      stdlib/layer/boto3). An entry marked cdk_only with no such dependency would have
      been safe to single-file-deploy even in the pre-#781 world — a sign the flag is
      stale/copy-pasted and should be reconsidered. (`extra_files` has zero live entries
      today — nothing to validate; if one is ever added, extend `_ANNOTATION_KEYS`.)

Guarded/optional imports (e.g. `measurements_ingestion_lambda.py`'s
`try: import openpyxl / except ImportError:`) are intentionally NOT held to strict
resolution — see `_is_guarded()`. Rule: an import is guarded if (1) it sits directly
inside an `except` handler's body (already a failure-path fallback), or (2) it is a
direct statement of a `try:` body whose handler(s) explicitly catch
ImportError/ModuleNotFoundError. A broad `except Exception:` (the I4-mandated
handler-wide catch-all every lambda_handler has) does NOT count — that would silently
exempt every function-local import in every handler, defeating the whole point.
"""

import ast
import json
import os
import sys

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
LAMBDAS_DIR = os.path.join(ROOT, "lambdas")
MCP_DIR = os.path.join(ROOT, "mcp")
LAMBDA_MAP_PATH = os.path.join(ROOT, "ci", "lambda_map.json")

_DEPLOY_DIR = os.path.join(ROOT, "deploy")
if _DEPLOY_DIR not in sys.path:
    sys.path.insert(0, _DEPLOY_DIR)
import build_bundle  # noqa: E402  the ONE staging implementation (#781) — reused, not duplicated

# #416 / ADR-117: deploy-critical lane. An unresolvable import here means the deploy
# artifact WILL Runtime.ImportModuleError at cold start — same class test_lambda_handlers.py
# guards, just at the import-resolution layer instead of handler existence/syntax/signature.
pytestmark = pytest.mark.deploy_critical


def _load_lambda_map():
    with open(LAMBDA_MAP_PATH, encoding="utf-8") as f:
        return json.load(f)


LAMBDA_MAP = _load_lambda_map()
_REGISTERED_LAMBDAS = LAMBDA_MAP.get("lambdas", {})
_MCP_ENTRY = LAMBDA_MAP.get("mcp", {})
_MCP_SOURCE = _MCP_ENTRY.get("source", "mcp_server.py")

# ── What's resolvable without any bundled sibling ─────────────────────────────────
STDLIB_MODULES = frozenset(sys.stdlib_module_names)

# The only two third-party dependency layers in the platform (cdk/stacks/constants.py:
# GARTH_LAYER_ARN, PILLOW_LAYER_ARN). The garth-layer publishes BOTH `garth` and
# `garminconnect` (docs/DECISIONS.md: "python-garminconnect is built on garth"; both
# ship from the same layer per the 2026-03-19 incident log). boto3/botocore ship inside
# the base Lambda Python 3.12 runtime itself, not a layer — always resolvable.
DEPENDENCY_LAYER_MODULES = frozenset({"garth", "garminconnect", "PIL", "boto3", "botocore"})


def _walk_module_names(root_dir: str) -> set:
    """Enumerate every dotted module/package name importable from root_dir.

    Mirrors deploy/build_bundle.py's staging rules exactly (same EXCLUDE_DIRS,
    same "package contents land at bundle root" shape) WITHOUT copying files to
    disk — walks the real source tree directly so this test tracks build_bundle.py
    if its exclude rules ever change, instead of duplicating a second copy of them.
    """
    names = set()
    for dirpath, dirnames, filenames in os.walk(root_dir):
        dirnames[:] = [d for d in dirnames if d not in build_bundle.EXCLUDE_DIRS]
        rel_dir = os.path.relpath(dirpath, root_dir)
        for fname in filenames:
            if not fname.endswith(".py"):
                continue
            rel_file = fname if rel_dir == "." else os.path.join(rel_dir, fname)
            mod = rel_file[:-3].replace(os.sep, ".")
            if mod.endswith(".__init__"):
                mod = mod[: -len(".__init__")]
            if not mod:
                continue
            names.add(mod)
            parts = mod.split(".")
            for i in range(1, len(parts)):
                names.add(".".join(parts[:i]))
    return names


# The "tree" bundle: what deploy_lambda.sh / deploy_fleet.sh / CDK stage for every
# function EXCEPT life-platform-mcp / life-platform-mcp-warmer.
TREE_MODULES = _walk_module_names(LAMBDAS_DIR)

# The "mcp" bundle: the tree PLUS mcp_server.py (root-level module) PLUS the mcp/
# package (build_bundle.stage_mcp). Only life-platform-mcp{,-warmer} get this shape.
_MCP_INNER_MODULES = _walk_module_names(MCP_DIR)
MCP_MODULES = TREE_MODULES | {"mcp", "mcp_server"} | {f"mcp.{m}" for m in _MCP_INNER_MODULES}


# ── AST helpers ────────────────────────────────────────────────────────────────────


def _build_parent_map(tree: ast.AST) -> dict:
    parents = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parents[child] = node
    return parents


def _catches_import_error(try_node: ast.Try) -> bool:
    """True if any handler on this Try explicitly names ImportError/ModuleNotFoundError."""
    for handler in try_node.handlers:
        t = handler.type
        names = []
        if isinstance(t, ast.Tuple):
            names = [elt.id for elt in t.elts if isinstance(elt, ast.Name)]
        elif isinstance(t, ast.Name):
            names = [t.id]
        if "ImportError" in names or "ModuleNotFoundError" in names:
            return True
    return False


def _is_guarded(node: ast.AST, parents: dict) -> bool:
    """Is this Import/ImportFrom an intentionally-optional dependency?

    Deliberately narrow (see module docstring): being *somewhere* inside a Try
    ancestor is NOT enough — every lambda_handler has a top-level try/except
    (I4), which would make this check vacuous. Only two patterns count:
      1. The import is a statement directly inside an `except ...:` body — it
         only runs as a fallback after something else already failed.
      2. The import is a direct statement of a `try:` body whose handler(s)
         explicitly catch ImportError/ModuleNotFoundError (not a bare/Exception
         catch-all).
    """
    parent = parents.get(node)
    if isinstance(parent, ast.ExceptHandler):
        return True
    if isinstance(parent, ast.Try) and node in parent.body and _catches_import_error(parent):
        return True
    return False


def _own_dotted_module(rel_path: str):
    """The dotted module name rel_path would have INSIDE its bundle, or None if
    rel_path lives outside the staged tree/mcp package (relative imports there
    can't be resolved by this helper)."""
    if rel_path.startswith("lambdas/"):
        rel = rel_path[len("lambdas/") :]
    elif rel_path.startswith("mcp/"):
        return "mcp." + rel_path[len("mcp/") :][:-3].replace(os.sep, ".")
    elif rel_path == "mcp_server.py":
        return "mcp_server"
    else:
        return None
    mod = rel[:-3].replace(os.sep, ".")
    if mod.endswith(".__init__"):
        mod = mod[: -len(".__init__")]
    return mod


def _resolves(name: str, available: set) -> bool:
    if not name:
        return True
    top = name.split(".")[0]
    return top in STDLIB_MODULES or top in DEPENDENCY_LAYER_MODULES or name in available


def _resolve_relative(node: ast.ImportFrom, own_module: str, available: set) -> bool:
    """PEP 328 relative-import resolution: level N walks N-1 packages up from the
    package CONTAINING own_module (level=1 == "this package")."""
    if own_module is None:
        return False
    own_pkg_parts = own_module.split(".")[:-1]
    level = node.level
    base_parts = own_pkg_parts[: len(own_pkg_parts) - (level - 1)] if level > 1 else own_pkg_parts
    base = ".".join(base_parts)
    if node.module:
        candidate = f"{base}.{node.module}" if base else node.module
        return candidate in available
    # Bare `from . import name[, name2, ...]` — each name may be a submodule OR an
    # attribute re-exported from the package's __init__ (can't tell without executing
    # it). Resolve if ANY name is a real submodule, else fall back to "does the base
    # package itself exist" (lenient — avoids false positives on __init__ re-exports).
    for alias in node.names:
        sub = f"{base}.{alias.name}" if base else alias.name
        if sub in available:
            return True
    return base in available


def unresolved_imports(full_path: str, rel_path: str, available: set) -> list:
    """Return actionable strings for every NON-guarded import in full_path that
    doesn't resolve against `available` (stdlib/layer/boto3 always resolve)."""
    with open(full_path, encoding="utf-8") as f:
        src = f.read()
    tree = ast.parse(src, filename=rel_path)
    parents = _build_parent_map(tree)
    own_module = _own_dotted_module(rel_path)
    bad = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if not _resolves(alias.name, available) and not _is_guarded(node, parents):
                    bad.append(f"line {node.lineno}: import {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0:
                if not _resolves(node.module, available) and not _is_guarded(node, parents):
                    bad.append(f"line {node.lineno}: from {node.module} import ...")
            else:
                if not _resolve_relative(node, own_module, available) and not _is_guarded(node, parents):
                    dots = "." * node.level
                    bad.append(f"line {node.lineno}: from {dots}{node.module or ''} import ... (relative)")
    return bad


def _sibling_bundle_deps(full_path: str, rel_path: str, available: set) -> set:
    """Every non-stdlib/non-layer module this file imports that resolves inside the
    bundle (i.e. a genuine "would break a single-file-only zip" dependency), whether
    or not the import is guarded — used only for the cdk_only consistency check."""
    with open(full_path, encoding="utf-8") as f:
        src = f.read()
    tree = ast.parse(src, filename=rel_path)
    own_module = _own_dotted_module(rel_path)
    deps = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.level == 0:
            names = [node.module] if node.module else []
        else:
            continue
        for name in names:
            if not name:
                continue
            top = name.split(".")[0]
            if top in STDLIB_MODULES or top in DEPENDENCY_LAYER_MODULES:
                continue
            if name in available and name != own_module and not (own_module and own_module.startswith(name + ".")):
                deps.add(name)
    return deps


def _fix_suggestion(rel_path: str, bad_import: str) -> str:
    return (
        f"{rel_path} — unresolvable import ({bad_import}).\n"
        f"  This handler ships via deploy/build_bundle.py (the whole lambdas/ tree, #781) on\n"
        f"  EVERY deploy path (CDK / deploy_lambda.sh / deploy_fleet.sh) — an import that doesn't\n"
        f"  resolve here WILL Runtime.ImportModuleError at cold start no matter which path ships it.\n"
        f"  Fix options:\n"
        f"    (a) typo / wrong path — correct the import.\n"
        f"    (b) missing sibling module — add it under lambdas/ (or mcp/ if this is the MCP handler).\n"
        f"    (c) genuine third-party dependency — either wrap it in try/except ImportError (the\n"
        f"        openpyxl pattern in lambdas/ingestion/measurements_ingestion_lambda.py) if it's\n"
        f"        optional, or add a real dependency layer (like garth/pillow) and extend\n"
        f"        DEPENDENCY_LAYER_MODULES in tests/test_lambda_map_imports.py."
    )


# ── I7 — every mapped handler's imports resolve in the real bundle ────────────────


@pytest.mark.parametrize("rel_path", sorted(_REGISTERED_LAMBDAS.keys()))
def test_i7_handler_imports_resolve_in_tree_bundle(rel_path):
    """I7: every ci/lambda_map.json["lambdas"] handler's un-guarded imports must
    resolve inside the full-tree bundle build_bundle.py actually stages."""
    full_path = os.path.join(ROOT, rel_path)
    if not os.path.exists(full_path):
        pytest.skip(f"{rel_path} not found on disk (covered by test_lambda_handlers.py I1)")
    bad = unresolved_imports(full_path, rel_path, TREE_MODULES)
    assert not bad, "I7 FAIL: " + "; ".join(_fix_suggestion(rel_path, b) for b in bad)


def test_i7_mcp_server_imports_resolve_in_mcp_bundle():
    """I7 (MCP): mcp_server.py — the life-platform-mcp / -warmer entry point — gets
    the mcp-shaped bundle (tree + mcp_server.py + mcp/), not the plain tree."""
    full_path = os.path.join(ROOT, _MCP_SOURCE)
    assert os.path.exists(full_path), f"MCP server entry point '{_MCP_SOURCE}' not found on disk."
    bad = unresolved_imports(full_path, _MCP_SOURCE, MCP_MODULES)
    assert not bad, "I7 FAIL: " + "; ".join(_fix_suggestion(_MCP_SOURCE, b) for b in bad)


# ── I8 — cdk_only annotations correlate with a real bundled-sibling dependency ─────


def test_i8_cdk_only_entries_have_a_genuine_sibling_dependency():
    """I8: every `cdk_only: true` entry must actually import something beyond
    stdlib/dependency-layer/boto3 — i.e. a real bundled sibling that a naive
    single-file zip (the pre-#781 world cdk_only was invented to steer away from)
    would have missed. cdk_only no longer changes what deploy_lambda.sh/deploy_fleet.sh
    ship (#781 — see module docstring), so this is purely a documentation-honesty
    check: it catches a `cdk_only: true` copy-pasted onto a handler that never
    needed it (would have been single-file-deploy-safe even before #781)."""
    stale = []
    for rel_path, entry in sorted(_REGISTERED_LAMBDAS.items()):
        if not entry.get("cdk_only"):
            continue
        full_path = os.path.join(ROOT, rel_path)
        if not os.path.exists(full_path):
            continue  # covered by I1
        deps = _sibling_bundle_deps(full_path, rel_path, TREE_MODULES)
        if not deps:
            stale.append(
                f"{rel_path} is marked cdk_only but imports nothing beyond "
                f"stdlib/{sorted(DEPENDENCY_LAYER_MODULES)}/boto3 — the flag looks stale, "
                f"reconsider removing it or fix its _cdk_only_reason."
            )
    assert not stale, "I8 FAIL:\n  " + "\n  ".join(stale)


# ── Synthetic unit tests — prove the checker actually catches the bug class ───────
# These do NOT touch ci/lambda_map.json; they call the same helpers the production
# tests above use, against throwaway files, so they demonstrate detection without
# risking a false real-world mapping.


def _write(tmp_path, name: str, body: str) -> str:
    p = tmp_path / name
    p.write_text(body)
    return str(p)


def test_synthetic_unguarded_missing_sibling_is_flagged(tmp_path):
    """The core bug class: an un-guarded import of a module that doesn't exist
    anywhere in the bundle must be flagged — this is what would have shipped a
    Runtime.ImportModuleError under the old single-file world, and still would
    today if it slipped past deploy_lambda.sh's handler-resolves-in-bundle check."""
    full = _write(
        tmp_path,
        "bad_handler.py",
        "import totally_fake_module_xyz_not_in_any_bundle\n\n\ndef lambda_handler(event, context):\n    return {}\n",
    )
    bad = unresolved_imports(full, "lambdas/bad_handler.py", TREE_MODULES)
    assert len(bad) == 1
    assert "totally_fake_module_xyz_not_in_any_bundle" in bad[0]


def test_synthetic_guarded_missing_import_is_not_flagged(tmp_path):
    """The openpyxl pattern: a genuinely-missing module wrapped in
    try/except ImportError must NOT fail the suite — it's deliberately optional."""
    full = _write(
        tmp_path,
        "optional_handler.py",
        "\n".join(
            [
                "def lambda_handler(event, context):",
                "    try:",
                "        import totally_fake_optional_dep_xyz",
                "    except ImportError:",
                "        raise ImportError('optional dep not available')",
                "    return {}",
                "",
            ]
        ),
    )
    bad = unresolved_imports(full, "lambdas/optional_handler.py", TREE_MODULES)
    assert bad == []


def test_synthetic_import_inside_generic_exception_handler_is_still_checked(tmp_path):
    """The I4 trap this checker must NOT fall into: almost every lambda_handler wraps
    its whole body in `try: ... except Exception:` for error resilience (I4). An
    import textually inside THAT try must still be held to strict resolution —
    otherwise this checker would be vacuous for the exact handlers #799 cares about."""
    full = _write(
        tmp_path,
        "handler_with_broad_try.py",
        "\n".join(
            [
                "def lambda_handler(event, context):",
                "    try:",
                "        import totally_fake_module_inside_broad_try",
                "        return {}",
                "    except Exception as e:",
                "        raise",
                "",
            ]
        ),
    )
    bad = unresolved_imports(full, "lambdas/handler_with_broad_try.py", TREE_MODULES)
    assert len(bad) == 1
    assert "totally_fake_module_inside_broad_try" in bad[0]


def test_synthetic_real_sibling_module_resolves(tmp_path):
    """Sanity check against false positives: a handler importing a module that IS
    in the bundle (using a real one, stats_core) must resolve cleanly."""
    full = _write(
        tmp_path,
        "good_handler.py",
        "import stats_core\n\n\ndef lambda_handler(event, context):\n    return {}\n",
    )
    bad = unresolved_imports(full, "lambdas/good_handler.py", TREE_MODULES)
    assert bad == []


def test_synthetic_cdk_only_with_no_sibling_dependency_is_flagged_as_stale(tmp_path):
    """I8's own logic, exercised directly: a handler marked cdk_only that only
    imports stdlib has no reason to need cdk_only — the annotation is stale."""
    full = _write(
        tmp_path,
        "no_deps_handler.py",
        "import json\nimport os\n\n\ndef lambda_handler(event, context):\n    return {}\n",
    )
    deps = _sibling_bundle_deps(full, "lambdas/no_deps_handler.py", TREE_MODULES)
    assert deps == set()


def test_synthetic_cdk_only_with_real_sibling_dependency_is_not_flagged(tmp_path):
    """Counterpart: a handler that genuinely imports a bundled sibling (stats_core)
    DOES have a reason to justify a cdk_only annotation."""
    full = _write(
        tmp_path,
        "real_deps_handler.py",
        "import stats_core\n\n\ndef lambda_handler(event, context):\n    return {}\n",
    )
    deps = _sibling_bundle_deps(full, "lambdas/real_deps_handler.py", TREE_MODULES)
    assert deps == {"stats_core"}


# ── Standalone runner ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import subprocess

    result = subprocess.run(["python3", "-m", "pytest", __file__, "-v", "--tb=short"], cwd=ROOT)
    sys.exit(result.returncode)
