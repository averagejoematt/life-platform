"""#3340 — the CDK cfn-exec permissions boundary: the braces under #2834's belt.

WHAT IS BEING GUARDED
  `cdk-hnb659fds-cfn-exec-role-<acct>-<region>` is what CloudFormation acts as. All three
  regional copies carry AdministratorAccess (CDK bootstrap default; read live, read-only,
  2026-08-31 — `PermissionsBoundary: None` on all three). `github-actions-deploy-role` has
  held `sts:AssumeRole` on `role/cdk-*` since #401, and since #2834 CI exercises that chain
  on every additive IAM grant. So a permissions boundary on those three roles is the only
  control that survives a bug in the gate's parser, a template it mis-slices, or a workflow
  edit that skips the step.

THE FIVE PRIMITIVES (docs/CHARTER.md) — where each one lives in this file
  registry          `deploy/iam_additive_registry.py` — the SAME module the additive gate
                    reads. `ENROLLED_IAM_PRINCIPALS` / `IAM_PROTECTED_PRINCIPALS` /
                    `boundary_protected_s3_prefixes()` are derived there, not forked here.
  derivation guard  `test_the_committed_json_equals_the_derivation` +
                    `test_the_derivation_hand_types_no_account_or_resource_literal` +
                    `test_the_enrolled_role_family_derives_from_cdk_app_stack_ids`
  ratchet           `test_the_registry_equals_the_baseline_the_adr_declares` — parsed from
                    the ```json cfn-exec-boundary-baseline``` fence in the ADR-065
                    amendment of 2026-08-31, the same R5 shape #2834 uses: a widening has
                    to appear where the OWNER reads, in the same PR.
  contract test     `test_the_policy_decides_every_probe_the_way_aws_did` — an offline IAM
                    evaluator run over the SAME probe set `--simulate` sends to AWS, whose
                    28/28 agreement with `iam:SimulateCustomPolicy` is recorded on the PR.
                    The live engine is the fixture; this is the wire.
  dead-man          `test_a_missing_boundary_reads_red` and siblings — `verify_oidc_iam`'s
                    new assertion is fed a role with no boundary, a role with the WRONG
                    boundary, a DRIFTED document and an AccessDenied, and every one of them
                    must produce a finding. A boundary nobody can read is never a pass.

No tree sweeping here on purpose: this file reads named files only, so it does not join
`tests/premerge_derivation.py`'s structural-gate family and mints no census gate.
"""

from __future__ import annotations

import fnmatch
import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "deploy"))
sys.path.insert(0, str(ROOT / "cdk"))

import derive_cfn_exec_boundary as boundary  # noqa: E402
import iam_additive_registry as reg  # noqa: E402
import verify_oidc_iam as verifier  # noqa: E402
from stacks import constants  # noqa: E402

pytestmark = pytest.mark.deploy_critical

DECISIONS = ROOT / "docs" / "DECISIONS.md"
IAM_README = ROOT / "infra" / "iam" / "README.md"
PROPORTIONALITY = ROOT / "docs" / "PROPORTIONALITY.md"
PROBE_DIR = ROOT / "infra" / "iam" / "boundary_probe"
_ADR_FENCE = re.compile(r"```json cfn-exec-boundary-baseline\n(.*?)\n```", re.S)


# ═══════════════════════════════════════════════════════════════════════════════
# An offline IAM evaluator — validated against AWS's own engine on the same probes
# ═══════════════════════════════════════════════════════════════════════════════
#
# `deploy/derive_cfn_exec_boundary.py --simulate` sends `simulation_probes()` to
# `iam:SimulateCustomPolicy` and prints AWS's verdicts (28/28 as expected, recorded on the
# PR, read-only). CI has no AWS credentials, so the same probe set is decided here by a
# small evaluator implementing exactly the subset of the policy language this document
# uses: Action / NotAction, Resource / NotResource, and one `StringNotEquals` condition on
# `aws:RequestedRegion`. If the two ever disagree, the recorded live run is the arbiter.
#
# ONE KNOWN DIVERGENCE CLASS, measured rather than assumed: this evaluator matches
# resources as strings and does NOT model action-to-resource-type applicability, while
# AWS's engine does — `iam:AttachRolePolicy` against a user/group/policy ARN reads
# `explicitDeny` here and `implicitDeny` there. Three probes disagreed for exactly that
# reason on the first live run, and the fix was in the PROBE (pick an action that suits
# the ARN type), not in either engine: a type-mismatched probe is a negative control that
# passes for the wrong reason. Both engines agree 33/33 on the shipped set.


