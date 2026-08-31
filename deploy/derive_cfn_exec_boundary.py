#!/usr/bin/env python3
"""deploy/derive_cfn_exec_boundary.py — render the CDK cfn-exec permissions boundary (#3340).

WHY THIS EXISTS
  `cdk-hnb659fds-cfn-exec-role-<acct>-<region>` is the identity CloudFormation acts as when
  it creates, updates and deletes every resource in the platform's ten stacks. Verified live
  read-only 2026-08-31: all three regional copies carry **AdministratorAccess** and
  `PermissionsBoundary: None`. CI's OIDC deploy identity has held `sts:AssumeRole` on
  `role/cdk-*` since #401, and since #2834 CI actually exercises that chain on every
  additive IAM grant. So CI's additive-IAM gate (`deploy/iam_additive_gate.py`) — a parser
  over a synthesized template — is the ONLY thing between a template and an account-wide
  change. That is a belt with no braces.

  This module is the braces: a permissions boundary attached to those three roles, whose
  Denies IAM enforces regardless of what the gate parses, skips, or gets wrong.

WHY A GUARDRAIL AND NOT AN ALLOW-LIST OF NAMES
  Resource naming in this account is NOT `life-platform*`-uniform (measured live
  2026-08-31): 113 of 147 IAM roles are CDK auto-named `LifePlatform<Stack>-<Construct><Hash>`,
  only three are `life-platform*`, and most Lambda functions carry no platform prefix at all
  (`coach-nudge`, `weekly-plate`, `ai-expert-analyzer`, `site-stats-refresh`, …). A boundary
  that only Allowed `life-platform*` ARNs would have refused every stack deploy on the first
  attempt. CloudFormation must be able to create arbitrarily-named resources in ten stacks.
  So the shape is: **Allow broadly, Deny explicitly** — the standard guardrail form, where
  each Deny names a specific irreversible or privilege-escalating capability.

ONE SOURCE
  Every value here is read from `deploy/iam_additive_registry.py`, the registry the additive
  gate already reads: the protected S3 prefixes derive from `deploy/bucket_policy.json`; the
  enrolled IAM name families derive from `cdk/app.py`'s stack ids; the buckets, account and
  regions derive from `cdk/stacks/constants.py`. There is no second list to drift.

USAGE
    python3 deploy/derive_cfn_exec_boundary.py             # print the rendered document
    python3 deploy/derive_cfn_exec_boundary.py --write     # (re)write the committed JSON
    python3 deploy/derive_cfn_exec_boundary.py --check     # exit 1 if committed != derived
    python3 deploy/derive_cfn_exec_boundary.py --simulate  # read-only iam:SimulateCustomPolicy probes

The committed render is `infra/iam/cdk-cfn-exec-boundary.boundary.json`. It is applied
VERBATIM by the owner (`aws iam create-policy --policy-document file://…`) — never inlined
into a shell script (#3336). The apply/verify/rollback runbook is `infra/iam/README.md`.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "deploy"))

from iam_additive_registry import (  # noqa: E402
    _C,
    ACCOUNT,
    BOUNDARY_POLICY_NAME,
    CDK_BOOTSTRAP_QUALIFIER,
    CFN_EXEC_ROLE_NAMES,
    ENROLLED_IAM_PRINCIPALS,
    IAM_PROTECTED_PRINCIPALS,
    PLATFORM_REGIONS,
    PLATFORM_SLUG,
    boundary_protected_s3_prefixes,
)

# `.boundary.json`, NOT `.permissions.json`: the latter suffix is the #3336 guard's
# structural signal for "a governed ROLE's inline policy document, which must have a
# matching .trust.json". This document is a standalone managed policy attached as a
# boundary — it has no trust policy and no role of its own, and naming it after the
# role convention would have made `tests/test_iam_twin_free_3336.py` treat it as a
# fifth OIDC identity. Its own twin guard lives in tests/test_cfn_exec_boundary_3340.py.
POLICY_PATH = ROOT / "infra" / "iam" / f"{BOUNDARY_POLICY_NAME}.boundary.json"
POLICY_ARN = f"arn:aws:iam::{ACCOUNT}:policy/{BOUNDARY_POLICY_NAME}"

# AWS's managed-policy size limit. The limit counts the document with whitespace removed
# (IAM "character limits" section), so the committed file may be pretty-printed; the
# render still has to fit compact, and the test asserts BOTH numbers.
MANAGED_POLICY_MAX_CHARS = 6144

# Services whose endpoints are global (or whose control plane always resolves to one
# region) and therefore cannot carry a meaningful `aws:RequestedRegion` for the region
# pin. Denying them by region would break `iam:*` on every stack deploy and the
# CloudFront/ACM path of LifePlatformWeb. Each one is separately fenced by a Deny below
# where it needs to be — the region pin is not their guard.
# `organizations` and `account` are absent on purpose: they are denied outright below, so
# exempting them from the region pin would only weaken a fence that is already closed.
# The set is the three global services this role has ACTUALLY used (IAM, CloudFront and
# Budgets — IAM Access Advisor, three regions, read 2026-08-31) plus `sts` and `route53`,
# which have no regional form. Anything else global that a future stack needs is a
# regenerate-and-review, not a silent allowance.
GLOBAL_SERVICE_ACTIONS: tuple[str, ...] = (
    "iam:*",
    "sts:*",
    "cloudfront:*",
    "route53:*",
    "budgets:*",
)

# IAM writes that change WHO can do WHAT. Confined to the enrolled name families by
# `DenyIamWritesOutsideEnrolledFamilies`. Reads (`iam:Get*`/`List*`/`Simulate*`) are
# deliberately NOT here: they grant nothing, CloudFormation issues them constantly
# during drift and resource-existence checks, and denying them would turn a fence into
# an outage. `iam:CreateServiceLinkedRole` is likewise absent — its resource is always
# `role/aws-service-role/<service>/…`, out of every family by construction, and it can
# only mint the role the named service principal is entitled to. `iam:TagRole` /
# `iam:UntagRole` / `iam:UpdateRoleDescription` are absent too: they grant nothing, and
# CDK tags every role it creates (`cdk.Tags.of(app)` in cdk/app.py) — a fence that trips
# on a tag is an outage that teaches people to remove the fence.
IAM_WRITE_ACTIONS: tuple[str, ...] = (
    "iam:CreateRole",
    "iam:DeleteRole",
    "iam:UpdateRole",
    "iam:UpdateAssumeRolePolicy",
    "iam:AttachRolePolicy",
    "iam:DetachRolePolicy",
    "iam:PutRolePolicy",
    "iam:DeleteRolePolicy",
    "iam:PutRolePermissionsBoundary",
    "iam:DeleteRolePermissionsBoundary",
    "iam:PassRole",
    "iam:CreatePolicy",
    "iam:DeletePolicy",
    "iam:CreatePolicyVersion",
    "iam:DeletePolicyVersion",
    "iam:SetDefaultPolicyVersion",
)

# The fence's own removal. Named explicitly even though
# `DenyIamOnProtectedIdentities` already covers `role/cdk-*` + `policy/cdk-*`: a
# self-protection clause that exists only as a consequence of a wildcard is one
# refactor away from silently not existing.
BOUNDARY_SELF_MUTATION_ACTIONS: tuple[str, ...] = (
    "iam:PutRolePermissionsBoundary",
    "iam:DeleteRolePermissionsBoundary",
    "iam:CreatePolicyVersion",
    "iam:DeletePolicy",
    "iam:DeletePolicyVersion",
    "iam:SetDefaultPolicyVersion",
)


def _sorted_unique(values: Any) -> list[str]:
    return sorted(set(values))


def build_policy() -> dict[str, Any]:
    """The boundary document, derived. Statement order is stable; IAM evaluation is not
    order-dependent (any Deny wins), so the order here is for the human reader."""
    bucket = _C.S3_BUCKET
    replica = _C.RAW_BACKUP_BUCKET
    protected_objects = [f"arn:aws:s3:::{bucket}/{prefix}*" for prefix in boundary_protected_s3_prefixes()]
    protected_objects.append(f"arn:aws:s3:::{replica}/*")

    statements: list[dict[str, Any]] = [
        {
            "Sid": "AllowEverythingTheFenceDoesNotRefuse",
            "Effect": "Allow",
            "Action": "*",
            "Resource": "*",
        },
        {
            # A boundary caps; it never grants. CloudFormation creates arbitrarily-named
            # resources in ten stacks, so the Allow above is the only shape that does not
            # break the first deploy — every real control below is a Deny.
            "Sid": "DenyOutsidePlatformRegions",
            "Effect": "Deny",
            "NotAction": list(GLOBAL_SERVICE_ACTIONS),
            "Resource": "*",
            "Condition": {"StringNotEquals": {"aws:RequestedRegion": list(PLATFORM_REGIONS)}},
        },
        {
            # ADR-032/033/046. The bucket policy's own Deny binds `matthew-admin` ONLY —
            # it never was a backstop for CloudFormation. Prefixes derive from
            # deploy/bucket_policy.json; the replica (DIL-027) is fenced whole.
            "Sid": "DenyProtectedObjectDestruction",
            "Effect": "Deny",
            "Action": [
                "s3:DeleteObject",
                "s3:DeleteObjectVersion",
                "s3:PutObjectRetention",
                "s3:PutObjectLegalHold",
                "s3:BypassGovernanceRetention",
            ],
            "Resource": protected_objects,
        },
        {
            # The platform bucket is IMPORTED into CDK (`Bucket.from_bucket_name`, every
            # stack), so CloudFormation has no legitimate reason to touch its bucket-level
            # configuration at all — its policy and lifecycle are owner-applied.
            "Sid": "DenyPlatformBucketControlPlane",
            "Effect": "Deny",
            "Action": [
                "s3:DeleteBucket",
                "s3:PutBucketPolicy",
                "s3:DeleteBucketPolicy",
                "s3:PutLifecycleConfiguration",
                "s3:PutBucketVersioning",
                "s3:PutReplicationConfiguration",
                "s3:PutEncryptionConfiguration",
                "s3:PutBucketPublicAccessBlock",
                "s3:PutBucketAcl",
            ],
            "Resource": [f"arn:aws:s3:::{bucket}"],
        },
        {
            # The replica IS CDK-owned (backup_stack.py), so its versioning, lifecycle and
            # encryption stay writable — only its destruction and its delete-protection
            # policy are fenced. Removing either is an owner-run operation by design.
            "Sid": "DenyBackupBucketDestruction",
            "Effect": "Deny",
            "Action": ["s3:DeleteBucket", "s3:DeleteBucketPolicy", "s3:PutReplicationConfiguration"],
            "Resource": [f"arn:aws:s3:::{replica}"],
        },
        {
            "Sid": "DenyIamPrincipalMinting",
            "Effect": "Deny",
            "Action": [
                "iam:CreateUser",
                "iam:CreateAccessKey",
                "iam:CreateLoginProfile",
                "iam:UpdateLoginProfile",
                "iam:AttachUserPolicy",
                "iam:PutUserPolicy",
                "iam:AddUserToGroup",
                "iam:CreateGroup",
                "iam:AttachGroupPolicy",
                "iam:PutGroupPolicy",
                "iam:CreateSAMLProvider",
                "iam:CreateOpenIDConnectProvider",
                "iam:UpdateOpenIDConnectProviderThumbprint",
                "iam:UpdateAccountPasswordPolicy",
            ],
            "Resource": "*",
        },
        {
            # The enrolled families are cdk/app.py's stack ids (CDK names every role it
            # creates `<StackName>-<Construct><Hash>`) plus the `life-platform-*` roles
            # whose physical names are pinned in constants.py.
            "Sid": "DenyIamWritesOutsideEnrolledFamilies",
            "Effect": "Deny",
            "Action": list(IAM_WRITE_ACTIONS),
            "NotResource": _sorted_unique(ENROLLED_IAM_PRINCIPALS),
        },
        {
            "Sid": "DenyIamOnProtectedIdentities",
            "Effect": "Deny",
            "Action": "iam:*",
            "Resource": _sorted_unique(IAM_PROTECTED_PRINCIPALS),
        },
        {
            "Sid": "DenyBoundarySelfMutation",
            "Effect": "Deny",
            "Action": list(BOUNDARY_SELF_MUTATION_ACTIONS),
            "Resource": _sorted_unique([POLICY_ARN] + [f"arn:aws:iam::{ACCOUNT}:role/{r}" for r in CFN_EXEC_ROLE_NAMES]),
        },
        {
            "Sid": "DenyAccountAndOrganizationControlPlane",
            "Effect": "Deny",
            "Action": [
                "organizations:*",
                "account:*",
                "aws-portal:*",
                "iam:CreateAccountAlias",
                "budgets:DeleteBudget",
            ],
            "Resource": "*",
        },
        {
            "Sid": "DenyAuditAndDetectionTampering",
            "Effect": "Deny",
            "Action": [
                "cloudtrail:StopLogging",
                "cloudtrail:DeleteTrail",
                "cloudtrail:UpdateTrail",
                "cloudtrail:PutEventSelectors",
                "config:DeleteConfigurationRecorder",
                "config:DeleteDeliveryChannel",
                "config:StopConfigurationRecorder",
                "guardduty:DeleteDetector",
                "guardduty:UpdateDetector",
                "securityhub:DisableSecurityHub",
                "access-analyzer:DeleteAnalyzer",
            ],
            "Resource": "*",
        },
        {
            # No CDK stack creates a KMS key or alias (verified: no `aws_kms` import in
            # cdk/stacks/), so every one of these is pure fence.
            "Sid": "DenyKeyDestruction",
            "Effect": "Deny",
            "Action": ["kms:ScheduleKeyDeletion", "kms:DisableKey", "kms:PutKeyPolicy", "kms:DeleteAlias"],
            "Resource": "*",
        },
        {
            # Every credential lives under `life-platform/`; none is CDK-created (the
            # site-api origin secret is imported by partial ARN).
            "Sid": "DenySecretMutation",
            "Effect": "Deny",
            "Action": [
                "secretsmanager:DeleteSecret",
                "secretsmanager:PutSecretValue",
                "secretsmanager:UpdateSecret",
                "secretsmanager:RotateSecret",
                "secretsmanager:PutResourcePolicy",
            ],
            "Resource": [f"arn:aws:secretsmanager:*:{ACCOUNT}:secret:{PLATFORM_SLUG}/*"],
        },
        {
            # The table is imported into CDK too — CloudFormation never legitimately
            # deletes it, disables PITR, or flips its TTL attribute (#951's class).
            "Sid": "DenyDataStoreDestruction",
            "Effect": "Deny",
            "Action": [
                "dynamodb:DeleteTable",
                "dynamodb:DeleteBackup",
                "dynamodb:UpdateContinuousBackups",
                "dynamodb:UpdateTimeToLive",
                "backup:DeleteBackupVault",
                "backup:DeleteRecoveryPoint",
                "backup:DeleteBackupPlan",
            ],
            "Resource": "*",
        },
        {
            "Sid": "DenyServingSurfaceDestruction",
            "Effect": "Deny",
            "Action": [
                "cloudfront:DeleteDistribution",
                "acm:DeleteCertificate",
                "route53:DeleteHostedZone",
            ],
            "Resource": "*",
        },
        {
            "Sid": "DenySsmPlatformParameterDeletion",
            "Effect": "Deny",
            "Action": ["ssm:DeleteParameter", "ssm:DeleteParameters"],
            "Resource": [f"arn:aws:ssm:*:{ACCOUNT}:parameter/{PLATFORM_SLUG}/*"],
        },
        {
            "Sid": "DenyRoleAssumptionOutsideThisAccount",
            "Effect": "Deny",
            "Action": ["sts:AssumeRole", "sts:AssumeRoleWithSAML", "sts:AssumeRoleWithWebIdentity"],
            "NotResource": [f"arn:aws:iam::{ACCOUNT}:role/*"],
        },
    ]
    return {"Version": "2012-10-17", "Statement": statements}


def render(policy: dict[str, Any] | None = None) -> str:
    """The exact bytes of the committed file (pretty, trailing newline)."""
    return json.dumps(policy if policy is not None else build_policy(), indent=2) + "\n"


def compact_size(policy: dict[str, Any] | None = None) -> int:
    """The size IAM measures: the document with whitespace removed."""
    return len(json.dumps(policy if policy is not None else build_policy(), separators=(",", ":")))


def committed() -> dict[str, Any]:
    with open(POLICY_PATH, encoding="utf-8") as fh:
        return json.load(fh)


HOME = PLATFORM_REGIONS[0]


def simulation_probes() -> tuple[tuple[str, str, str, str], ...]:
    """(action, resource, aws:RequestedRegion, expected decision) — the boundary's contract.

    Shared by `--simulate` (live `iam:SimulateCustomPolicy`, read-only, the PR's pre-apply
    evidence) and by the offline unit test, so the two can never disagree about what this
    document is supposed to do.

    `aws:RequestedRegion` is passed on EVERY probe on purpose: the region pin's
    `StringNotEquals` is a NEGATED operator, and a negated operator over an ABSENT key
    evaluates TRUE — so a simulation with no context entry reports explicitDeny for
    everything and proves nothing. That is the vacuous-negative-control shape, and it is
    the first thing this probe set had to avoid.

    The protected-identity probes are GENERATED from `IAM_PROTECTED_PRINCIPALS` rather than
    typed, so the probe set grows with the registry (guard the SET) — and so this module,
    which necessarily carries a policy document, never spells a governed OIDC role's name
    and cannot read as a #3336 twin.
    """
    # One probe per protected family. The action has to SUIT the ARN type: AWS's simulator
    # models action↔resource applicability and returns `implicitDeny` for
    # `iam:AttachRolePolicy` on a user/group/policy ARN (measured — three probes disagreed
    # with the offline evaluator until this map existed), so a type-mismatched probe would
    # be a vacuous negative control that passes for the wrong reason.
    by_kind = {
        "role": "iam:PutRolePolicy",
        "policy": "iam:CreatePolicyVersion",
        "user": "iam:PutUserPolicy",
        "group": "iam:PutGroupPolicy",
    }
    protected = tuple(
        (by_kind[pattern.split(":")[5].split("/")[0]], pattern.replace("*", "probe"), HOME, "explicitDeny")
        for pattern in IAM_PROTECTED_PRINCIPALS
    )
    return protected + (
        # ── the escalation the #3340 probe stack deploys ───────────────────────────────
        ("iam:CreateRole", f"arn:aws:iam::{ACCOUNT}:role/boundary-probe-3340-EscalationRole", HOME, "explicitDeny"),
        ("iam:PutRolePolicy", f"arn:aws:iam::{ACCOUNT}:role/boundary-probe-3340-EscalationRole", HOME, "explicitDeny"),
        # ── the fence protecting itself ───────────────────────────────────────────────
        ("iam:DeleteRolePermissionsBoundary", f"arn:aws:iam::{ACCOUNT}:role/{CFN_EXEC_ROLE_NAMES[0]}", HOME, "explicitDeny"),
        ("iam:CreatePolicyVersion", POLICY_ARN, HOME, "explicitDeny"),
        ("iam:CreateUser", f"arn:aws:iam::{ACCOUNT}:user/evil", HOME, "explicitDeny"),
        # ── the data the platform cannot recompute ────────────────────────────────────
        ("s3:DeleteObject", f"arn:aws:s3:::{_C.S3_BUCKET}/raw/matthew/whoop/2026/08/2026-08-31.json", HOME, "explicitDeny"),
        ("s3:DeleteObject", f"arn:aws:s3:::{_C.RAW_BACKUP_BUCKET}/raw/x.json", HOME, "explicitDeny"),
        ("s3:PutBucketPolicy", f"arn:aws:s3:::{_C.S3_BUCKET}", HOME, "explicitDeny"),
        ("dynamodb:DeleteTable", f"arn:aws:dynamodb:{HOME}:{ACCOUNT}:table/{_C.TABLE_NAME}", HOME, "explicitDeny"),
        (
            "secretsmanager:PutSecretValue",
            f"arn:aws:secretsmanager:{HOME}:{ACCOUNT}:secret:{PLATFORM_SLUG}/whoop-AbCdEf",
            HOME,
            "explicitDeny",
        ),
        ("ssm:DeleteParameter", f"arn:aws:ssm:{HOME}:{ACCOUNT}:parameter/{PLATFORM_SLUG}/remediation-mode", HOME, "explicitDeny"),
        ("cloudfront:DeleteDistribution", f"arn:aws:cloudfront::{ACCOUNT}:distribution/{_C.CF_DIST_ID}", "us-east-1", "explicitDeny"),
        # ── the region pin, both directions ───────────────────────────────────────────
        ("s3:CreateBucket", "arn:aws:s3:::a-bucket-in-frankfurt", "eu-central-1", "explicitDeny"),
        ("s3:CreateBucket", "arn:aws:s3:::a-bucket-in-ohio", "us-east-2", "allowed"),
        # ── POSITIVE CONTROLS: what a normal stack deploy does, and must keep doing ────
        ("iam:CreateRole", f"arn:aws:iam::{ACCOUNT}:role/LifePlatformCompute-NewRoleABC123-XyZ", HOME, "allowed"),
        ("iam:PutRolePolicy", f"arn:aws:iam::{ACCOUNT}:role/LifePlatformIngestion-WhoopIngestionRole9858872A-3o", HOME, "allowed"),
        ("iam:PassRole", f"arn:aws:iam::{ACCOUNT}:role/LifePlatformEmail-DailyBriefRoleCE6CDC95-ksIxNOHNdRvg", HOME, "allowed"),
        ("iam:CreateRole", f"arn:aws:iam::{ACCOUNT}:role/{PLATFORM_SLUG}-raw-replication", HOME, "allowed"),
        ("lambda:UpdateFunctionCode", f"arn:aws:lambda:{HOME}:{ACCOUNT}:function:coach-nudge", HOME, "allowed"),
        ("lambda:CreateFunction", f"arn:aws:lambda:{HOME}:{ACCOUNT}:function:weekly-plate", HOME, "allowed"),
        ("logs:CreateLogGroup", f"arn:aws:logs:{HOME}:{ACCOUNT}:log-group:/aws/lambda/site-stats-refresh", HOME, "allowed"),
        ("s3:PutObject", f"arn:aws:s3:::{_C.S3_BUCKET}/site/index.html", HOME, "allowed"),
        ("s3:DeleteObject", f"arn:aws:s3:::{_C.S3_BUCKET}/site/index.html", HOME, "allowed"),
        ("s3:PutBucketVersioning", f"arn:aws:s3:::{_C.RAW_BACKUP_BUCKET}", "us-east-2", "allowed"),
        ("events:PutRule", f"arn:aws:events:{HOME}:{ACCOUNT}:rule/LifePlatformIngestion-WhoopRule", HOME, "allowed"),
        ("acm:DescribeCertificate", f"arn:aws:acm:us-east-1:{ACCOUNT}:certificate/abc", "us-east-1", "allowed"),
        ("ssm:GetParameter", f"arn:aws:ssm:{HOME}:{ACCOUNT}:parameter/cdk-bootstrap/{CDK_BOOTSTRAP_QUALIFIER}/version", HOME, "allowed"),
    )


def _simulate() -> int:  # pragma: no cover — read-only AWS, run by hand for the PR evidence
    """`iam:SimulateCustomPolicy` verdicts for the probe set. Read-only, no mutation."""
    import boto3

    doc = json.dumps(build_policy())
    iam = boto3.client("iam")
    bad = 0
    probes = simulation_probes()
    for action, resource, region, expected in probes:
        resp = iam.simulate_custom_policy(
            PolicyInputList=[doc],
            ActionNames=[action],
            ResourceArns=[resource],
            ContextEntries=[
                {"ContextKeyName": "aws:RequestedRegion", "ContextKeyValues": [region], "ContextKeyType": "string"},
            ],
        )
        decision = resp["EvaluationResults"][0]["EvalDecision"]
        ok = decision == expected
        bad += 0 if ok else 1
        print(f"{'OK ' if ok else 'BAD'}  {action:<34} {decision:<14} (expected {expected})  [{region}]\n      {resource}")
    print(f"\n{len(probes) - bad}/{len(probes)} simulator verdicts as expected")
    return 0 if bad == 0 else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--write", action="store_true", help="(re)write the committed JSON")
    ap.add_argument("--check", action="store_true", help="exit 1 if the committed JSON differs from the derivation")
    ap.add_argument("--simulate", action="store_true", help="read-only iam:SimulateCustomPolicy probes")
    args = ap.parse_args()

    policy = build_policy()
    size = compact_size(policy)
    if size > MANAGED_POLICY_MAX_CHARS:
        print(f"error: rendered boundary is {size} chars, over IAM's {MANAGED_POLICY_MAX_CHARS} managed-policy limit", file=sys.stderr)
        return 2

    if args.simulate:
        return _simulate()

    if args.write:
        POLICY_PATH.write_text(render(policy), encoding="utf-8")
        print(f"wrote {POLICY_PATH.relative_to(ROOT)} ({size} chars compact, limit {MANAGED_POLICY_MAX_CHARS})")
        return 0

    if args.check:
        if not POLICY_PATH.exists():
            print(f"error: {POLICY_PATH.relative_to(ROOT)} is missing — run --write", file=sys.stderr)
            return 1
        if committed() != policy:
            print(
                f"DRIFT: {POLICY_PATH.relative_to(ROOT)} differs from the derivation. "
                "Regenerate with `python3 deploy/derive_cfn_exec_boundary.py --write` in the SAME PR "
                "that changed the registry it derives from.",
                file=sys.stderr,
            )
            return 1
        print(f"CLEAN — committed boundary == derivation ({size} chars compact, limit {MANAGED_POLICY_MAX_CHARS})")
        return 0

    sys.stdout.write(render(policy))
    return 0


if __name__ == "__main__":
    sys.exit(main())
