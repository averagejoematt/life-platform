"""tests/test_key_rotator_grants_4707.py — every Secrets Manager call a rotation Lambda makes is granted (#4707).

The defect: `life-platform-key-rotator` passed createSecret/setSecret/testSecret and then
failed finishSecret on every retry of the 2026-10 rotation of `life-platform/mcp-api-key`,
with `AccessDeniedException ... secretsmanager:UpdateSecretVersionStage`. The CDK statement in
`operational_key_rotator()` granted four actions; the code calls five. The grant was dropped on
2026-03-10 (d2f996914 rebuilt the function after 385894fbb truncated role_policies.py) and
nothing compared the code's calls with the role, so a rotation that fires once every 90 days
carried the gap for seven months.

The SET guarded here, not the one action:
  A. every Lambda under `lambdas/` that implements the Secrets Manager rotation protocol
     (it handles the `finishSecret` step) is registered in ROTATION_LAMBDAS with its
     policy function and the secret it rotates — a new rotator cannot land unguarded;
  B. for each one, every `<client>.<method>(...)` call on a `boto3.client("secretsmanager")`
     handle is mapped through botocore's own service model to its API operation, and that
     `secretsmanager:<Operation>` must be granted by a statement in the policy function whose
     resource covers the rotated secret.

`grant_enumeration` (tests/test_grant_enumeration_drift.py) does not cover this: it checks that
a reachable secret NAME is readable, and the rotator's secret id arrives in the event payload, so
that sweep exempts it by design (its `secret:...key_rotator_lambda.*` entries).

Both sides are read with `ast`, not imported — no aws_cdk stub, no AWS credentials.

Run:  python3 -m pytest tests/test_key_rotator_grants_4707.py -v
"""

from __future__ import annotations

import ast
import pathlib

import pytest
from botocore import xform_name
from botocore.session import get_session

REPO = pathlib.Path(__file__).resolve().parent.parent

# rotation Lambda source -> (policy module, policy function, rotated secret name)
ROTATION_LAMBDAS = {
    "lambdas/operational/key_rotator_lambda.py": (
        "cdk/stacks/role_policies_operational.py",
        "operational_key_rotator",
        "life-platform/mcp-api-key",
    ),
}

ROTATION_STEP_MARKER = "finishSecret"


def _sm_operations() -> dict:
    """boto3 snake_case method name -> Secrets Manager API operation name, from botocore's model."""
    model = get_session().get_service_model("secretsmanager")
    return {xform_name(op): op for op in model.operation_names}


def sm_client_methods(source: str) -> set:
    """Every method called on a name bound to `boto3.client("secretsmanager", ...)`.

    `sm.exceptions.X` is an attribute chain, not a call on the client, and is not an API call.
    """
    tree = ast.parse(source)
    clients = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
            call = node.value
            func = call.func
            is_client = isinstance(func, ast.Attribute) and func.attr == "client"
            first = call.args[0] if call.args else None
            if is_client and isinstance(first, ast.Constant) and first.value == "secretsmanager":
                clients.update(t.id for t in node.targets if isinstance(t, ast.Name))
    methods = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            owner = node.func.value
            if isinstance(owner, ast.Name) and owner.id in clients:
                methods.add(node.func.attr)
    return methods


def granted_actions(policy_source: str, fn_name: str, secret: str) -> set:
    """Actions of every PolicyStatement in `fn_name` whose resources name `_secret_arn(secret)`."""
    tree = ast.parse(policy_source)
    fn = next((n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == fn_name), None)
    assert fn is not None, f"policy function {fn_name} not found"
    actions = set()
    for node in ast.walk(fn):
        if not (isinstance(node, ast.Call) and getattr(node.func, "attr", getattr(node.func, "id", None)) == "PolicyStatement"):
            continue
        kw = {k.arg: k.value for k in node.keywords}
        res = kw.get("resources")
        covers = False
        for r in ast.walk(res) if res is not None else []:
            if (
                isinstance(r, ast.Call)
                and getattr(r.func, "id", None) == "_secret_arn"
                and r.args
                and isinstance(r.args[0], ast.Constant)
                and r.args[0].value == secret
            ):
                covers = True
        if covers and isinstance(kw.get("actions"), ast.List):
            actions.update(e.value for e in kw["actions"].elts if isinstance(e, ast.Constant))
    return actions