def _matches(patterns, value: str) -> bool:
    if isinstance(patterns, str):
        patterns = [patterns]
    return any(fnmatch.fnmatch(value.lower(), p.lower()) for p in patterns)


def _condition_holds(statement: dict, region: str) -> bool:
    condition = statement.get("Condition")
    if not condition:
        return True
    assert set(condition) == {"StringNotEquals"}, f"evaluator does not model {sorted(condition)} — extend it or simplify the policy"
    values = condition["StringNotEquals"]
    assert set(values) == {"aws:RequestedRegion"}, sorted(values)
    return region not in values["aws:RequestedRegion"]


def _statement_applies(statement: dict, action: str, resource: str, region: str) -> bool:
    if "Action" in statement:
        if not _matches(statement["Action"], action):
            return False
    elif _matches(statement["NotAction"], action):
        return False
    if "Resource" in statement:
        if not _matches(statement["Resource"], resource):
            return False
    elif _matches(statement["NotResource"], resource):
        return False
    return _condition_holds(statement, region)


def evaluate(policy: dict, action: str, resource: str, region: str) -> str:
    """`allowed` / `explicitDeny` / `implicitDeny` — the three verdicts IAM reports."""
    allowed = False
    for statement in policy["Statement"]:
        if not _statement_applies(statement, action, resource, region):
            continue
        if statement["Effect"] == "Deny":
            return "explicitDeny"
        allowed = True
    return "allowed" if allowed else "implicitDeny"


def _policy() -> dict:
    return boundary.build_policy()


def _statement(sid: str) -> dict:
    for st in _policy()["Statement"]:
        if st.get("Sid") == sid:
            return st
    raise AssertionError(f"no statement with Sid {sid!r} — the boundary lost a clause")


# ═══════════════════════════════════════════════════════════════════════════════
# Derivation guard — the committed JSON is output, never a hand edit
# ═══════════════════════════════════════════════════════════════════════════════


def test_the_committed_json_equals_the_derivation():
    """The derivation-guard primitive. A hand edit to the JSON — or a registry change that
    was never re-rendered — reds here, in the same PR, not at apply time."""
    assert boundary.POLICY_PATH.exists(), f"{boundary.POLICY_PATH} is missing — run `python3 deploy/derive_cfn_exec_boundary.py --write`"
    assert boundary.committed() == _policy(), (
        "infra/iam/cdk-cfn-exec-boundary.boundary.json differs from its derivation. "
        "Regenerate with `python3 deploy/derive_cfn_exec_boundary.py --write` in the SAME PR."
    )
    # And the CLI says the same thing, so the operator's pre-apply check is the tested path.
    assert boundary.main.__module__ == "derive_cfn_exec_boundary"


def test_the_document_fits_inside_iams_managed_policy_limit():
    """6,144 characters, whitespace excluded. This is not a style rule: a document one byte
    over cannot be created at all, and the failure would land in the apply window."""
    compact = boundary.compact_size()
    assert compact <= boundary.MANAGED_POLICY_MAX_CHARS, f"{compact} chars > {boundary.MANAGED_POLICY_MAX_CHARS}"
    # Headroom, stated: a new protected prefix in deploy/bucket_policy.json costs ~48 chars,
    # and the render must not be one commit away from being un-appliable.
    assert boundary.MANAGED_POLICY_MAX_CHARS - compact >= 200, (
        f"only {boundary.MANAGED_POLICY_MAX_CHARS - compact} chars of headroom left — trim the document "
        "(or split a Deny out) before the next protected prefix lands"
    )


