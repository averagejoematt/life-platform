#!/usr/bin/env python3
"""deploy/iam_additive_gate.py — the statement-level additive-IAM gate (#2834, ADR-065 amendment 2026-08-30).

WHAT THIS DECIDES
  CI's Plan job used to red on ANY `cdk diff` line matching /iam|policy|role|permission/i
  (the R8-ST6 grep). That gate was right to exist and wrong in shape: it stranded the whole
  code-deploy pipeline for ~14h on a single `sqs:SendMessage` grant (INCIDENT_LOG 2026-08-15),
  it left a fail-closed privacy screen silently no-op'd for five days because the fix was an
  IAM grant nobody could ship through CI (2026-08-14 P1), and it fired on
  `AWS::CloudFront::ResponseHeadersPolicy` because the word "Policy" was in the type name.

  The owner's decision (#2834, option b): CI may apply an IAM change ONLY when the synthesized
  TEMPLATE diff is additive-only —

    * every changed statement is a NEW `Allow` (or an existing Allow that only GREW, which is
      how CDK's `minimizePolicies` merges a new grant into a like-shaped statement);
    * every resource ARN is inside the platform namespace, derived from an explicit registry
      (`NAMESPACE_FAMILIES` below — built from `cdk/stacks/constants.py` + `ci/lambda_map.json`,
      never a regex guess);
    * no `Deny` removed, narrowed, altered — or added;
    * no trust-policy (`AssumeRolePolicyDocument`) edit, no new/removed/changed role;
    * no `iam:*` / `sts:*` / `*` / service-wide wildcard action, no action overlapping
      `FORBIDDEN_ACTION_PATTERNS`;
    * no wildcard (`*`) resource, no out-of-account or out-of-region ARN;
    * no managed-policy attachment, no permissions boundary, no resource-based policy
      (Lambda::Permission, BucketPolicy, QueuePolicy, TopicPolicy, KMS key policy …), no
      policy bound to a user/group, no change to which role a policy binds to;
    * and nothing ELSE rides along in the same stack that CI's code path cannot ship — the
      only tolerated non-IAM churn is `TOLERATED_NON_IAM` (Lambda `Code` asset hashes, which
      move on every commit by construction since #2377; the CDK-internal LogRetention
      singleton's toolchain-chosen `Runtime`, #2468; `CDKMetadata.Analytics`; resource
      `Metadata`).

  Anything else → OWNER-REQUIRED, every offending statement named, with the owner path
  (`bash deploy/cdk_deploy.sh <Stack>`) printed. A diff this module cannot parse or fetch is
  OWNER-REQUIRED too — the gate fails CLOSED (exit 2), never open.

VERDICTS (per stack)
  NO-IAM-CHANGE   nothing IAM-relevant differs (non-IAM diffs, if any, are listed as an
                  advisory `pending owner cdk deploy` — they neither strand nor ship)
  ALLOW-ADDITIVE  ≥1 admitted IAM delta, zero findings, zero non-tolerated non-IAM changes
  OWNER-REQUIRED  ≥1 finding (named), or additive IAM riding with non-IAM changes, or
                  the stack could not be evaluated

INPUT — THE TEMPLATE DIFF, NOT PROSE
  Synthesized side: `cdk.out/` (manifest.json → per-stack template + environment).
  Deployed side:    `--live` (`aws cloudformation get-template --template-stage Original`,
                    read-only, the same JSON shape CDK deployed) or `--deployed-dir` (files
                    named `<Stack>.template.json`, for tests and offline review).

THE FIVE PRIMITIVES (docs/CHARTER.md) — where each lives
  registry          NAMESPACE_FAMILIES / FORBIDDEN_ACTION_PATTERNS / TOLERATED_NON_IAM (below)
  derivation guard  tests/test_iam_additive_gate_guards_2834.py — namespace values derive from
                    cdk/stacks/constants.py + ci/lambda_map.json; no hand-typed account/table
  ratchet           same file — forbidden set may only grow, namespace/tolerance sets may only
                    shrink, each entry dated; widening needs a dated ADR-065 amendment line
  contract test     tests/test_iam_additive_gate_2834.py — one mutation per forbidden shape on
                    a REAL synthesized template slice (the wire), plus positive controls
  dead-man          exit 2 + OWNER-REQUIRED on anything unevaluable; the Deploy job asserts the
                    Plan verdict output EXISTS before it does anything (absence ≠ pass); the
                    wiring test pins both steps into ci-cd.yml with no continue-on-error

USAGE
  python3 deploy/iam_additive_gate.py --synth-dir cdk/cdk.out --live [--stacks A B] \
      [--json OUT.json] [--github-output FILE] [--expect-converged]
  Exit 0: every evaluated stack is NO-IAM-CHANGE or ALLOW-ADDITIVE.
  Exit 1: ≥1 OWNER-REQUIRED (or, with --expect-converged, ≥1 stack still carries IAM diff).
  Exit 2: usage error / unevaluable input (reported as OWNER-REQUIRED — fail closed).
"""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
GATE_NAME = "iam_additive_gate"
ISSUE = 2834
OWNER_PATH = "bash deploy/cdk_deploy.sh <Stack>   # owner-run, from main (docs/CONVENTIONS.md §6)"

ALLOW = "ALLOW-ADDITIVE"
NO_CHANGE = "NO-IAM-CHANGE"
OWNER = "OWNER-REQUIRED"


# ═══════════════════════════════════════════════════════════════════════════════
# REGISTRY — the allowed shape, as data. Every entry is dated; the ratchet test pins
# these sets (forbidden may only grow; namespace + tolerance may only shrink).
# ═══════════════════════════════════════════════════════════════════════════════


