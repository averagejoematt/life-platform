"""Tests for #794 (R22-DEBT-01) — site-api's "dual ownership" resolution.

Ground truth established while fixing #794: `deploy/deploy_site_api.sh` was
ALREADY converted to stage through `deploy/build_bundle.py` in the #781/#833
layer-retirement PR (ADR-131) — it no longer hand-curates a `web/` + `reading/`
+ `methods_registry.py` zip. What was still wrong: stale comments (in
`cdk/stacks/operational_stack.py` and ADR-112 in `docs/DECISIONS.md`) kept
describing site-api as "script-managed, not CDK" and referencing a shared
Lambda layer that no longer exists, understating that CDK owns the function's
infrastructure (role/env/alarms) while the script is just the fast hot-deploy
code path — and BOTH now ship the identical package via the one bundle
channel, `deploy/build_bundle.py`.

These tests are cheap and deterministic (no AWS creds, no zip-diff): they
parse script/stack source text and actually invoke `build_bundle.stage_tree()`
into a scratch directory to assert the staged layout still contains every
module the old curated site-api zip used to hand-pick. They exist to catch a
regression where either channel drifts back to building its own package.
"""

import ast
import os
import sys

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DEPLOY_DIR = os.path.join(REPO_ROOT, "deploy")
CDK_STACKS_DIR = os.path.join(REPO_ROOT, "cdk", "stacks")

sys.path.insert(0, DEPLOY_DIR)
import build_bundle  # noqa: E402


def _read(*parts):
    with open(os.path.join(REPO_ROOT, *parts)) as f:
        return f.read()


# ══════════════════════════════════════════════════════════════════════════
# 1. Both deploy channels stage through the ONE bundle implementation.
# ══════════════════════════════════════════════════════════════════════════


def test_deploy_site_api_stages_via_build_bundle():
    """deploy_site_api.sh must invoke build_bundle.py, not hand-curate a zip."""
    script = _read("deploy", "deploy_site_api.sh")
    assert "build_bundle.py" in script, "deploy_site_api.sh no longer stages via the one bundle channel (#781/#794)"
    # Guard against a regression back to a hand-curated zip of specific dirs
    # (the pre-#781 shape: `zip -r ... web/ reading/ methods_registry.py`).
    assert "zip -r" not in script, "deploy_site_api.sh appears to hand-build a zip again instead of using build_bundle.py"


def test_deploy_lambda_and_fleet_also_stage_via_build_bundle():
    """The other two hot-deploy paths share the same channel (regression guard)."""
    for script_name in ("deploy_lambda.sh", "deploy_fleet.sh"):
        script = _read("deploy", script_name)
        assert "build_bundle.py" in script, f"{script_name} no longer stages via deploy/build_bundle.py"


def test_cdk_lambda_helpers_uses_build_bundle_for_default_asset():
    """CDK's default Lambda code asset must come from the same staging module."""
    helpers = _read("cdk", "stacks", "lambda_helpers.py")
    assert "import build_bundle" in helpers
    assert "build_bundle.stage_tree" in helpers


# ══════════════════════════════════════════════════════════════════════════
# 2. site-api's CDK definition doesn't override the shared bundle asset.
# ══════════════════════════════════════════════════════════════════════════


def _create_platform_lambda_calls_for(function_names):
    """AST-parse serve_stack.py (#793: the serving lambdas moved out of
    operational_stack); return {function_name: keyword-arg-names} for each
    create_platform_lambda(...) call whose function_name matches."""
    src = _read("cdk", "stacks", "serve_stack.py")
    tree = ast.parse(src, filename="serve_stack.py")
    found = {}
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "create_platform_lambda"):
            continue
        kwargs = {kw.arg: kw for kw in node.keywords if kw.arg is not None}
        fn_kw = kwargs.get("function_name")
        if fn_kw is None or not isinstance(fn_kw.value, ast.Constant):
            continue
        name = fn_kw.value.value
        if name in function_names:
            found[name] = set(kwargs.keys())
    return found


def test_site_api_lambdas_use_default_shared_bundle_asset():
    """Neither life-platform-site-api nor -site-api-ai passes a `code=` override —
    both must fall through to lambda_helpers.staged_tree_asset() (the same
    build_bundle.py output deploy_site_api.sh ships)."""
    calls = _create_platform_lambda_calls_for({"life-platform-site-api", "life-platform-site-api-ai"})
    assert set(calls) == {
        "life-platform-site-api",
        "life-platform-site-api-ai",
    }, f"Expected both site-api Lambda definitions in serve_stack.py, found: {sorted(calls)}"
    for name, kwarg_names in calls.items():
        assert "code" not in kwarg_names, (
            f"{name}'s create_platform_lambda() call now passes code= — this would let CDK ship a "
            "different package than deploy_site_api.sh, reopening the #794 dual-ownership gap."
        )


# ══════════════════════════════════════════════════════════════════════════
# 3. The staged bundle actually contains what the old curated site-api zip did.
# ══════════════════════════════════════════════════════════════════════════


def test_staged_bundle_contains_the_modules_site_api_needs(tmp_path):
    """Structural layout-equivalence check: build_bundle.stage_tree() must
    still contain web/ (site_api_lambda.py + friends), reading/ (imported by
    web/reading endpoints), and methods_registry.py at the bundle root — the
    exact set the pre-#781 deploy_site_api.sh used to hand-curate."""
    out = build_bundle.stage_tree(str(tmp_path / "stage"))

    must_exist = [
        os.path.join("web", "site_api_lambda.py"),
        os.path.join("web", "site_api_ai_lambda.py"),
        os.path.join("reading", "__init__.py"),
        "methods_registry.py",
    ]
    for rel in must_exist:
        full = os.path.join(out, rel)
        assert os.path.isfile(full), f"staged bundle is missing {rel} — site-api's package layout has drifted"


# ══════════════════════════════════════════════════════════════════════════
# 4. No stale "site-api is script-managed, not CDK" ownership claim survives.
# ══════════════════════════════════════════════════════════════════════════


def test_no_stale_site_api_sole_ownership_claims():
    """Guard against the exact false claim #794 was filed against re-appearing:
    that site-api has only one owner, or that a Lambda layer is attached to it
    (the shared layer was retired fleet-wide by #781/ADR-131)."""
    haystacks = {
        "deploy/deploy_site_api.sh": _read("deploy", "deploy_site_api.sh"),
        "cdk/stacks/operational_stack.py": _read("cdk", "stacks", "operational_stack.py"),
        "cdk/stacks/serve_stack.py": _read("cdk", "stacks", "serve_stack.py"),
        "docs/DECISIONS.md": _read("docs", "DECISIONS.md"),
    }
    banned_phrases = [
        "site-api is NOT CDK-managed",
        "site-api is script-managed, not CDK",
    ]
    for path, text in haystacks.items():
        for phrase in banned_phrases:
            assert phrase not in text, f"{path} still contains the stale sole-ownership claim: {phrase!r}"