def test_the_derivation_hand_types_no_account_or_resource_literal():
    """The one way a derived document drifts is a copied literal. Refuse the copy."""
    src = (ROOT / "deploy" / "derive_cfn_exec_boundary.py").read_text(encoding="utf-8")
    # The same four-minus-one set `test_gate_source_hand_types_no_namespace_literal` uses:
    # `TABLE_NAME` is excluded there and here because it IS the platform slug
    # ("life-platform") and appears in prose about naming, where it is not a copied value.
    for literal in (constants.ACCT, constants.S3_BUCKET, constants.RAW_BACKUP_BUCKET, constants.KMS_KEY_ID):
        assert literal not in src, f"hand-typed {literal!r} in deploy/derive_cfn_exec_boundary.py — derive it from the registry"


def test_the_enrolled_role_family_derives_from_cdk_app_stack_ids__guard_the_set():
    """Both directions. Every stack CDK actually deploys must be able to mint its roles;
    a name outside the platform's families must not."""
    assert len(reg.CDK_STACK_NAMES) >= 8, reg.CDK_STACK_NAMES
    prefix = reg.CDK_STACK_NAME_PREFIX
    assert prefix and all(name.startswith(prefix) for name in reg.CDK_STACK_NAMES), reg.CDK_STACK_NAMES
    policy = _policy()
    for stack in reg.CDK_STACK_NAMES:
        arn = f"arn:aws:iam::{constants.ACCT}:role/{stack}-SomeConstructABC123-XyZ"
        assert evaluate(policy, "iam:CreateRole", arn, constants.REGION) == "allowed", stack
    # …and the roles constants.py names explicitly (the DIL-027 replication pair).
    for role in (constants.RAW_REPLICATION_ROLE_NAME, constants.RAW_BATCH_REPLICATION_ROLE_NAME):
        arn = f"arn:aws:iam::{constants.ACCT}:role/{role}"
        assert evaluate(policy, "iam:CreateRole", arn, constants.REGION) == "allowed", role
    # The mutation: a stack id that is not in cdk/app.py cannot mint a role.
    for outsider in ("boundary-probe-3340-EscalationRole", "SomeOtherApp-Role", "admin-backdoor"):
        arn = f"arn:aws:iam::{constants.ACCT}:role/{outsider}"
        assert evaluate(policy, "iam:CreateRole", arn, constants.REGION) == "explicitDeny", outsider


def test_the_protected_s3_prefixes_derive_from_the_bucket_policy_not_retyped():
    """Same derivation the additive gate uses (#3335 review R2): a prefix added to
    deploy/bucket_policy.json is fenced on the next render, and the equality test above is
    what turns 'next render' into a gate."""
    declared = json.loads((ROOT / "deploy" / "bucket_policy.json").read_text(encoding="utf-8"))
    from_file = set()
    for st in declared["Statement"]:
        if st.get("Effect") != "Deny":
            continue
        for res in st["Resource"] if isinstance(st["Resource"], list) else [st["Resource"]]:
            m = re.fullmatch(rf"arn:aws:s3:::{re.escape(constants.S3_BUCKET)}/(.+?)/\*", res)
            if m:
                from_file.add(m.group(1) + "/")
    assert from_file, "the bucket policy parse found no protected prefixes — the derivation is broken, not the policy"
    assert set(reg.boundary_protected_s3_prefixes()) == from_file
    # ADR-032/033/046's four named prefixes are in there, asserted by name so a parse that
    # silently returns a subset cannot pass.
    assert {"raw/", "config/", "uploads/", "generated/"} <= from_file


# ═══════════════════════════════════════════════════════════════════════════════
# Contract — the probe set, decided offline exactly as AWS decided it live
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.parametrize("action,resource,region,expected", boundary.simulation_probes())
def test_the_policy_decides_every_probe_the_way_aws_did(action, resource, region, expected):
    assert evaluate(_policy(), action, resource, region) == expected, f"{action} on {resource} in {region}"


def test_the_probe_set_carries_both_directions():
    """A negative control that is all negatives proves the fence is closed and nothing about
    whether the platform can still deploy through it."""
    verdicts = [p[3] for p in boundary.simulation_probes()]
    assert verdicts.count("explicitDeny") >= 10, verdicts
    assert verdicts.count("allowed") >= 10, verdicts