def _load_constants():
    """cdk/stacks/constants.py, loaded by FILE so no aws_cdk import is needed (it only imports os)."""
    path = ROOT / "cdk" / "stacks" / "constants.py"
    spec = importlib.util.spec_from_file_location("_lp_cdk_constants", path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def _lambda_function_names() -> tuple[str, ...]:
    """The platform's Lambda name vocabulary — ci/lambda_map.json, the one map CI deploys from."""
    with open(ROOT / "ci" / "lambda_map.json", encoding="utf-8") as fh:
        lmap = json.load(fh)
    return tuple(sorted({entry["function"] for entry in lmap["lambdas"].values()}))


_C = _load_constants()
ACCOUNT: str = _C.ACCT
PLATFORM_SLUG = "life-platform"  # the namespace token; the derivation test pins it to constants.TABLE_NAME
# Regions the platform's stacks live in: the default (cdk/app.py `region`), the CloudFront
# stack's us-east-1 (a string literal in app.py by #1816's rule), the backup replica's region.
PLATFORM_REGIONS: tuple[str, ...] = tuple(dict.fromkeys((_C.REGION, "us-east-1", _C.RAW_BACKUP_REGION)))
LAMBDA_NAMES: tuple[str, ...] = _lambda_function_names()


@dataclass(frozen=True)
class NamespaceFamily:
    name: str
    patterns: tuple[str, ...]  # fnmatchcase patterns over the RESOLVED ARN string
    since: str
    why: str


def _regional(fmt: str) -> tuple[str, ...]:
    return tuple(fmt.format(region=r, acct=ACCOUNT) for r in PLATFORM_REGIONS)


def _build_namespace() -> tuple[NamespaceFamily, ...]:
    lam: list[str] = list(_regional(f"arn:aws:lambda:{{region}}:{{acct}}:function:{PLATFORM_SLUG}-*"))
    logs: list[str] = list(_regional(f"arn:aws:logs:{{region}}:{{acct}}:log-group:/aws/lambda/{PLATFORM_SLUG}-*"))
    for name in LAMBDA_NAMES:
        lam += _regional(f"arn:aws:lambda:{{region}}:{{acct}}:function:{name}")
        lam += _regional(f"arn:aws:lambda:{{region}}:{{acct}}:function:{name}:*")
        logs += _regional(f"arn:aws:logs:{{region}}:{{acct}}:log-group:/aws/lambda/{name}")
        logs += _regional(f"arn:aws:logs:{{region}}:{{acct}}:log-group:/aws/lambda/{name}:*")
    return (
        NamespaceFamily(
            "dynamodb-table",
            (
                f"arn:aws:dynamodb:{_C.REGION}:{ACCOUNT}:table/{_C.TABLE_NAME}",
                f"arn:aws:dynamodb:{_C.REGION}:{ACCOUNT}:table/{_C.TABLE_NAME}/index/*",
            ),
            "2026-08-30",
            "the single table (constants.TABLE_NAME) + its two sanctioned GSIs (ADR-097)",
        ),
        NamespaceFamily(
            "s3-platform-bucket",
            (f"arn:aws:s3:::{_C.S3_BUCKET}", f"arn:aws:s3:::{_C.S3_BUCKET}/*"),
            "2026-08-30",
            "the platform bucket (constants.S3_BUCKET); prefix scoping inside it is the grant author's job",
        ),
        NamespaceFamily(
            "s3-raw-backup-bucket",
            (f"arn:aws:s3:::{_C.RAW_BACKUP_BUCKET}", f"arn:aws:s3:::{_C.RAW_BACKUP_BUCKET}/*"),
            "2026-08-30",
            "the DIL-027 cross-region raw/ replica (constants.RAW_BACKUP_BUCKET)",
        ),
        NamespaceFamily(
            "secrets",
            _regional(f"arn:aws:secretsmanager:{{region}}:{{acct}}:secret:{PLATFORM_SLUG}/*"),
            "2026-08-30",
            "every credential lives under the life-platform/ prefix (CLAUDE.md: Secrets Manager only)",
        ),
        NamespaceFamily(
            "lambda-functions",
            tuple(lam),
            "2026-08-30",
            "life-platform-* plus every function name in ci/lambda_map.json (most names are bare, e.g. daily-brief)",
        ),
        NamespaceFamily(
            "sns-topics",
            _regional(f"arn:aws:sns:{{region}}:{{acct}}:{PLATFORM_SLUG}-*"),
            "2026-08-30",
            "life-platform-alerts / -alerts-digest and siblings",
        ),
        NamespaceFamily(
            "sqs-queues",
            _regional(f"arn:aws:sqs:{{region}}:{{acct}}:{PLATFORM_SLUG}-*"),
            "2026-08-30",
            "the ingestion DLQ and the per-function DLQs (#2655 class — the 08-15 strand was exactly this grant)",
        ),
        NamespaceFamily(
            "log-groups",
            tuple(logs),
            "2026-08-30",
            "/aws/lambda/<function> for the same function vocabulary",
        ),
        NamespaceFamily(
            "ssm-parameters",
            _regional(f"arn:aws:ssm:{{region}}:{{acct}}:parameter/{PLATFORM_SLUG}/*"),
            "2026-08-30",
            "/life-platform/budget-tier, /remediation-mode, /experiment-cycle — the platform's own SSM tree",
        ),
        NamespaceFamily(
            "kms-platform-key",
            (f"arn:aws:kms:{_C.REGION}:{ACCOUNT}:key/{_C.KMS_KEY_ID}",),
            "2026-08-30",
            "the one platform CMK (constants.KMS_KEY_ID) every table/secret reader already holds Decrypt on",
        ),
    )


NAMESPACE_FAMILIES: tuple[NamespaceFamily, ...] = _build_namespace()

# Actions a NEW or GROWN Allow may never carry, lowercase fnmatch patterns keyed to why.
# Bare "*" and service-wide "svc:*" are a separate rule (`_action_problem`) because a
# fnmatch pattern of "*" would match everything. A partial-wildcard action (s3:GetObject*,
# the shape CDK's grant helpers emit) is admitted only if its literal prefix cannot overlap
# any pattern here — see `_action_problem`.
FORBIDDEN_ACTION_PATTERNS: dict[str, str] = {
    "iam:*": "any IAM action is privilege administration (iam:PassRole is the classic escalation)",
    "sts:*": "role assumption/federation is a lateral-movement primitive",
    "organizations:*": "account-structure control",
    "account:*": "account-level settings",
    "cloudformation:*": "CFN executes as the Administrator cfn-exec role — any stack mutation is admin by proxy",
    "lambda:createfunction*": "creating a function with a chosen role = arbitrary code under that role",
    "lambda:updatefunction*": "code/config swap on another function (env vars, handler, role)",
    "lambda:deletefunction*": "destructive and irreversible",
    "lambda:addpermission": "resource-based grant to an external principal",
    "lambda:removepermission": "resource-policy edit",
    "lambda:putfunction*": "concurrency / event-invoke / code-signing config mutation",
    "lambda:publishlayerversion": "layer injection into other functions' runtimes",
    "lambda:addlayerversionpermission": "layer sharing across functions",
    "lambda:*eventsourcemapping": "wiring another function to a data source",
    "events:put*": "scheduling arbitrary invocations / rewriting targets",
    "events:delete*": "destructive and irreversible",
    "events:remove*": "target removal",
    "events:disable*": "silently turning a cron off",
    "events:enable*": "turning a parked cron back on (Garmin, ADR-074)",
    "kms:putkeypolicy": "key-policy = the key's own IAM",
    "kms:schedulekeydeletion": "destructive and irreversible",
    "kms:disablekey": "destructive and irreversible",
    "kms:createkey": "new key material outside the registry",
    "kms:creategrant": "delegated key access",
    "s3:putbucketpolicy": "bucket-policy = resource IAM (ADR-032/046 delete-protection lives there)",
    "s3:deletebucketpolicy": "removes the delete-protection policy",
    "s3:putbucketacl": "bucket ACL grant (public-read)",
    "s3:putobjectacl": "object ACL grant (public-read)",
    "s3:putbucketpublicaccessblock": "public-access posture",
    "s3:putaccountpublicaccessblock": "account public-access posture",
    "s3:deletebucket": "destructive and irreversible",
    "s3:putbucketversioning": "can suspend versioning under raw/ (the replica's basis)",
    "s3:putreplicationconfiguration": "rewires the DIL-027 replica",
    "s3:putlifecycleconfiguration": "can expire raw/ objects",
    "dynamodb:deletetable": "destructive and irreversible",
    "dynamodb:updatetable": "GSI/stream/capacity mutation (ADR-097: a new GSI needs an ADR)",
    "dynamodb:updatecontinuousbackups": "can disable PITR",
    "dynamodb:deletebackup": "destructive and irreversible",
    "secretsmanager:deletesecret": "destructive and irreversible",
    "secretsmanager:putresourcepolicy": "secret resource-policy = resource IAM",
    "secretsmanager:createsecret": "new credential outside the reviewed set",
    "sns:addpermission": "topic resource-policy grant",
    "sns:settopicattributes": "topic policy lives in attributes",
    "sqs:addpermission": "queue resource-policy grant",
    "sqs:setqueueattributes": "queue policy lives in attributes",
    "logs:deleteloggroup": "destructive (audit trail)",
    "logs:putresourcepolicy": "log resource-policy",
    "ssm:deleteparameter": "destructive and irreversible",
}


# Non-IAM template churn that may ride alongside an additive IAM change without demoting
# the stack to OWNER-REQUIRED. Everything not listed here is "CI cannot ship it".
# (type, property) → dated reason.  `logical_id_prefix` narrows the LogRetention exception.
@dataclass(frozen=True)
class Tolerance:
    resource_type: str
    prop: str | None  # None = the resource-level `Metadata` block
    logical_id_prefix: str
    since: str
    why: str


TOLERATED_NON_IAM: tuple[Tolerance, ...] = (
    Tolerance(
        "AWS::Lambda::Function",
        "Code",
        "",
        "2026-08-30",
        "asset-hash churn — the bundle carries its commit (#2377) so Code moves every commit; "
        "CI's code path (deploy_lambda.sh / deploy_fleet.sh) ships exactly this class already (#2993)",
    ),
    Tolerance(
        "AWS::Lambda::Function",
        "Runtime",
        "LogRetention",
        "2026-08-30",
        "the CDK-internal LogRetention singleton's Runtime is chosen by aws-cdk-lib's regionalFact, not by "
        "any merged config (#2468; classify_cdk_diff.py reports it as a ::notice for the same reason)",
    ),
    Tolerance("AWS::CDK::Metadata", "Analytics", "", "2026-08-30", "CDK's construct-usage telemetry string; moves on every synth"),
    Tolerance("*", None, "", "2026-08-30", "resource-level Metadata (aws:cdk:path, aws:asset:*) is synth bookkeeping, not configuration"),
)

# Resource types whose ANY change is IAM-relevant (a resource-based policy or an identity).
RESOURCE_POLICY_TYPES: frozenset[str] = frozenset(
    {
        "AWS::Lambda::Permission",
        "AWS::Lambda::LayerVersionPermission",
        "AWS::Lambda::Url",
        "AWS::S3::BucketPolicy",
        "AWS::S3::AccessPoint",
        "AWS::SQS::QueuePolicy",
        "AWS::SNS::TopicPolicy",
        "AWS::KMS::Key",
        "AWS::KMS::Alias",
        "AWS::SecretsManager::ResourcePolicy",
        "AWS::Logs::ResourcePolicy",
        "AWS::Events::EventBusPolicy",
    }
)
# Property names on ANY resource whose change is an IAM change (role swap, boundary, key policy).
IAM_PROPERTY_NAMES: frozenset[str] = frozenset(
    {
        "Role",
        "RoleArn",
        "ExecutionRoleArn",
        "PermissionsBoundary",
        "ManagedPolicyArns",
        "AssumeRolePolicyDocument",
        "Policies",
        "PolicyDocument",
        "KeyPolicy",
    }
)
_ROLE_PROP_CLASS = {
    "AssumeRolePolicyDocument": "trust-policy-edit",
    "ManagedPolicyArns": "managed-policy-attachment",
    "PermissionsBoundary": "permissions-boundary-edit",
    "Policies": "inline-role-policy-edit",
}


def registry_fingerprint() -> str:
    """sha256 over the registry data — the ledger records WHICH allowed shape admitted a change."""
    blob = json.dumps(
        {
            "namespace": [asdict(f) for f in NAMESPACE_FAMILIES],
            "forbidden": FORBIDDEN_ACTION_PATTERNS,
            "tolerated": [asdict(t) for t in TOLERATED_NON_IAM],
            "resource_policy_types": sorted(RESOURCE_POLICY_TYPES),
            "iam_property_names": sorted(IAM_PROPERTY_NAMES),
        },
        sort_keys=True,
    )
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


# ═══════════════════════════════════════════════════════════════════════════════
# Verdict types
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass
class Finding:
    kind: str  # the forbidden shape, e.g. "deny-removed", "trust-policy-edit", "out-of-namespace-resource"
    logical_id: str
    detail: str


@dataclass
class Admitted:
    logical_id: str  # the AWS::IAM::Policy resource
    role_refs: list[str]
    sid: str
    actions: list[str]
    resources: list[str]
    how: str  # "new-statement" | "grown-statement"


@dataclass
class StackVerdict:
    stack: str
    verdict: str = OWNER
    findings: list[Finding] = field(default_factory=list)
    admitted: list[Admitted] = field(default_factory=list)
    pending_non_iam: list[str] = field(default_factory=list)  # advisory when no IAM change; blocking with one
    unevaluable: str | None = None


# ═══════════════════════════════════════════════════════════════════════════════
# Resource resolution + statement predicates
# ═══════════════════════════════════════════════════════════════════════════════

_PSEUDO = {"AWS::Partition": "aws", "AWS::URLSuffix": "amazonaws.com"}
# GetAtt/Ref → ARN, by type. Only resources with a LITERAL name property resolve; a
# CFN-generated name is unknowable from the template → unresolvable → OWNER-REQUIRED.
_ARN_BUILDERS = {
    "AWS::S3::Bucket": ("BucketName", "arn:aws:s3:::{name}"),
    "AWS::SQS::Queue": ("QueueName", "arn:aws:sqs:{region}:{acct}:{name}"),
    "AWS::SNS::Topic": ("TopicName", "arn:aws:sns:{region}:{acct}:{name}"),
    "AWS::DynamoDB::Table": ("TableName", "arn:aws:dynamodb:{region}:{acct}:table/{name}"),
    "AWS::Lambda::Function": ("FunctionName", "arn:aws:lambda:{region}:{acct}:function:{name}"),
    "AWS::Logs::LogGroup": ("LogGroupName", "arn:aws:logs:{region}:{acct}:log-group:{name}:*"),
    "AWS::SecretsManager::Secret": ("Name", "arn:aws:secretsmanager:{region}:{acct}:secret:{name}-*"),
}
# What a bare Ref returns for each type — an ARN for some, a NAME for others (used inside Fn::Join).
_REF_IS_ARN = {"AWS::SNS::Topic", "AWS::SecretsManager::Secret"}
_REF_IS_NAME = {"AWS::S3::Bucket", "AWS::DynamoDB::Table", "AWS::Lambda::Function", "AWS::Logs::LogGroup"}


@dataclass(frozen=True)
class Ctx:
    region: str
    account: str
    resources: dict[str, Any]  # the synthesized template's Resources (for Ref/GetAtt lookups)


def _literal_name(ctx: Ctx, logical_id: str) -> tuple[str | None, str | None]:
    res = ctx.resources.get(logical_id)
    if not isinstance(res, dict):
        return None, None
    typ = res.get("Type")
    spec = _ARN_BUILDERS.get(typ)
    if not spec:
        return typ, None
    name = (res.get("Properties") or {}).get(spec[0])
    return typ, (name if isinstance(name, str) else None)


def _arn_for(ctx: Ctx, logical_id: str) -> str | None:
    typ, name = _literal_name(ctx, logical_id)
    if typ is None or name is None:
        return None
    return _ARN_BUILDERS[typ][1].format(name=name, region=ctx.region, acct=ctx.account)


def resolve_resource(value: Any, ctx: Ctx) -> str | None:
    """Render a policy Resource entry to a plain string, or None if it cannot be known from the template."""
    if isinstance(value, str):
        return value
    if not isinstance(value, dict) or len(value) != 1:
        return None
    (fn, arg), *_ = value.items()
    if fn == "Ref":
        if arg == "AWS::Region":
            return ctx.region
        if arg == "AWS::AccountId":
            return ctx.account
        if arg in _PSEUDO:
            return _PSEUDO[arg]
        typ, name = _literal_name(ctx, arg)
        if typ in _REF_IS_ARN:
            return _arn_for(ctx, arg)
        if typ in _REF_IS_NAME:
            return name
        return None
    if fn == "Fn::GetAtt":
        if isinstance(arg, list) and len(arg) == 2 and arg[1] == "Arn":
            return _arn_for(ctx, arg[0])
        return None
    if fn == "Fn::Join":
        if not (isinstance(arg, list) and len(arg) == 2 and isinstance(arg[0], str) and isinstance(arg[1], list)):
            return None
        parts = [resolve_resource(p, ctx) for p in arg[1]]
        if any(p is None for p in parts):
            return None
        return arg[0].join(parts)  # type: ignore[arg-type]
    if fn == "Fn::Sub" and isinstance(arg, str):
        out = arg
        for m in set(re.findall(r"\$\{([^}]+)\}", arg)):
            if "." in m:
                lid, attr = m.split(".", 1)
                rep = _arn_for(ctx, lid) if attr == "Arn" else None
            else:
                rep = resolve_resource({"Ref": m}, ctx)
            if rep is None:
                return None
            out = out.replace("${" + m + "}", rep)
        return out
    return None


def resource_in_namespace(arn: str) -> str | None:
    """Return the family name that admits this ARN, else None. Case-sensitive on purpose."""
    for fam in NAMESPACE_FAMILIES:
        for pat in fam.patterns:
            if fnmatch.fnmatchcase(arn, pat):
                return fam.name
    return None


def _action_problem(action: Any) -> str | None:
    if not isinstance(action, str) or ":" not in action:
        return f"malformed-or-wildcard-action:{action!r}"
    a = action.strip().lower()
    if a == "*" or a.endswith(":*") or a.startswith("*"):
        return f"service-wide-wildcard-action:{action}"
    a_prefix = a.split("*", 1)[0]
    for pat in FORBIDDEN_ACTION_PATTERNS:
        if fnmatch.fnmatchcase(a, pat):
            return f"forbidden-action:{action} (matches {pat})"
        if "*" in a:
            p_prefix = pat.split("*", 1)[0]
            if a_prefix.startswith(p_prefix) or p_prefix.startswith(a_prefix):
                return f"wildcard-action-overlaps-forbidden:{action} (could match {pat})"
    return None


def _as_list(v: Any) -> list[Any]:
    if v is None:
        return []
    return list(v) if isinstance(v, list) else [v]


def _canon(v: Any) -> str:
    return json.dumps(v, sort_keys=True, separators=(",", ":"))


def statement_problems(stmt: Any, ctx: Ctx) -> list[str]:
    """Every way a NEW (or grown) statement fails the additive shape. Empty list = in shape."""
    if not isinstance(stmt, dict):
        return [f"statement-not-an-object:{stmt!r}"]
    problems: list[str] = []
    if stmt.get("Effect") != "Allow":
        problems.append(
            f"deny-added:{stmt.get('Sid', '<no sid>')}" if stmt.get("Effect") == "Deny" else f"effect-not-allow:{stmt.get('Effect')!r}"
        )
    for bad in ("Principal", "NotPrincipal", "NotAction", "NotResource"):
        if bad in stmt:
            problems.append(f"inverted-or-principal-statement:{bad}")
    actions = _as_list(stmt.get("Action"))
    if not actions:
        problems.append("statement-without-action")
    for a in actions:
        p = _action_problem(a)
        if p:
            problems.append(p)
    resources = _as_list(stmt.get("Resource"))
    if not resources:
        problems.append("statement-without-resource")
    for r in resources:
        rendered = resolve_resource(r, ctx)
        if rendered is None:
            problems.append(f"unresolvable-resource:{_canon(r)}")
        elif rendered.strip() == "*" or rendered.startswith("*"):
            problems.append("wildcard-resource:*")
        elif resource_in_namespace(rendered) is None:
            problems.append(f"out-of-namespace-resource:{rendered}")
    if "Condition" in stmt and not isinstance(stmt["Condition"], dict):
        problems.append("malformed-condition")
    return problems


def _stmt_key(s: dict) -> str:
    return _canon({"Effect": s.get("Effect"), "Sid": s.get("Sid"), "Condition": s.get("Condition")})


def _admit(logical_id: str, role_refs: list[str], stmt: dict, ctx: Ctx, how: str) -> Admitted:
    return Admitted(
        logical_id=logical_id,
        role_refs=role_refs,
        sid=str(stmt.get("Sid", "")),
        actions=[str(a) for a in _as_list(stmt.get("Action"))],
        resources=[resolve_resource(r, ctx) or _canon(r) for r in _as_list(stmt.get("Resource"))],
        how=how,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Resource-level evaluation
# ═══════════════════════════════════════════════════════════════════════════════


def _role_refs(props: dict, ctx: Ctx, old_resources: dict[str, Any] | None) -> tuple[list[str], list[str]]:
    """Return (role logical ids, problems). A policy may bind ONLY to in-template roles that
    already exist live, unchanged — never to users/groups, never by name."""
    problems: list[str] = []
    for bad in ("Users", "Groups"):
        if props.get(bad):
            problems.append(f"policy-bound-to-{bad.lower()}")
    refs: list[str] = []
    roles = props.get("Roles")
    if not isinstance(roles, list) or not roles:
        problems.append("policy-without-role-binding")
        return refs, problems
    for r in roles:
        lid = r.get("Ref") if isinstance(r, dict) and len(r) == 1 else None
        if not lid or (ctx.resources.get(lid) or {}).get("Type") != "AWS::IAM::Role":
            problems.append(f"policy-bound-outside-template:{_canon(r)}")
            continue
        if old_resources is not None and old_resources.get(lid) != ctx.resources.get(lid):
            problems.append(f"policy-bound-to-new-or-changed-role:{lid}")
        refs.append(lid)
    return refs, problems


def evaluate_policy(
    logical_id: str, old: dict | None, new: dict, ctx: Ctx, old_resources: dict[str, Any]
) -> tuple[list[Admitted], list[Finding]]:
    """AWS::IAM::Policy — new or modified. Returns (admitted deltas, findings)."""
    findings: list[Finding] = []
    admitted: list[Admitted] = []
    new_props = new.get("Properties") or {}
    role_refs, problems = _role_refs(new_props, ctx, old_resources)
    for p in problems:
        findings.append(Finding(p.split(":", 1)[0], logical_id, p))
    old_props = (old or {}).get("Properties") or {}
    if old is not None:
        for prop in set(old_props) | set(new_props):
            if prop == "PolicyDocument":
                continue
            if old_props.get(prop) != new_props.get(prop):
                findings.append(Finding("policy-binding-changed", logical_id, f"{prop} differs"))
        for key in set(old) | set(new):
            if key in ("Properties", "Metadata"):
                continue
            if old.get(key) != new.get(key):
                findings.append(Finding("policy-resource-attribute-changed", logical_id, key))
    doc_new = new_props.get("PolicyDocument")
    if not isinstance(doc_new, dict) or not isinstance(doc_new.get("Statement"), list):
        findings.append(Finding("unparseable-policy-document", logical_id, "PolicyDocument.Statement is not a list"))
        return admitted, findings
    if doc_new.get("Version") not in (None, "2012-10-17"):
        findings.append(Finding("policy-version-unexpected", logical_id, str(doc_new.get("Version"))))
    doc_old = old_props.get("PolicyDocument") if old is not None else {}
    stmts_old = list((doc_old or {}).get("Statement") or [])
    remaining = list(doc_new["Statement"])
    for s_old in stmts_old:
        if s_old in remaining:
            remaining.remove(s_old)
            continue
        label = f"{logical_id}#{s_old.get('Sid', '<no sid>') if isinstance(s_old, dict) else '?'}"
        if not isinstance(s_old, dict) or s_old.get("Effect") == "Deny":
            findings.append(Finding("deny-removed-or-altered", logical_id, f"{label}: a Deny statement is missing or changed"))
            continue
        grown = [
            s
            for s in remaining
            if isinstance(s, dict)
            and _stmt_key(s) == _stmt_key(s_old)
            and {_canon(a) for a in _as_list(s_old.get("Action"))} <= {_canon(a) for a in _as_list(s.get("Action"))}
            and {_canon(r) for r in _as_list(s_old.get("Resource"))} <= {_canon(r) for r in _as_list(s.get("Resource"))}
            and not (set(s_old) - set(s))
        ]
        if not grown:
            findings.append(Finding("allow-removed-or-narrowed", logical_id, f"{label}: an existing Allow is missing or narrowed"))
            continue
        s_new = grown[0]
        remaining.remove(s_new)
        # A grown statement is admitted only if the WHOLE resulting statement is in shape —
        # a new action on a statement whose resource is "*" is a new grant on "*".
        probs = statement_problems(s_new, ctx)
        if probs:
            for p in probs:
                findings.append(Finding(p.split(":", 1)[0], logical_id, f"{label} (grown): {p}"))
        else:
            admitted.append(_admit(logical_id, role_refs, s_new, ctx, "grown-statement"))
    for s_new in remaining:
        label = f"{logical_id}#{s_new.get('Sid', '<no sid>') if isinstance(s_new, dict) else '?'}"
        probs = statement_problems(s_new, ctx)
        if probs:
            for p in probs:
                findings.append(Finding(p.split(":", 1)[0], logical_id, f"{label} (new): {p}"))
        else:
            admitted.append(_admit(logical_id, role_refs, s_new, ctx, "new-statement"))
    return admitted, findings


def is_iam_relevant_type(typ: str) -> bool:
    if typ.startswith("AWS::IAM::") or typ in RESOURCE_POLICY_TYPES:
        return True
    if typ.startswith("AWS::CloudFront::"):
        return False  # CachePolicy / ResponseHeadersPolicy — the R8-ST6 grep's measured false positive
    return any(tok in typ for tok in ("Policy", "Permission"))


def _tolerated(typ: str, logical_id: str, prop: str | None) -> bool:
    for t in TOLERATED_NON_IAM:
        if t.resource_type not in ("*", typ):
            continue
        if t.prop != prop:
            continue
        if t.logical_id_prefix and not logical_id.startswith(t.logical_id_prefix):
            continue
        return True
    return False


def evaluate_templates(stack: str, deployed: Any, synthesized: Any, region: str, account: str) -> StackVerdict:
    """The pure core: two templates in, one StackVerdict out. Never raises on template content."""
    v = StackVerdict(stack=stack)
    if not (isinstance(deployed, dict) and isinstance(synthesized, dict)):
        v.unevaluable = "template is not a JSON object"
        v.findings.append(Finding("unevaluable", stack, v.unevaluable))
        return v
    dres, sres = deployed.get("Resources"), synthesized.get("Resources")
    if not isinstance(dres, dict) or not isinstance(sres, dict):
        v.unevaluable = "template has no Resources object"
        v.findings.append(Finding("unevaluable", stack, v.unevaluable))
        return v
    ctx = Ctx(region=region, account=account, resources=sres)
    iam_touched = False

    for section in ("Parameters", "Rules", "Conditions", "Mappings", "Outputs", "Transform"):
        if deployed.get(section) != synthesized.get(section):
            v.pending_non_iam.append(f"template.{section}")

    for lid in sorted(set(dres) | set(sres)):
        old, new = dres.get(lid), sres.get(lid)
        typ = str(((new if new is not None else old) or {}).get("Type", "?"))
        if old is None:
            if typ == "AWS::IAM::Policy":
                iam_touched = True
                adm, fnd = evaluate_policy(lid, None, new, ctx, dres)
                v.admitted += adm
                v.findings += fnd
            elif is_iam_relevant_type(typ):
                iam_touched = True
                v.findings.append(Finding("new-role-or-resource-policy" if typ == "AWS::IAM::Role" else "new-iam-resource", lid, typ))
            else:
                v.pending_non_iam.append(f"{lid} ({typ}) added")
            continue
        if new is None:
            if is_iam_relevant_type(typ):
                iam_touched = True
                v.findings.append(Finding("iam-resource-removed", lid, typ))
            else:
                v.pending_non_iam.append(f"{lid} ({typ}) removed")
            continue
        if old == new:
            continue
        if old.get("Type") != new.get("Type"):
            iam_touched = iam_touched or is_iam_relevant_type(typ) or is_iam_relevant_type(str(old.get("Type")))
            (v.findings if is_iam_relevant_type(typ) else v.pending_non_iam).append(
                Finding("resource-type-changed", lid, f"{old.get('Type')} → {typ}") if is_iam_relevant_type(typ) else f"{lid} type changed"
            )
            continue
        op, np_ = old.get("Properties") or {}, new.get("Properties") or {}
        changed_props = sorted(p for p in set(op) | set(np_) if op.get(p) != np_.get(p))
        changed_attrs = sorted(k for k in (set(old) | set(new)) - {"Properties"} if old.get(k) != new.get(k))
        if typ == "AWS::IAM::Policy":
            if changed_props or [k for k in changed_attrs if k != "Metadata"]:
                iam_touched = True
                adm, fnd = evaluate_policy(lid, old, new, ctx, dres)
                v.admitted += adm
                v.findings += fnd
            continue
        if typ == "AWS::IAM::Role":
            if changed_props or [k for k in changed_attrs if k != "Metadata"]:
                iam_touched = True
                for p in changed_props:
                    v.findings.append(Finding(_ROLE_PROP_CLASS.get(p, "role-property-edit"), lid, f"Role.{p} differs"))
                for k in changed_attrs:
                    if k != "Metadata":
                        v.findings.append(Finding("role-property-edit", lid, f"Role attribute {k} differs"))
            continue
        if is_iam_relevant_type(typ):
            if changed_props or [k for k in changed_attrs if k != "Metadata"]:
                iam_touched = True
                v.findings.append(Finding("iam-resource-modified", lid, f"{typ}: {', '.join(changed_props + changed_attrs)}"))
            continue
        for p in changed_props:
            if p in IAM_PROPERTY_NAMES:
                iam_touched = True
                v.findings.append(Finding("iam-property-edit", lid, f"{typ}.{p} differs"))
            elif not _tolerated(typ, lid, p):
                v.pending_non_iam.append(f"{lid} ({typ}).{p}")
        for k in changed_attrs:
            if k == "Metadata" and _tolerated(typ, lid, None):
                continue
            v.pending_non_iam.append(f"{lid} ({typ}) attribute {k}")

    if not iam_touched:
        v.verdict = NO_CHANGE
    elif v.findings:
        v.verdict = OWNER
    elif v.pending_non_iam:
        v.verdict = OWNER
        v.findings.append(
            Finding(
                "rides-with-non-iam-change",
                stack,
                "additive IAM shares the stack with changes CI may not ship: " + "; ".join(v.pending_non_iam),
            )
        )
    elif v.admitted:
        v.verdict = ALLOW
    else:
        v.verdict = NO_CHANGE
    return v


# ═══════════════════════════════════════════════════════════════════════════════
# Inputs: cdk.out manifest, deployed templates (dir or live), CLI
# ═══════════════════════════════════════════════════════════════════════════════


def read_manifest(synth_dir: Path) -> dict[str, tuple[Path, str, str]]:
    """stack name → (template path, account, region) from cdk.out/manifest.json."""
    with open(synth_dir / "manifest.json", encoding="utf-8") as fh:
        manifest = json.load(fh)
    out: dict[str, tuple[Path, str, str]] = {}
    for name, art in (manifest.get("artifacts") or {}).items():
        if art.get("type") != "aws:cloudformation:stack":
            continue
        env = str(art.get("environment", ""))
        m = re.fullmatch(r"aws://(\d+)/([a-z0-9-]+)", env)
        if not m:
            raise ValueError(f"{name}: unparseable environment {env!r}")
        out[name] = (synth_dir / art["properties"]["templateFile"], m.group(1), m.group(2))
    if not out:
        raise ValueError("manifest lists no CloudFormation stacks")
    return out


def _load_json_file(path: Path) -> Any:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def fetch_live_template(stack: str, region: str) -> Any:
    """Read-only: the template CDK last deployed, as CloudFormation stores it (Original stage)."""
    cmd = [
        "aws",
        "cloudformation",
        "get-template",
        "--stack-name",
        stack,
        "--template-stage",
        "Original",
        "--region",
        region,
        "--output",
        "json",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if proc.returncode != 0:
        raise RuntimeError(f"get-template failed for {stack} ({region}): {proc.stderr.strip()[:300]}")
    body = json.loads(proc.stdout).get("TemplateBody")
    if isinstance(body, str):  # a YAML body — CDK never deploys one; refuse rather than guess
        raise RuntimeError(f"{stack}: TemplateBody is not JSON")
    return body


def evaluate_all(synth_dir: Path, deployed_dir: Path | None, live: bool, only: list[str] | None) -> tuple[list[StackVerdict], bool]:
    """Returns (verdicts, unevaluable_seen). Any failure to obtain/parse a side is OWNER-REQUIRED."""
    verdicts: list[StackVerdict] = []
    unevaluable = False
    try:
        stacks = read_manifest(synth_dir)
    except Exception as exc:  # noqa: BLE001 — fail closed on ANY manifest problem
        v = StackVerdict(stack="<manifest>", unevaluable=f"cannot read synth manifest: {exc}")
        v.findings.append(Finding("unevaluable", "<manifest>", v.unevaluable))
        return [v], True
    names = only or sorted(stacks)
    for name in names:
        if name not in stacks:
            v = StackVerdict(stack=name, unevaluable="stack not in synth manifest")
            v.findings.append(Finding("unevaluable", name, v.unevaluable))
            verdicts.append(v)
            unevaluable = True
            continue
        tpath, account, region = stacks[name]
        try:
            if account != ACCOUNT:
                raise RuntimeError(f"synth environment account {account} is not the platform account")
            synthesized = _load_json_file(tpath)
            if live:
                deployed = fetch_live_template(name, region)
            elif deployed_dir is not None:
                deployed = _load_json_file(deployed_dir / f"{name}.template.json")
            else:
                raise RuntimeError("no deployed side given (--live or --deployed-dir)")
            verdicts.append(evaluate_templates(name, deployed, synthesized, region, account))
        except Exception as exc:  # noqa: BLE001 — fail closed
            v = StackVerdict(stack=name, unevaluable=f"{type(exc).__name__}: {exc}")
            v.findings.append(Finding("unevaluable", name, v.unevaluable))
            verdicts.append(v)
            unevaluable = True
    return verdicts, unevaluable


def render(verdicts: list[StackVerdict]) -> list[str]:
    out = ["═" * 72, f"  IAM additive gate (#{ISSUE}) — registry {registry_fingerprint()}", "═" * 72]
    for v in verdicts:
        out.append(f"{v.stack:28s} {v.verdict}")
        if v.unevaluable:
            out.append(f"    ✗ UNEVALUABLE (fails closed): {v.unevaluable}")
        for f in v.findings:
            out.append(f"    ✗ {f.kind:34s} {f.logical_id}: {f.detail}")
        for a in v.admitted:
            out.append(f"    ✓ admitted [{a.how}] {a.logical_id}#{a.sid or '-'} → roles {','.join(a.role_refs)}")
            out.append(f"        actions   {', '.join(a.actions)}")
            out.append(f"        resources {', '.join(a.resources)}")
        if v.verdict == NO_CHANGE and v.pending_non_iam:
            out.append(
                f"    ::warning title=Pending owner cdk deploy ({v.stack})::{v.stack} has non-IAM CDK changes CI does not ship: "
                + "; ".join(v.pending_non_iam[:12])
            )
    if any(v.verdict == OWNER for v in verdicts):
        out.append("")
        out.append("  OWNER-REQUIRED → " + OWNER_PATH)
    return out


def to_record(verdicts: list[StackVerdict]) -> dict[str, Any]:
    return {
        "gate": GATE_NAME,
        "issue": ISSUE,
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
        "git_sha": os.environ.get("GITHUB_SHA"),
        "run_id": os.environ.get("GITHUB_RUN_ID"),
        "actor": os.environ.get("GITHUB_ACTOR"),
        "registry_fingerprint": registry_fingerprint(),
        "overall": overall(verdicts),
        "stacks": {v.stack: asdict(v) for v in verdicts},
    }


def overall(verdicts: list[StackVerdict]) -> str:
    if any(v.verdict == OWNER for v in verdicts):
        return OWNER
    if any(v.verdict == ALLOW for v in verdicts):
        return ALLOW
    return NO_CHANGE


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--synth-dir", required=True, type=Path, help="cdk.out directory (manifest.json + templates)")
    side = ap.add_mutually_exclusive_group(required=True)
    side.add_argument("--live", action="store_true", help="fetch deployed templates read-only via aws cloudformation get-template")
    side.add_argument("--deployed-dir", type=Path, help="directory of <Stack>.template.json deployed-side templates")
    ap.add_argument("--stacks", nargs="*", help="evaluate only these stacks (default: every stack in the manifest)")
    ap.add_argument("--json", type=Path, help="write the machine-readable decision record here")
    ap.add_argument("--github-output", type=Path, help="append iam_gate_verdict= and iam_additive_stacks= lines here")
    ap.add_argument("--expect-converged", action="store_true", help="post-deploy proof: exit 1 unless every stack is NO-IAM-CHANGE")
    args = ap.parse_args(argv[1:])

    verdicts, unevaluable = evaluate_all(args.synth_dir, args.deployed_dir, args.live, args.stacks or None)
    for line in render(verdicts):
        print(line)
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(to_record(verdicts), indent=2, default=str), encoding="utf-8")
    allow_stacks = [v.stack for v in verdicts if v.verdict == ALLOW]
    if args.github_output:
        with open(args.github_output, "a", encoding="utf-8") as fh:
            fh.write(f"iam_gate_verdict={overall(verdicts)}\n")
            fh.write(f"iam_additive_stacks={' '.join(allow_stacks)}\n")
    if unevaluable:
        return 2
    if args.expect_converged:
        return 0 if all(v.verdict == NO_CHANGE for v in verdicts) else 1
    return 1 if overall(verdicts) == OWNER else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