def missing_grants(lambda_source: str, policy_source: str, fn_name: str, secret: str) -> list:
    ops = _sm_operations()
    needed = set()
    for method in sm_client_methods(lambda_source):
        assert method in ops, f"`{method}` is not a Secrets Manager client operation in botocore's model"
        needed.add(f"secretsmanager:{ops[method]}")
    return sorted(needed - granted_actions(policy_source, fn_name, secret))


def _read(rel: str) -> str:
    return (REPO / rel).read_text(encoding="utf-8")


def test_every_rotation_lambda_is_registered():
    found = sorted(
        str(p.relative_to(REPO)) for p in (REPO / "lambdas").rglob("*.py") if f'"{ROTATION_STEP_MARKER}"' in p.read_text(encoding="utf-8")
    )
    assert found == sorted(ROTATION_LAMBDAS), (
        "rotation Lambdas (handle the finishSecret step) must be registered in ROTATION_LAMBDAS "
        f"with their policy function and rotated secret: found {found}, registered {sorted(ROTATION_LAMBDAS)}"
    )


def test_every_secretsmanager_call_of_every_rotation_lambda_is_granted():
    offenders = []
    for src, (policy_file, fn_name, secret) in ROTATION_LAMBDAS.items():
        lambda_source = _read(src)
        methods = sm_client_methods(lambda_source)
        # The parser must actually see the rotation's calls, or an empty set would pass vacuously.
        if "update_secret_version_stage" not in methods or "put_secret_value" not in methods:
            offenders.append(f"{src}: parser found {sorted(methods)} — expected the rotation protocol's calls")
            continue
        missing = missing_grants(lambda_source, _read(policy_file), fn_name, secret)
        if missing:
            offenders.append(f"{src}: {fn_name}() on {secret} lacks {missing}")
    assert not offenders, "Secrets Manager calls with no IAM grant (#4707):\n  " + "\n  ".join(offenders)


# ── mutation proofs: the gate reds when the grant or the code drifts ─────────────────────────

_POLICY = """
def operational_key_rotator():
    return [
        iam.PolicyStatement(
            sid="Secrets",
            actions=[{actions}],
            resources=[_secret_arn("life-platform/mcp-api-key")],
        ),
    ]
"""

_LAMBDA = """
import boto3
sm = boto3.client("secretsmanager")
def finish(s, t):
    sm.describe_secret(SecretId=s)
    try:
        sm.get_secret_value(SecretId=s)
    except sm.exceptions.ResourceNotFoundException:
        pass
    sm.update_secret_version_stage(SecretId=s, VersionStage="AWSCURRENT", MoveToVersionId=t)
"""


def _policy(*actions: str) -> str:
    return _POLICY.format(actions=", ".join(f'"secretsmanager:{a}"' for a in actions))


def test_reds_when_update_secret_version_stage_is_not_granted():
    """The exact #4707 shape: the pre-fix four-action statement."""
    policy = _policy("GetSecretValue", "PutSecretValue", "UpdateSecret", "DescribeSecret")
    assert missing_grants(_LAMBDA, policy, "operational_key_rotator", "life-platform/mcp-api-key") == [
        "secretsmanager:UpdateSecretVersionStage"
    ]


def test_green_when_every_call_is_granted_and_exceptions_attr_is_not_a_call():
    policy = _policy("GetSecretValue", "DescribeSecret", "UpdateSecretVersionStage")
    assert missing_grants(_LAMBDA, policy, "operational_key_rotator", "life-platform/mcp-api-key") == []


def test_reds_when_the_grant_is_scoped_to_a_different_secret():
    policy = _policy("GetSecretValue", "DescribeSecret", "UpdateSecretVersionStage").replace(
        "life-platform/mcp-api-key", "life-platform/other"
    )
    assert len(missing_grants(_LAMBDA, policy, "operational_key_rotator", "life-platform/mcp-api-key")) == 3


def test_reds_when_the_code_gains_a_new_call():
    policy = _policy("GetSecretValue", "DescribeSecret", "UpdateSecretVersionStage")
    grown = _LAMBDA + "\n    sm.cancel_rotate_secret(SecretId=s)\n"
    assert missing_grants(grown, policy, "operational_key_rotator", "life-platform/mcp-api-key") == ["secretsmanager:CancelRotateSecret"]


def test_an_unknown_method_is_refused_not_silently_mapped():
    with pytest.raises(AssertionError, match="not a Secrets Manager client operation"):
        missing_grants(
            _LAMBDA + "\n    sm.not_an_operation()\n", _policy("GetSecretValue"), "operational_key_rotator", "life-platform/mcp-api-key"
        )