# The services the three cfn-exec roles have ACTUALLY used, from IAM Access Advisor
# (`generate-service-last-accessed-details` per role ARN, then `get-…`, read-only,
# 2026-08-31): the union across us-west-2 / us-east-1 / us-east-2. CloudTrail cannot
# answer this question — an assumed-role session logs under the session name, and
# `lookup-events --lookup-attributes Username=<role>` returns nothing.
#
# Each entry is one representative action the role must still be able to take. This is
# the "did the fence break the deploy" test, asked of measured evidence rather than
# imagination.
ACCESS_ADVISOR_SERVICES: dict[str, tuple[str, str, str]] = {
    "acm": ("acm:DescribeCertificate", "arn:aws:acm:us-east-1:{acct}:certificate/abc", "us-east-1"),
    "apigateway": ("apigateway:POST", "arn:aws:apigateway:us-west-2::/restapis", "us-west-2"),
    "batch": ("batch:DescribeJobQueues", "*", "us-west-2"),
    "budgets": ("budgets:ModifyBudget", "arn:aws:budgets::{acct}:budget/life-platform-monthly-75", "us-east-1"),
    "cloudformation": ("cloudformation:CreateChangeSet", "arn:aws:cloudformation:us-west-2:{acct}:stack/LifePlatformCore/*", "us-west-2"),
    "cloudfront": ("cloudfront:UpdateDistribution", "arn:aws:cloudfront::{acct}:distribution/E3S424OXQZ8NBE", "us-east-1"),
    "cloudwatch": ("cloudwatch:PutMetricAlarm", "arn:aws:cloudwatch:us-west-2:{acct}:alarm:life-platform-x", "us-west-2"),
    "codepipeline": ("codepipeline:GetPipeline", "*", "us-west-2"),
    "ec2": ("ec2:DescribeVpcs", "*", "us-east-1"),
    "events": ("events:PutTargets", "arn:aws:events:us-west-2:{acct}:rule/LifePlatformIngestion-Whoop", "us-west-2"),
    "iam": ("iam:CreateRole", "arn:aws:iam::{acct}:role/LifePlatformCore-SomeRole", "us-west-2"),
    "inspector": ("inspector:DescribeAssessmentRuns", "*", "us-west-2"),
    "kms": ("kms:DescribeKey", "arn:aws:kms:us-west-2:{acct}:key/abc", "us-west-2"),
    "lambda": ("lambda:CreateFunction", "arn:aws:lambda:us-west-2:{acct}:function:coach-nudge", "us-west-2"),
    "logs": ("logs:PutRetentionPolicy", "arn:aws:logs:us-west-2:{acct}:log-group:/aws/lambda/weekly-plate:*", "us-west-2"),
    "s3": ("s3:PutObject", "arn:aws:s3:::matthew-life-platform/site/index.html", "us-west-2"),
    "sagemaker": ("sagemaker:ListEndpoints", "*", "us-west-2"),
    "secretsmanager": (
        "secretsmanager:GetSecretValue",
        "arn:aws:secretsmanager:us-west-2:{acct}:secret:life-platform/whoop-AbCdEf",
        "us-west-2",
    ),
    "sns": ("sns:CreateTopic", "arn:aws:sns:us-west-2:{acct}:life-platform-alerts", "us-west-2"),
    "sqs": ("sqs:CreateQueue", "arn:aws:sqs:us-west-2:{acct}:life-platform-dlq", "us-west-2"),
    "ssm": ("ssm:GetParameter", "arn:aws:ssm:us-west-2:{acct}:parameter/cdk-bootstrap/hnb659fds/version", "us-west-2"),
}


@pytest.mark.parametrize("service", sorted(ACCESS_ADVISOR_SERVICES))
def test_every_service_the_role_actually_uses_is_still_allowed(service):
    action, resource, region = ACCESS_ADVISOR_SERVICES[service]
    verdict = evaluate(_policy(), action, resource.format(acct=constants.ACCT), region)
    assert verdict == "allowed", f"{service}: {action} reads {verdict} — the boundary would break a path the role has used"


