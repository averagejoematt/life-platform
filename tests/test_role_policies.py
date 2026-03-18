"""
tests/test_role_policies.py — Static IAM policy linter for role_policies.py.

Validates structural correctness of every policy function without needing
AWS credentials or a deployed environment. Runs in the existing CI/CD
'test' job (Job 2) alongside test_shared_modules.py.

Rules enforced:
  R1  DDB read actions  → kms:Decrypt must be present
  R2  DDB write actions → kms:GenerateDataKey must be present
  R3  KMS resource must be the platform CMK ARN (no wildcards)
  R4  No wildcard (*) resource except on explicitly allowlisted actions
  R5  Secrets Manager resources must be scoped ARNs (no bare *)
  R6  Every policy list must be non-empty
  R7  No duplicate SIDs within a single policy

Run with:   python3 -m pytest tests/test_role_policies.py -v
Or directly: python3 tests/test_role_policies.py

v1.0.0 — 2026-03-11
"""

import sys
import os
import inspect
import types

# ── Add cdk/stacks/ to path ───────────────────────────────────────────────────
CDK_STACKS = os.path.join(os.path.dirname(__file__), "..", "cdk", "stacks")
sys.path.insert(0, os.path.abspath(CDK_STACKS))

# ── Stub aws_cdk so role_policies.py imports without CDK installed ────────────
class _PolicyStatement:
    """Minimal stub that captures the fields role_policies.py uses."""
    def __init__(self, sid="", actions=None, resources=None, **kwargs):
        self.sid = sid
        self.actions = list(actions or [])
        self.resources = list(resources or [])

_iam_stub = types.ModuleType("aws_cdk.aws_iam")
_iam_stub.PolicyStatement = _PolicyStatement

_cdk_stub = types.ModuleType("aws_cdk")
_cdk_stub.aws_iam = _iam_stub

sys.modules.setdefault("aws_cdk", _cdk_stub)
sys.modules["aws_cdk.aws_iam"] = _iam_stub

import role_policies as rp  # noqa — importable now

# ── Constants from role_policies ──────────────────────────────────────────────
KMS_KEY_ARN = rp.KMS_KEY_ARN
TABLE_ARN   = rp.TABLE_ARN

DDB_READ_ACTIONS  = {
    "dynamodb:getitem", "dynamodb:query", "dynamodb:scan", "dynamodb:batchgetitem",
}
DDB_WRITE_ACTIONS = {
    "dynamodb:putitem", "dynamodb:updateitem", "dynamodb:deleteitem", "dynamodb:batchwriteitem",
}

# Actions for which a wildcard (*) resource is genuinely required by AWS
WILDCARD_RESOURCE_ALLOWLIST = {
    "cloudwatch:putmetricdata",        # CloudWatch requires * — no resource-level support
    "ses:sendemail",                   # Canary SESAlert stmt uses * intentionally
    "xray:puttracesegments",           # X-Ray does not support resource-level restrictions
    "xray:puttelemetryrecords",        # X-Ray does not support resource-level restrictions
    "xray:getsamplingrules",           # X-Ray does not support resource-level restrictions
    "xray:getsamplingtargets",         # X-Ray does not support resource-level restrictions
    "secretsmanager:listsecrets",      # List operation — no resource-level support
    "lambda:listfunctions",            # List operation — no resource-level support
}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _all_policy_functions():
    """Return {name: fn} for every public function in role_policies."""
    return {
        name: obj
        for name, obj in inspect.getmembers(rp, inspect.isfunction)
        if not name.startswith("_")
    }


ALL_FUNCTIONS = _all_policy_functions()


def _actions(stmts):
    return {a.lower() for s in stmts for a in s.actions}


def _has_ddb_reads(stmts):
    return bool(_actions(stmts) & DDB_READ_ACTIONS)


def _has_ddb_writes(stmts):
    return bool(_actions(stmts) & DDB_WRITE_ACTIONS)


# ══════════════════════════════════════════════════════════════════════════════
# Tests — parametrised over every public function in role_policies
# ══════════════════════════════════════════════════════════════════════════════

import pytest  # noqa — imported after sys.path manipulation


@pytest.mark.parametrize("fn_name", sorted(ALL_FUNCTIONS))
def test_r1_ddb_read_requires_kms_decrypt(fn_name):
    """R1: Any policy with DDB read actions must include kms:Decrypt."""
    stmts = ALL_FUNCTIONS[fn_name]()
    if not _has_ddb_reads(stmts):
        pytest.skip("no DDB read actions")
    assert "kms:decrypt" in _actions(stmts), (
        f"{fn_name}(): has DDB read actions but is missing kms:Decrypt. "
        f"The life-platform table is CMK-encrypted — every GetItem/Query/Scan "
        f"will fail with AccessDeniedException without this permission. "
        f"Add: iam.PolicyStatement(sid='KMS', actions=['kms:Decrypt','kms:GenerateDataKey'], "
        f"resources=[KMS_KEY_ARN])"
    )


