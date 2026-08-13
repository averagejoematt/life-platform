"""tests/test_put_metric_data_grant_lockstep.py — #1196 regression guard.

Turns the reference_iam_parity_codified_broken_state lesson ("repo == live IAM
both match while the capability is dead") into a CI gate for one specific,
thrice-repeated failure class: a Lambda handler that calls
``cloudwatch.put_metric_data`` at runtime while its CDK role never granted
``cloudwatch:PutMetricData``. The emit is caught fail-soft (a WARNING), so the
telemetry silently never lands and any alarm built on that metric can never
clear. It has now bitten four handlers:
  - ai-expert-analyzer      (fixed — needs_ai_keys grant)
  - coach-state-updater     (fixed — explicit CloudWatchMetrics statement)
  - coach-prediction-evaluator (#1196 — this change)
  - site-api-ai             (#1196 — found by THIS gate on its first run)

The guard is fully DERIVED (no hand-maintained baseline to drift):
  1. AST-scan every cdk/stacks/*.py create_platform_lambda(...) call to map each
     wired ``source_file="lambdas/..."`` → the ``custom_policies=rp.<fn>()``
     function(s) that build its role.
  2. Find the emitters: those source files whose code actually calls
     ``.put_metric_data(``.
  3. For each emitting handler, resolve its role_policies function(s) and assert
     the built PolicyStatements include ``cloudwatch:PutMetricData``. An
     ungranted emitter fails CI at PR time — before it ships another silently
     dead metric.

Shared modules that emit (ai_calls / bedrock_client / retry_utils / …) are NOT
wired as a source_file; they ride inside every bundle and their emits only fire
on the AI code path, which is granted via ``needs_ai_keys`` on the host role.
This gate deliberately scopes to wired handlers that emit directly — the exact
shape of all four incidents.
"""

import ast
import glob
import importlib
import os
import pathlib
import re
import sys
import types

# ── Add cdk/ and cdk/stacks/ to path + stub aws_cdk (same pattern as
#    tests/test_role_policies.py) so role_policies.py imports with no CDK dep. ──
_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "cdk"))
sys.path.insert(0, os.path.join(_REPO, "cdk", "stacks"))


class _PolicyStatement:
    def __init__(self, sid="", actions=None, resources=None, **kwargs):
        self.sid = sid
        self.actions = list(actions or [])
        self.resources = list(resources or [])


_iam_stub = types.ModuleType("aws_cdk.aws_iam")
_iam_stub.PolicyStatement = _PolicyStatement
_cdk_stub = types.ModuleType("aws_cdk")
_cdk_stub.aws_iam = _iam_stub
sys.modules.setdefault("aws_cdk", _cdk_stub)
sys.modules.setdefault("aws_cdk.aws_iam", _iam_stub)

import role_policies as rp  # noqa: E402

# #2611: resolve policy functions across the WHOLE `role_policies*` family, not just the
# facade. `role_policies.py` re-exports the #2604 domain siblings but deliberately does NOT
# re-export `role_policies_permanence.operational_permanence` (#1400) — a bare
# `getattr(rp, ...)` reports that role as "no grant" rather than as "not found". Derived by
# glob so a ninth sibling is covered the day it lands.
_POLICY_MODULES = [rp] + [importlib.import_module(p.stem) for p in sorted(pathlib.Path(_REPO, "cdk", "stacks").glob("role_policies_*.py"))]


def _resolve_policy_fn(fn_name: str):
    for mod in _POLICY_MODULES:
        fn = getattr(mod, fn_name, None)
        if fn is not None:
            return fn
    return None


def _statement_actions(stmt):
    """Actions from a built statement — works for the stub AND real CDK."""
    acts = getattr(stmt, "actions", None)
    if acts is not None:
        return list(acts)
    try:
        j = stmt.to_json()  # real aws_cdk PolicyStatement
        act = j.get("Action", [])
        return act if isinstance(act, list) else [act]
    except Exception:
        return []


def _rp_grants_put_metric_data(fn_name: str) -> bool:
    fn = _resolve_policy_fn(fn_name)
    if fn is None:
        return False
    try:
        stmts = fn()
    except TypeError:
        # role_policies function that requires args — none of the emitters map
        # to one, so treat as unresolved (surfaces via the unresolved check).
        return False
    return any("cloudwatch:PutMetricData" in _statement_actions(s) for s in stmts)


def _policy_aliases(tree) -> set:
    """Local names this stack module binds to a `role_policies*` module.

    #2611: this used to be the hardcoded literal `"rp"`. `operational_stack.py` imports
    `role_policies_permanence as rpp` (#1400), so the Permanence Lambda's `custom_policies`
    resolved to the empty set and sat outside the lockstep. It failed loud rather than
    silent (the resolver guard below catches an emitting handler with no resolved role), but
    the alias set is derived from the module's own imports now — a stack that imports a
    #2604 sibling under any name is covered without editing this file.
    """
    aliases = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            for a in node.names:
                if a.name.startswith("role_policies"):
                    aliases.add(a.asname or a.name)
        elif isinstance(node, ast.Import):
            for a in node.names:
                mod = a.name.rsplit(".", 1)[-1]
                if mod.startswith("role_policies"):
                    aliases.add(a.asname or mod)
    return aliases


# Wired handlers that actually pass a `custom_policies=` kwarg. A Lambda may legitimately
# be wired without one (it just rides the base role), so the #2611 alias guard below scopes
# to this set rather than to every wired handler.
HAS_CUSTOM_POLICIES: set = set()