# ═══════════════════════════════════════════════════════════════════════════════
# The clauses the issue names — asserted BY NAME, not as a consequence
# ═══════════════════════════════════════════════════════════════════════════════


def test_the_fence_cannot_remove_itself():
    """Self-protection. Without this, CloudFormation can call
    `iam:DeleteRolePermissionsBoundary` on its own exec role, or publish a new default
    version of this very document, and the boundary is decorative."""
    policy = _policy()
    for role in reg.CFN_EXEC_ROLE_NAMES:
        arn = f"arn:aws:iam::{constants.ACCT}:role/{role}"
        for action in ("iam:DeleteRolePermissionsBoundary", "iam:PutRolePermissionsBoundary"):
            assert evaluate(policy, action, arn, constants.REGION) == "explicitDeny", f"{action} on {role}"
    for action in ("iam:CreatePolicyVersion", "iam:DeletePolicy", "iam:DeletePolicyVersion", "iam:SetDefaultPolicyVersion"):
        assert evaluate(policy, action, boundary.POLICY_ARN, constants.REGION) == "explicitDeny", action
    # …and the clause exists as its own statement, not only as a wildcard's side effect.
    self_protect = _statement("DenyBoundarySelfMutation")
    assert boundary.POLICY_ARN in self_protect["Resource"]
    assert set(reg.CFN_EXEC_ROLE_NAMES) <= {r.rsplit("/", 1)[-1] for r in self_protect["Resource"]}


def test_the_protected_data_zones_refuse_deletion():
    """ADR-032/033/046 + DIL-027. The bucket policy's own Deny binds `matthew-admin` only,
    so it never was a backstop for CloudFormation."""
    policy = _policy()
    for prefix in reg.boundary_protected_s3_prefixes():
        arn = f"arn:aws:s3:::{constants.S3_BUCKET}/{prefix}some/object.json"
        assert evaluate(policy, "s3:DeleteObject", arn, constants.REGION) == "explicitDeny", prefix
        assert evaluate(policy, "s3:DeleteObjectVersion", arn, constants.REGION) == "explicitDeny", prefix
    replica = f"arn:aws:s3:::{constants.RAW_BACKUP_BUCKET}/raw/x.json"
    assert evaluate(policy, "s3:DeleteObject", replica, constants.RAW_BACKUP_REGION) == "explicitDeny"
    assert evaluate(policy, "s3:DeleteBucket", f"arn:aws:s3:::{constants.RAW_BACKUP_BUCKET}", constants.RAW_BACKUP_REGION) == "explicitDeny"
    # Positive control: an unprotected prefix CI's own paths already write AND delete.
    assert evaluate(policy, "s3:DeleteObject", f"arn:aws:s3:::{constants.S3_BUCKET}/site/a.html", constants.REGION) == "allowed"


def test_protected_identities_are_untouchable():
    policy = _policy()
    for name in ("github-actions-deploy-role", "github-actions-remediation-role", reg.CFN_EXEC_ROLE_NAMES[0]):
        arn = f"arn:aws:iam::{constants.ACCT}:role/{name}"
        assert evaluate(policy, "iam:AttachRolePolicy", arn, constants.REGION) == "explicitDeny", name
        assert evaluate(policy, "iam:UpdateAssumeRolePolicy", arn, constants.REGION) == "explicitDeny", name
    for action in ("iam:CreateUser", "iam:CreateAccessKey", "iam:CreateLoginProfile", "iam:AttachUserPolicy", "iam:PutUserPolicy"):
        assert evaluate(policy, action, f"arn:aws:iam::{constants.ACCT}:user/whoever", constants.REGION) == "explicitDeny", action


def test_the_region_pin_holds_and_does_not_break_the_global_services():
    policy = _policy()
    for region in reg.PLATFORM_REGIONS:
        assert evaluate(policy, "lambda:CreateFunction", f"arn:aws:lambda:{region}:{constants.ACCT}:function:x", region) == "allowed"
    for region in ("eu-central-1", "ap-southeast-2", "us-east-2a"):
        assert evaluate(policy, "lambda:CreateFunction", f"arn:aws:lambda:{region}:{constants.ACCT}:function:x", region) == "explicitDeny"
    # IAM and CloudFront are global; the pin must not reach them or every stack deploy dies.
    assert evaluate(policy, "iam:CreateRole", f"arn:aws:iam::{constants.ACCT}:role/LifePlatformCore-R", "eu-central-1") == "allowed"
    assert (
        evaluate(policy, "cloudfront:UpdateDistribution", f"arn:aws:cloudfront::{constants.ACCT}:distribution/D", "eu-central-1")
        == "allowed"
    )


