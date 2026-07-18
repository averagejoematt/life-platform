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
import os
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
    fn = getattr(rp, fn_name, None)
    if fn is None:
        return False
    try:
        stmts = fn()
    except TypeError:
        # role_policies function that requires args — none of the emitters map
        # to one, so treat as unresolved (surfaces via the unresolved check).
        return False
    return any("cloudwatch:PutMetricData" in _statement_actions(s) for s in stmts)


def _build_source_to_rp_map() -> dict:
    """source_file → set(role_policies fn names) from every create_platform_lambda."""
    mapping: dict[str, set] = {}
    for stack in glob.glob(os.path.join(_REPO, "cdk", "stacks", "*.py")):
        with open(stack, encoding="utf-8") as f:
            tree = ast.parse(f.read())
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and getattr(node.func, "id", None) == "create_platform_lambda"):
                continue
            source_file = None
            rp_fns: set = set()
            for kw in node.keywords:
                if kw.arg == "source_file" and isinstance(kw.value, ast.Constant):
                    source_file = kw.value.value
                if kw.arg == "custom_policies":
                    for call in ast.walk(kw.value):
                        if (
                            isinstance(call, ast.Call)
                            and isinstance(call.func, ast.Attribute)
                            and isinstance(call.func.value, ast.Name)
                            and call.func.value.id == "rp"
                        ):
                            rp_fns.add(call.func.attr)
            if source_file:
                mapping.setdefault(source_file, set()).update(rp_fns)
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