def _build_source_to_rp_map() -> dict:
    """source_file → set(role_policies fn names) from every create_platform_lambda."""
    mapping: dict[str, set] = {}
    for stack in glob.glob(os.path.join(_REPO, "cdk", "stacks", "*.py")):
        with open(stack, encoding="utf-8") as f:
            tree = ast.parse(f.read())
        aliases = _policy_aliases(tree)
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and getattr(node.func, "id", None) == "create_platform_lambda"):
                continue
            source_file = None
            rp_fns: set = set()
            has_custom_policies = False
            for kw in node.keywords:
                if kw.arg == "source_file" and isinstance(kw.value, ast.Constant):
                    source_file = kw.value.value
                if kw.arg == "custom_policies":
                    has_custom_policies = True
                    for call in ast.walk(kw.value):
                        if (
                            isinstance(call, ast.Call)
                            and isinstance(call.func, ast.Attribute)
                            and isinstance(call.func.value, ast.Name)
                            and call.func.value.id in aliases
                        ):
                            rp_fns.add(call.func.attr)
            if source_file:
                mapping.setdefault(source_file, set()).update(rp_fns)
                if has_custom_policies:
                    HAS_CUSTOM_POLICIES.add(source_file)
    return mapping


def _emits_put_metric_data(source_file: str) -> bool:
    path = os.path.join(_REPO, source_file)
    if not os.path.isfile(path):
        return False
    with open(path, encoding="utf-8") as f:
        return bool(re.search(r"\.put_metric_data\s*\(", f.read()))


_SOURCE_TO_RP = _build_source_to_rp_map()
# Every wired handler that actually emits a CloudWatch metric.
_EMITTER_HANDLERS = {sf: fns for sf, fns in _SOURCE_TO_RP.items() if _emits_put_metric_data(sf)}


def test_every_emitting_handler_role_grants_put_metric_data():
    """The lockstep: a handler that calls put_metric_data must ride a role that
    grants cloudwatch:PutMetricData. Fails listing any ungranted (handler, role)."""
    ungranted = []
    for source_file, rp_fns in sorted(_EMITTER_HANDLERS.items()):
        for fn_name in sorted(rp_fns):
            if not _rp_grants_put_metric_data(fn_name):
                ungranted.append(f"{source_file} → rp.{fn_name}()")
    assert not ungranted, (
        "These Lambda handlers call cloudwatch.put_metric_data but their role_policies "
        "function does not grant cloudwatch:PutMetricData (the emit will fail AccessDenied, "
        "fail-soft, and the metric/alarm goes dead — see reference_iam_parity_codified_broken_state):\n  " + "\n  ".join(ungranted)
    )


def test_every_emitting_handler_resolves_to_a_role():
    """Guard the guard: an emitting handler wired with a custom_policies form this
    test can't resolve to an rp function would silently escape the lockstep. Fail
    loudly so the resolver gets extended rather than the emitter slipping through."""
    unresolved = [sf for sf, fns in _EMITTER_HANDLERS.items() if not fns]
    assert not unresolved, (
        "These emitting handlers are wired via create_platform_lambda but their "
        "custom_policies did not resolve to a role_policies rp.<fn>() call — extend "
        "_build_source_to_rp_map so they are covered by the PutMetricData lockstep:\n  " + "\n  ".join(sorted(unresolved))
    )


def test_gate_is_non_vacuous():
    """A green run must mean the scan actually found and checked emitters — not that
    the map came back empty. Pins the #1196 subject + a healthy floor of coverage."""
    assert len(_EMITTER_HANDLERS) >= 10, f"expected many emitting handlers, found {len(_EMITTER_HANDLERS)} — resolver likely broke"
    evaluator = "lambdas/coach/coach_prediction_evaluator.py"
    assert evaluator in _EMITTER_HANDLERS, f"{evaluator} not detected as an emitting handler — the #1196 subject must be in scope"
    assert "compute_coach_prediction_evaluator" in _EMITTER_HANDLERS[evaluator]


def test_every_wired_lambda_resolves_its_policy_alias():
    """#2611: the resolver must cover EVERY wired handler, not only the emitting ones.

    `_EMITTER_HANDLERS` filters to handlers that call put_metric_data today, so a stack
    importing a `role_policies*` sibling under a non-`rp` alias stayed invisible until the
    day its handler started emitting. Assert the whole wired set resolves, so the alias
    blindness is caught when it is introduced rather than when it finally matters.
    """
    assert HAS_CUSTOM_POLICIES, "no create_platform_lambda passes custom_policies — the scan broke"
    unresolved = sorted(sf for sf in HAS_CUSTOM_POLICIES if not _SOURCE_TO_RP.get(sf))
    assert not unresolved, (
        "These create_platform_lambda calls pass custom_policies that did not resolve to any "
        "`role_policies*` module alias — extend _policy_aliases:\n  " + "\n  ".join(unresolved)
    )


def test_the_non_rp_alias_is_actually_exercised():
    """Mutation canary: prove the derived-alias code path has a live subject.

    If every stack ever settles on the bare `rp` alias, `_policy_aliases` becomes
    indistinguishable from the old hardcoded literal and this guard should be re-read
    rather than silently kept.
    """
    permanence = "lambdas/operational/permanence_lambda.py"
    assert permanence in _SOURCE_TO_RP, f"{permanence} is no longer wired — re-check the #2611 alias guard"
    assert _SOURCE_TO_RP[permanence] == {"operational_permanence"}, _SOURCE_TO_RP[permanence]
    # …and the function it names resolves off the sibling, not the facade.
    assert getattr(rp, "operational_permanence", None) is None, "the facade now re-exports it — simplify _resolve_policy_fn"
    assert _resolve_policy_fn("operational_permanence") is not None