def test_the_boundary_is_a_cap_not_a_grant():
    """A permissions boundary intersects with the identity policy; it never adds anything.
    The single broad Allow is what lets CloudFormation keep creating arbitrarily-named
    resources in ten stacks — the reason this is a guardrail and not a name allow-list."""
    allows = [st for st in _policy()["Statement"] if st["Effect"] == "Allow"]
    assert len(allows) == 1 and allows[0]["Action"] == "*" and allows[0]["Resource"] == "*"
    assert sum(1 for st in _policy()["Statement"] if st["Effect"] == "Deny") >= 14


# ═══════════════════════════════════════════════════════════════════════════════
# Dead-man — the verifier's new assertion, proved able to fail
# ═══════════════════════════════════════════════════════════════════════════════


class _FakeIam:
    """Just enough IAM for `verify_cfn_exec_boundary`. Every method raises or returns what
    the scenario declares — no network, no credentials."""

    class exceptions:  # noqa: N801 — mirrors botocore's client shape
        class NoSuchEntityException(Exception):
            pass

    def __init__(self, boundary_arn="__match__", document=None, role_error=None, policy_error=None):
        self._arn = boundary.POLICY_ARN if boundary_arn == "__match__" else boundary_arn
        self._document = document if document is not None else boundary.committed()
        self._role_error = role_error
        self._policy_error = policy_error

    def get_role(self, RoleName):  # noqa: N803 — boto3 kwarg casing
        if self._role_error:
            raise self._role_error
        role = {"RoleName": RoleName}
        if self._arn is not None:
            role["PermissionsBoundary"] = {"PermissionsBoundaryType": "Policy", "PermissionsBoundaryArn": self._arn}
        return {"Role": role}

    def get_policy(self, PolicyArn):  # noqa: N803
        if self._policy_error:
            raise self._policy_error
        return {"Policy": {"DefaultVersionId": "v1"}}

    def get_policy_version(self, PolicyArn, VersionId):  # noqa: N803
        if self._policy_error:
            raise self._policy_error
        return {"PolicyVersion": {"Document": self._document}}


def _statuses(iam) -> list[str]:
    findings: list[dict] = []
    verifier.verify_cfn_exec_boundary(iam, findings)
    return [f["status"] for f in findings]


def test_the_attached_and_matching_boundary_is_clean__positive_control():
    """The control that makes every red below mean something: with the committed document
    live on all three roles, the verifier reports nothing."""
    assert _statuses(_FakeIam()) == []


def test_a_missing_boundary_reads_red():
    statuses = _statuses(_FakeIam(boundary_arn=None))
    assert statuses == ["BOUNDARY-MISSING"] * len(reg.CFN_EXEC_ROLE_NAMES), statuses


def test_a_different_boundary_reads_red():
    statuses = _statuses(_FakeIam(boundary_arn=f"arn:aws:iam::{constants.ACCT}:policy/something-else"))
    assert statuses == ["BOUNDARY-DRIFT"] * len(reg.CFN_EXEC_ROLE_NAMES), statuses


def test_a_drifted_document_reads_red():
    """The shape that matters most: the boundary is attached, the ARN is right, and someone
    published a version with the `raw/` Deny removed."""
    tampered = json.loads(json.dumps(boundary.committed()))
    tampered["Statement"] = [st for st in tampered["Statement"] if st.get("Sid") != "DenyProtectedObjectDestruction"]
    statuses = _statuses(_FakeIam(document=tampered))
    assert statuses and set(statuses) == {"DRIFT"}, statuses


