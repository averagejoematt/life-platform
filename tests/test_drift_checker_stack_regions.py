"""Parity test (#1817): cdk/app.py's per-stack regions vs. the two hand-maintained
region maps that must track it —
  * deploy/check_lambda_config_drift.py::STACK_FILE_REGION (keyed by stack file)
  * deploy/drift_sentinel.py::STACKS (keyed by CFN stack name)

Both maps exist because CDK's per-stack `cdk.Environment(region=...)` isn't otherwise
introspectable offline — today only WebStack deploys outside the default region
(us-east-1, required for CloudFront). If a future stack is created with a non-default
region without updating BOTH maps, that stack's Lambdas get checked against the wrong
region — reproducing, undetected, the false-positive class the #1816-adjacent
region-aware fix (STACK_FILE_REGION itself) just solved.

Mirrors tests/test_lambda_map_regions.py's declared-vs-actual parity approach, except
here the "actual" side is cdk/app.py's own source (AST-parsed offline, no AWS needed)
rather than a live AWS inventory — read that file first for the pattern this borrows.
"""

import ast
import os
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_APP_PY = os.path.join(_ROOT, "cdk", "app.py")

for _p in (os.path.join(_ROOT, "deploy"),):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import check_lambda_config_drift as clcd  # noqa: E402
import drift_sentinel as ds  # noqa: E402


def _literal_str(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _parse_default_region(tree):
    """Extract the `"us-west-2"` fallback from
    `region = app.node.try_get_context("region") or "us-west-2"` rather than
    hardcoding it, so a future change to that literal doesn't silently desync
    this test from the source it's supposed to be checking."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            if isinstance(target, ast.Name) and target.id == "region":
                value = node.value
                if isinstance(value, ast.BoolOp) and isinstance(value.op, ast.Or):
                    for v in value.values:
                        lit = _literal_str(v)
                        if lit is not None:
                            return lit
    return "us-west-2"


def _parse_app_stacks():
    """AST-parse cdk/app.py: for every `<StackClass>(app, "<CfnName>", ..., env=...)`
    call, resolve (module_file, cfn_stack_name, region).

    `region` is the string literal explicitly passed to `cdk.Environment(region=...)`
    if present (WebStack today), else the module's own context-derived default (every
    other stack, via the shared `env` variable).

    Returns (default_region, [(module_file, cfn_stack_name, region), ...]).
    """
    with open(_APP_PY, encoding="utf-8") as f:
        tree = ast.parse(f.read(), filename="app.py")

    default_region = _parse_default_region(tree)

    # ClassName -> "web_stack.py", from `from stacks.web_stack import WebStack`.
    class_to_file = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("stacks."):
            module_file = node.module.split(".")[-1] + ".py"
            for alias in node.names:
                class_to_file[alias.name] = module_file

    stacks = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        cls_name = fn.id if isinstance(fn, ast.Name) else None
        if cls_name not in class_to_file:
            continue
        if len(node.args) < 2:
            continue
        cfn_name = _literal_str(node.args[1])
        if cfn_name is None:
            continue
        region = default_region
        for kw in node.keywords:
            if kw.arg != "env":
                continue
            env_expr = kw.value
            # env=cdk.Environment(..., region="us-east-1") — explicit override.
            # env=env (the shared default Environment) leaves `region` unchanged.
            if isinstance(env_expr, ast.Call):
                for env_kw in env_expr.keywords:
                    if env_kw.arg == "region":
                        lit = _literal_str(env_kw.value)
                        if lit is not None:
                            region = lit
        stacks.append((class_to_file[cls_name], cfn_name, region))
    return default_region, stacks


@pytest.fixture(scope="module")
def app_regions():
    default_region, stacks = _parse_app_stacks()
    assert stacks, "AST parse of cdk/app.py found zero stack instantiations — parser likely broken"
    return default_region, stacks


def test_app_py_has_a_non_default_region_stack(app_regions):
    """Sanity-check the parser actually resolves the known WebStack override — if this
    goes empty (e.g. app.py's constructor shape changes), the parity assertions below
    would pass vacuously and this whole test file stops doing its job."""
    default_region, stacks = app_regions
    non_default = [s for s in stacks if s[2] != default_region]
    assert non_default, "expected at least one non-default-region stack (WebStack/us-east-1) — AST parse regressed"


def test_stack_file_region_parity_with_app_py(app_regions):
    """Every non-default-region stack file declared in cdk/app.py must be a key in
    check_lambda_config_drift.STACK_FILE_REGION with the matching region."""
    default_region, stacks = app_regions
    missing = []
    mismatched = []
    for module_file, _cfn_name, region in stacks:
        if region == default_region:
            continue
        declared = clcd.STACK_FILE_REGION.get(module_file)
        if declared is None:
            missing.append(f"{module_file}: app.py says region={region!r}, STACK_FILE_REGION has no entry")
        elif declared != region:
            mismatched.append(f"{module_file}: app.py says region={region!r}, STACK_FILE_REGION says {declared!r}")
    problems = missing + mismatched
    assert not problems, "check_lambda_config_drift.STACK_FILE_REGION drifted from cdk/app.py:\n  " + "\n  ".join(problems)


def test_stack_file_region_has_no_stale_entries(app_regions):
    """Reverse direction: a STACK_FILE_REGION entry for a file app.py no longer builds
    with a non-default region is stale, and would silently mask a REAL future region
    change on that file being missed here (a stale entry reads as "covered")."""
    default_region, stacks = app_regions
    non_default_files = {module_file for module_file, _c, region in stacks if region != default_region}
    stale = sorted(f for f in clcd.STACK_FILE_REGION if f not in non_default_files)
    assert not stale, f"check_lambda_config_drift.STACK_FILE_REGION has stale entries not backed by app.py: {stale}"


def test_drift_sentinel_stacks_parity_with_app_py(app_regions):
    """Every stack built in cdk/app.py must be a key in drift_sentinel.STACKS with the
    matching region. Unlike STACK_FILE_REGION (override-only), drift_sentinel.STACKS
    covers all 9 stacks by CFN name, so this checks full parity, not just the
    non-default subset."""
    _default_region, stacks = app_regions
    missing = []
    mismatched = []
    for _module_file, cfn_name, region in stacks:
        declared = ds.STACKS.get(cfn_name)
        if declared is None:
            missing.append(f"{cfn_name}: app.py builds it with region={region!r}, drift_sentinel.STACKS has no entry")
        elif declared != region:
            mismatched.append(f"{cfn_name}: app.py says region={region!r}, drift_sentinel.STACKS says {declared!r}")
    problems = missing + mismatched
    assert not problems, "drift_sentinel.STACKS drifted from cdk/app.py:\n  " + "\n  ".join(problems)


def test_drift_sentinel_stacks_has_no_stale_entries(app_regions):
    _default_region, stacks = app_regions
    app_names = {cfn_name for _f, cfn_name, _r in stacks}
    stale = sorted(name for name in ds.STACKS if name not in app_names)
    assert not stale, f"drift_sentinel.STACKS has stale entries not backed by app.py: {stale}"