@pytest.mark.parametrize("fn_name", sorted(ALL_FUNCTIONS))
def test_r2_ddb_write_requires_kms_generate(fn_name):
    """R2: Any policy with DDB write actions must include kms:GenerateDataKey."""
    stmts = ALL_FUNCTIONS[fn_name]()
    if not _has_ddb_writes(stmts):
        pytest.skip("no DDB write actions")
    assert "kms:generatedatakey" in _actions(stmts), (
        f"{fn_name}(): has DDB write actions but is missing kms:GenerateDataKey. "
        f"PutItem/UpdateItem/DeleteItem on a CMK-encrypted table requires this permission."
    )


@pytest.mark.parametrize("fn_name", sorted(ALL_FUNCTIONS))
def test_r3_kms_resource_is_scoped(fn_name):
    """R3: KMS statements must target the platform CMK ARN — no wildcards."""
    stmts = ALL_FUNCTIONS[fn_name]()
    for s in stmts:
        if not ({a.lower() for a in s.actions} & {"kms:decrypt", "kms:generatedatakey"}):
            continue
        for resource in s.resources:
            assert resource != "*", (
                f"{fn_name}(): KMS statement (sid={s.sid!r}) uses wildcard resource '*'. "
                f"Scope to KMS_KEY_ARN: {KMS_KEY_ARN}"
            )
            assert resource == KMS_KEY_ARN, (
                f"{fn_name}(): KMS statement (sid={s.sid!r}) targets unexpected ARN "
                f"{resource!r}. Expected {KMS_KEY_ARN}"
            )


@pytest.mark.parametrize("fn_name", sorted(ALL_FUNCTIONS))
def test_r4_no_unexpected_wildcard_resources(fn_name):
    """R4: Wildcard (*) resources only permitted for explicitly allowlisted actions."""
    stmts = ALL_FUNCTIONS[fn_name]()
    violations = []
    for s in stmts:
        if "*" not in s.resources:
            continue
        non_allowlisted = [
            a for a in s.actions
            if a.lower() not in WILDCARD_RESOURCE_ALLOWLIST
        ]
        if non_allowlisted:
            violations.append(f"sid={s.sid!r}, actions={non_allowlisted}")
    assert not violations, (
        f"{fn_name}(): wildcard resource '*' on non-allowlisted actions:\n  " +
        "\n  ".join(violations) + "\n"
        f"Allowlisted wildcard actions: {sorted(WILDCARD_RESOURCE_ALLOWLIST)}\n"
        f"Scope these to specific ARNs."
    )


@pytest.mark.parametrize("fn_name", sorted(ALL_FUNCTIONS))
def test_r5_secrets_resources_are_scoped(fn_name):
    """R5: Secrets Manager statements must use scoped ARNs, not '*'."""
    stmts = ALL_FUNCTIONS[fn_name]()
    secrets_actions = {
        "secretsmanager:getsecretvalue", "secretsmanager:putsecretvalue",
        "secretsmanager:updatesecret", "secretsmanager:describesecret",
        "secretsmanager:rotatescret",
    }
    for s in stmts:
        if not ({a.lower() for a in s.actions} & secrets_actions):
            continue
        for resource in s.resources:
            assert resource != "*", (
                f"{fn_name}(): Secrets Manager statement (sid={s.sid!r}) uses wildcard "
                f"resource '*'. Scope to specific secret ARNs using _secret_arn()."
            )


@pytest.mark.parametrize("fn_name", sorted(ALL_FUNCTIONS))
def test_r6_policy_is_non_empty(fn_name):
    """R6: Every policy function must return a non-empty list of statements."""
    stmts = ALL_FUNCTIONS[fn_name]()
    assert isinstance(stmts, list), f"{fn_name}() must return a list, got {type(stmts)}"
    assert len(stmts) > 0, f"{fn_name}() returned an empty policy — missing all permissions?"


@pytest.mark.parametrize("fn_name", sorted(ALL_FUNCTIONS))
def test_r7_no_duplicate_sids(fn_name):
    """R7: SID values must be unique within a single policy's statements."""
    stmts = ALL_FUNCTIONS[fn_name]()
    sids = [s.sid for s in stmts if s.sid]
    seen, dupes = set(), []
    for sid in sids:
        if sid in seen:
            dupes.append(sid)
        seen.add(sid)
    assert not dupes, (
        f"{fn_name}(): duplicate SIDs: {dupes}. "
        f"Each statement in a policy must have a unique SID."
    )


# ══════════════════════════════════════════════════════════════════════════════
# Standalone runner
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import subprocess
    result = subprocess.run(
        ["python3", "-m", "pytest", __file__, "-v", "--tb=short"],
        cwd=os.path.join(os.path.dirname(__file__), ".."),
    )
    sys.exit(result.returncode)