def test_an_unreadable_boundary_reads_red_not_silent():
    """`AccessDenied` is a finding, never a skip — a boundary nobody can read is
    indistinguishable from a boundary that is not there."""
    denied = PermissionError("AccessDenied: not authorized to perform iam:GetRole")
    assert set(_statuses(_FakeIam(role_error=denied))) == {"BOUNDARY-UNREADABLE"}
    assert "BOUNDARY-UNREADABLE" in _statuses(_FakeIam(policy_error=denied))


def test_strict_mode_turns_a_boundary_finding_into_a_nonzero_exit():
    """`--strict` is what the driver and the wrap ritual run. If a finding did not move the
    exit code, this whole assertion would be decoration."""
    src = (ROOT / "deploy" / "verify_oidc_iam.py").read_text(encoding="utf-8")
    assert "if args.strict and findings:" in src and "return 1" in src
    assert "verify_cfn_exec_boundary(iam, findings)" in src


# ═══════════════════════════════════════════════════════════════════════════════
# Ratchet + the record the owner reads
# ═══════════════════════════════════════════════════════════════════════════════

# The boundary registry as shipped 2026-08-31. Direction: the protected S3 prefixes and
# the protected IAM principals may only GROW; the enrolled principals may only SHRINK.
ENROLLED_AS_SHIPPED = frozenset(reg.ENROLLED_IAM_PRINCIPALS)
PROTECTED_IDENTITIES_AS_SHIPPED = frozenset(reg.IAM_PROTECTED_PRINCIPALS)
PROTECTED_PREFIXES_AS_SHIPPED = frozenset(
    {
        "blog/",
        "buddy/",
        "claude-memory-backup/",
        "cloudtrail/",
        "config/",
        "dashboard/",
        "datadrops-archive/",
        "deploys/",
        "exports/",
        "generated/",
        "imports/",
        "mcp-audit/",
        "raw/",
        "uploads/",
    }
)


def _adr_baseline() -> dict:
    hits = _ADR_FENCE.findall(DECISIONS.read_text(encoding="utf-8"))
    assert len(hits) == 1, f"expected exactly one ```json cfn-exec-boundary-baseline``` block in docs/DECISIONS.md, found {len(hits)}"
    return json.loads(hits[0])


def test_the_registry_equals_the_baseline_the_adr_declares():
    """R5's shape, reused: a widening of the fence's own registry has to appear in the
    owner-facing decision record, in the same PR — not only in a test file."""
    declared, shipped = _adr_baseline(), reg.boundary_registry_snapshot()
    assert set(declared) == set(shipped), set(declared) ^ set(shipped)
    for key in sorted(shipped):
        assert declared[key] == shipped[key], (
            f"{key} differs between deploy/iam_additive_registry.py and the ADR-065 "
            "cfn-exec-boundary fenced block. Regenerate and paste it into docs/DECISIONS.md, in the SAME PR."
        )


def test_the_adr_block_is_non_vacuous():
    declared = _adr_baseline()
    assert len(declared["protected_s3_prefixes"]) >= 14
    assert len(declared["protected_iam_principals"]) >= 6
    assert len(declared["cfn_exec_roles"]) == 3
    assert len(declared["regions"]) == 3


def test_the_fence_only_moves_in_the_sanctioned_direction():
    assert PROTECTED_PREFIXES_AS_SHIPPED <= set(reg.boundary_protected_s3_prefixes()), "a protected S3 prefix was DROPPED"
    assert PROTECTED_IDENTITIES_AS_SHIPPED <= set(reg.IAM_PROTECTED_PRINCIPALS), "a protected IAM identity was DROPPED"
    added = set(reg.ENROLLED_IAM_PRINCIPALS) - ENROLLED_AS_SHIPPED
    assert not added, f"the enrolled IAM families WIDENED without a dated ADR-065 amendment: {sorted(added)}"


def test_the_runbook_puts_rollback_first():
    """Every apply runbook in this repo that mattered was read under pressure. Rollback is
    the first thing on the page, before the apply, on purpose."""
    text = IAM_README.read_text(encoding="utf-8")
    assert "#3340" in text, "infra/iam/README.md has no #3340 section"
    section = text[text.index("#3340") :]
    # The COMMANDS, not the prose that names them — the prose paragraph above the runbook
    # legitimately says "three put- calls, rolled back by three delete- calls".
    rollback = section.index("aws iam delete-role-permissions-boundary")
    apply_at = section.index("aws iam put-role-permissions-boundary")
    assert rollback < apply_at, "the #3340 runbook states the apply before the rollback — invert it"
    for needle in ("create-policy", "cdk-cfn-exec-boundary.boundary.json", "verify_oidc_iam.py --strict", "boundary_probe"):
        assert needle in section, f"the #3340 runbook never mentions {needle}"


def test_the_rent_row_exists():
    assert "cdk-cfn-exec-boundary" in PROPORTIONALITY.read_text(encoding="utf-8"), "docs/PROPORTIONALITY.md has no #3340 rent row"


# ═══════════════════════════════════════════════════════════════════════════════
# The mutation probe itself — non-vacuous by construction
# ═══════════════════════════════════════════════════════════════════════════════


def _probe(name: str) -> dict:
    return json.loads((PROBE_DIR / name).read_text(encoding="utf-8"))


def test_the_escalation_probe_actually_asks_for_the_escalation():
    """A probe that asks for something benign would 'pass' after attach and prove nothing —
    the vacuous-negative-control shape. Assert the plant is really a plant."""
    role = _probe("escalation.template.json")["Resources"]["EscalationRole"]
    assert role["Type"] == "AWS::IAM::Role"
    assert "RoleName" not in role["Properties"], "an explicit name could land inside an enrolled family and make the probe pass"
    statement = role["Properties"]["Policies"][0]["PolicyDocument"]["Statement"][0]
    assert statement["Action"] == "iam:*" and statement["Resource"] == "*"
    # And the boundary refuses the role CloudFormation would name for it.
    arn = f"arn:aws:iam::{constants.ACCT}:role/boundary-probe-3340-EscalationRole-A1B2C3"
    assert evaluate(_policy(), "iam:CreateRole", arn, constants.REGION) == "explicitDeny"


def test_the_additive_probe_is_the_positive_control_and_would_still_deploy():
    role = _probe("additive.template.json")["Resources"]["AdditiveRole"]
    name = role["Properties"]["RoleName"]
    assert name.startswith(reg.CDK_STACK_NAME_PREFIX), name
    arn = f"arn:aws:iam::{constants.ACCT}:role/{name}"
    assert evaluate(_policy(), "iam:CreateRole", arn, constants.REGION) == "allowed"
    statement = role["Properties"]["Policies"][0]["PolicyDocument"]["Statement"][0]
    assert statement["Action"] == "s3:GetObject"
    assert statement["Resource"].startswith(f"arn:aws:s3:::{constants.S3_BUCKET}/config/")


def test_no_other_deploy_file_carries_a_copy_of_the_boundary_document():
    """#3336's lesson, applied to this artifact by its own guard.

    `tests/test_iam_twin_free_3336.py` is scoped to roles that have BOTH a `.trust.json`
    and a `.permissions.json` — the four OIDC identities. This document is a standalone
    managed policy with no trust policy, so it is out of that guard's structural scope by
    construction, and a blind spot left there would be exactly the shape #3336 was.

    The rule: the derivation is the only file under `deploy/` that may carry these Sids.
    Everything else — an apply script, a helper, a "convenience" copy — must reference
    `infra/iam/cdk-cfn-exec-boundary.boundary.json` by path, never restate it.
    """
    sids = {st["Sid"] for st in _policy()["Statement"]}
    marker = "DenyIamWritesOutsideEnrolledFamilies"
    assert marker in sids
    offenders = []
    for path in sorted(list((ROOT / "deploy").glob("*.py")) + list((ROOT / "deploy").glob("*.sh"))):
        if path.name == "derive_cfn_exec_boundary.py":
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if marker in text and '"Effect"' in text:
            offenders.append(path.name)
    assert not offenders, f"these deploy/ files restate the boundary document instead of applying it by path: {offenders}"
    # Non-vacuity: the detector finds the derivation itself when it is not excluded.
    derivation = (ROOT / "deploy" / "derive_cfn_exec_boundary.py").read_text(encoding="utf-8")
    assert marker in derivation and '"Effect"' in derivation
