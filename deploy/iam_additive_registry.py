#!/usr/bin/env python3
"""deploy/iam_additive_registry.py — the allowed shape for CI-deployable IAM, as DATA (#2834).

This is the registry primitive of the additive-IAM gate (`deploy/iam_additive_gate.py`
evaluates; this module only *declares*). It was split out after the 2026-08-30 CISO review
(PR #3335) grew the forbidden list and added the S3 / wildcard rules — the evaluator would
otherwise have crossed the 1,200-line module ceiling (#1665), and the charter's rule is
extraction, never a new baseline.

Everything here derives from an existing source of truth rather than a retyped copy:

  account / region / table / bucket / key   cdk/stacks/constants.py (loaded by FILE — no aws_cdk import)
  Lambda name vocabulary                    ci/lambda_map.json (the map CI deploys from; most names are bare)
  non-default stack regions                 the string literals cdk/app.py carries by #1816's rule
  S3 protected (action, prefix) pairs       deploy/bucket_policy.json's Deny statements (review R2 — the
                                            bucket policy itself binds only matthew-admin, so the gate
                                            re-applies its intent to Lambda-role grants)
  the CDK asset bucket a Lambda may load    `cdk-<qualifier>-assets-<acct>-<region>`, qualifier read
  code from (review R1)                     from the synthesized template's own BootstrapVersion parameter

The RATCHET over this module is `tests/test_iam_additive_gate_guards_2834.py`, whose
baselines are parsed from the fenced ```json iam-additive-gate-baseline``` block in the
ADR-065 amendment of 2026-08-30 (docs/DECISIONS.md) — review R5: a widening has to appear
where the owner reads, in the same PR, not only in a test file. FORBIDDEN / RESOURCE_POLICY
/ IAM_PROPERTY sets may only grow; NAMESPACE / TOLERANCE sets may only shrink.
"""

from __future__ import annotations

import fnmatch
import hashlib
import importlib.util
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent


def _load_constants():
    """cdk/stacks/constants.py, loaded by FILE so no aws_cdk import is needed (it only imports os)."""
    path = ROOT / "cdk" / "stacks" / "constants.py"
    spec = importlib.util.spec_from_file_location("_lp_cdk_constants", path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def _as_list(v: Any) -> list[Any]:
    if v is None:
        return []
    return list(v) if isinstance(v, list) else [v]


def _lambda_function_names() -> tuple[str, ...]:
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


# ═══════════════════════════════════════════════════════════════════════════════
# Namespace — which ARNs a new Allow may name
# ═══════════════════════════════════════════════════════════════════════════════


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
            "the platform bucket (constants.S3_BUCKET); mutating actions are further bounded by S3_PROTECTED "
            "(derived from deploy/bucket_policy.json) and must be prefix-scoped — review R2. The DIL-027 raw/ "
            "replica bucket was REMOVED from the namespace by the same review: no Lambda role reads or writes it",
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
            "/life-platform/budget-tier, /remediation-mode, /experiment-cycle — READ side only: ssm:PutParameter "
            "is forbidden (review R3 — the kill-switch and the budget tier are control-plane state)",
        ),
        NamespaceFamily(
            "kms-platform-key",
            (f"arn:aws:kms:{_C.REGION}:{ACCOUNT}:key/{_C.KMS_KEY_ID}",),
            "2026-08-30",
            "the one platform CMK (constants.KMS_KEY_ID) every table/secret reader already holds Decrypt on",
        ),
    )


NAMESPACE_FAMILIES: tuple[NamespaceFamily, ...] = _build_namespace()


def resource_in_namespace(arn: str) -> str | None:
    """Return the family name that admits this ARN, else None. Case-sensitive on purpose."""
    for fam in NAMESPACE_FAMILIES:
        for pat in fam.patterns:
            if fnmatch.fnmatchcase(arn, pat):
                return fam.name
    return None


# ── N3 (review): what a WILDCARD inside an in-namespace resource means ──────────────
# The review found `function:life-platform-*` admitted and untested either way. The
# decision, made explicit here: a resource that itself contains `*` is admitted ONLY in
# the shapes below — data-plane key/version/stream patterns that name ONE object family
# inside ONE named resource. A NAME-PREFIX wildcard across the platform's control plane
# (`function:life-platform-*`, `life-platform-*` topics/queues,
# `log-group:/aws/lambda/life-platform-*`) is REFUSED: it grants over every function the
# platform will ever have, including ones that do not exist yet and were never reviewed.
# The namespace families still admit those same prefixes for CONCRETE names — which is
# the whole point of a vocabulary derived from ci/lambda_map.json.
_REGION_RE = "[a-z0-9-]+"
WILDCARD_RESOURCE_SHAPES: tuple[tuple[str, str, str], ...] = (
    # (shape name, regex fullmatched against the RESOLVED ARN, why)
    (
        "s3-object-key",
        rf"arn:aws:s3:::{re.escape(_C.S3_BUCKET)}/.*",
        "an object-key pattern inside the one platform bucket; MUTATING actions are additionally "
        "bounded by S3_PROTECTED and may not use the unscoped bucket/* form (review R2)",
    ),
    (
        "secret-name-or-version",
        rf"arn:aws:secretsmanager:{_REGION_RE}:\d+:secret:{PLATFORM_SLUG}/[^*?]*\*",
        "life-platform/* or life-platform/<name>-* (Secrets Manager appends a 6-char version suffix)",
    ),
    (
        "ssm-parameter-tree",
        rf"arn:aws:ssm:{_REGION_RE}:\d+:parameter/{PLATFORM_SLUG}/(?:[^*?]+/)?\*",
        "/life-platform/* or one level deeper — the platform's own parameter tree, read side only",
    ),
    (
        "dynamodb-index",
        rf"arn:aws:dynamodb:{_REGION_RE}:\d+:table/{re.escape(_C.TABLE_NAME)}/index/\*",
        "the single table's two sanctioned GSIs (ADR-097)",
    ),
    (
        "log-group-streams",
        rf"arn:aws:logs:{_REGION_RE}:\d+:log-group:/aws/lambda/[^*?:]+:\*",
        "the streams of ONE named log group — the group name itself carries no wildcard",
    ),
)


def wildcard_resource_shape(arn: str) -> str | None:
    """The established shape that admits this wildcard-bearing ARN, else None (review N3)."""
    for name, pattern, _why in WILDCARD_RESOURCE_SHAPES:
        if re.fullmatch(pattern, arn):
            return name
    return None


# ═══════════════════════════════════════════════════════════════════════════════
# S3 (review R2) — mutating actions are prefix-scoped and never touch protected prefixes
# ═══════════════════════════════════════════════════════════════════════════════

S3_READ_ACTION_PREFIXES: tuple[str, ...] = ("s3:get", "s3:list", "s3:head", "s3:describe")


def _load_s3_protected() -> tuple[tuple[str, str, str], ...]:
    """(denied action family, key prefix, Sid) for every Deny in deploy/bucket_policy.json.

    The bucket policy's Deny is principal-scoped to matthew-admin — it is NOT a backstop for
    Lambda roles (review R2). The gate re-applies the same (action x prefix) intent to any
    grant CI would ship. DERIVED, so a prefix added to the policy is protected here the same
    day. The denied action is widened to its family (`s3:DeleteObject` -> `s3:deleteobject*`)
    so DeleteObjectVersion / DeleteObjectTagging cannot walk around the same intent.
    """
    with open(ROOT / "deploy" / "bucket_policy.json", encoding="utf-8") as fh:
        policy = json.load(fh)
    out: set[tuple[str, str, str]] = set()
    for st in policy.get("Statement", []):
        if st.get("Effect") != "Deny":
            continue
        actions = [str(a).lower() for a in _as_list(st.get("Action"))]
        for res in _as_list(st.get("Resource")):
            m = re.fullmatch(rf"arn:aws:s3:::{re.escape(_C.S3_BUCKET)}/(.+?)/\*", str(res))
            if not m:
                continue
            for a in actions:
                out.add((a if a.endswith("*") else a + "*", m.group(1) + "/", str(st.get("Sid", ""))))
    if not out:
        raise RuntimeError("deploy/bucket_policy.json yielded no Deny (action, prefix) pairs — refusing an empty protection set")
    return tuple(sorted(out))


S3_PROTECTED: tuple[tuple[str, str, str], ...] = _load_s3_protected()

# Prefixes CI's own paths already write AND delete end to end, so a Lambda-role grant on one
# of them stays inside what the platform does today rather than being a new capability:
# `site/*` (the site deploy syncs it, deletions included) and `remediation-log/*` (the agent
# and this very gate write it). Named here as an EXPLICIT decision — the review listed both
# as currently admitted, and the answer is "yes, still admitted, because they are
# prefix-scoped and the bucket policy does not deny them" — not an oversight. Adding either
# to deploy/bucket_policy.json's Deny list flips them here the same day, automatically.
S3_MUTABLE_BY_CI_TODAY: tuple[str, ...] = ("site/", "remediation-log/")


def _actions_overlap(action: str, pattern: str) -> bool:
    """True when a (possibly wildcarded) action could match a (possibly wildcarded) pattern."""
    if fnmatch.fnmatchcase(action, pattern):
        return True
    if "*" not in action and "*" not in pattern:
        return False
    a_prefix, p_prefix = action.split("*", 1)[0], pattern.split("*", 1)[0]
    return a_prefix.startswith(p_prefix) or p_prefix.startswith(a_prefix)


def s3_grant_problem(action: str, arn: str) -> str | None:
    """Review R2: the extra bound on an S3 grant that is already inside the namespace.

    Returns None for read-only actions, for non-S3 actions and for non-S3 ARNs. Otherwise a
    named problem when the grant is unscoped (bare bucket / `bucket/*`) or reaches a prefix
    the bucket policy protects against the same action family.
    """
    a = action.strip().lower()
    if not a.startswith("s3:"):
        return None
    if any(a.startswith(p) for p in S3_READ_ACTION_PREFIXES):
        return None
    m = re.fullmatch(r"arn:aws:s3:::([^/]+)(?:/(.*))?", arn)
    if not m:
        return None
    key = m.group(2)
    if key is None or key.strip() in ("", "*"):
        return f"s3-mutating-action-on-unscoped-bucket:{action} on {arn} — a mutating S3 grant must name a key prefix"
    key_literal = key.split("*", 1)[0]
    for pattern, prefix, sid in S3_PROTECTED:
        if not _actions_overlap(a, pattern):
            continue
        if key_literal.startswith(prefix) or prefix.startswith(key_literal):
            return f"s3-protected-prefix:{action} on {arn} — bucket_policy.json Deny '{sid}' protects {prefix} against {pattern}"
    return None


# ═══════════════════════════════════════════════════════════════════════════════
# Forbidden actions — a NEW or GROWN Allow may never carry these (lowercase fnmatch)
# ═══════════════════════════════════════════════════════════════════════════════
# Bare "*" and service-wide "svc:*" are a separate rule (`iam_additive_gate._action_problem`)
# because a fnmatch pattern of "*" would match everything. Every pattern here has a
# non-empty literal prefix after the service colon (the ratchet asserts it), so the
# wildcard-overlap rule for partial-wildcard actions (s3:GetObject*) stays decidable.
FORBIDDEN_ACTION_PATTERNS: dict[str, str] = {
    "iam:*": "any IAM action is privilege administration (iam:PassRole is the classic escalation)",
    "sts:*": "role assumption/federation is a lateral-movement primitive",
    "organizations:*": "account-structure control",
    "account:*": "account-level settings",
    "cloudformation:*": "CFN executes as the Administrator cfn-exec role — any stack mutation is admin by proxy",
    # ── Lambda ──
    "lambda:createfunction*": "creating a function with a chosen role = arbitrary code under that role",
    "lambda:updatefunction*": "code/config swap on another function (env vars, handler, role)",
    "lambda:deletefunction*": "destructive and irreversible",
    "lambda:addpermission": "resource-based grant to an external principal",
    "lambda:removepermission": "resource-policy edit",
    "lambda:putfunction*": "concurrency / event-invoke / code-signing config mutation",
    "lambda:putprovisionedconcurrencyconfig": "review R3: spend + availability control plane",
    "lambda:putruntimemanagementconfig": "review R3: pins another function's runtime version",
    "lambda:publishlayerversion": "layer injection into other functions' runtimes",
    "lambda:addlayerversionpermission": "layer sharing across functions",
    "lambda:*eventsourcemapping": "wiring, rewiring or silently detaching another function's data source",
    # ── EventBridge ──
    "events:put*": "scheduling arbitrary invocations / rewriting targets",
    "events:delete*": "destructive and irreversible",
    "events:remove*": "target removal",
    "events:disable*": "silently turning a cron off",
    "events:enable*": "turning a parked cron back on (Garmin, ADR-074)",
    # ── KMS ──
    "kms:putkeypolicy": "key-policy = the key's own IAM",
    "kms:schedulekeydeletion": "destructive and irreversible",
    "kms:disablekey": "destructive and irreversible",
    "kms:createkey": "new key material outside the registry",
    "kms:creategrant": "delegated key access",
    "kms:replicatekey": "review R3: copies key material to another region",
    "kms:updateprimaryregion": "review R3: moves the key's home region",
    # ── S3 (review R2 grew this block) ──
    "s3:putbucketpolicy": "bucket-policy = resource IAM (ADR-032/046 delete-protection lives there)",
    "s3:deletebucketpolicy": "removes the delete-protection policy",
    "s3:putbucket*": "review R2: every bucket-level setting (ACL, notification, logging, versioning, object-lock, ownership …)",
    "s3:put*configuration": "review R2: encryption / lifecycle / replication / inventory / metrics / accelerate configuration",
    "s3:putbucketacl": "bucket ACL grant (public-read)",
    "s3:putobjectacl": "object ACL grant (public-read)",
    "s3:putobjectretention": "review R2: object-lock retention edit",
    "s3:putobjectlegalhold": "review R2: object-lock legal-hold edit",
    "s3:bypassgovernanceretention": "review R2: defeats governance-mode retention",
    "s3:deleteobjectversion*": "review R2: destroys the versioned history delete-protection relies on",
    "s3:putbucketpublicaccessblock": "public-access posture",
    "s3:putaccountpublicaccessblock": "account public-access posture",
    "s3:deletebucket": "destructive and irreversible",
    "s3:putbucketversioning": "can suspend versioning under raw/ (the replica's basis)",
    "s3:putreplicationconfiguration": "rewires the DIL-027 replica",
    "s3:putlifecycleconfiguration": "can expire raw/ objects",
    # ── DynamoDB ──
    "dynamodb:deletetable": "destructive and irreversible",
    "dynamodb:updatetable": "GSI/stream/capacity mutation (ADR-097: a new GSI needs an ADR)",
    "dynamodb:updatecontinuousbackups": "can disable PITR",
    "dynamodb:updatetimetolive": "review R3: a TTL flip silently expires or retains every row",
    "dynamodb:*kinesisstreamingdestination": "review R3: an exfiltration channel for the whole table",
    "dynamodb:createtablereplica": "review R3: a cross-region copy outside the registry",
    "dynamodb:restoretable*": "review R3: a restore overwrites live state",
    "dynamodb:importtable": "review R3: bulk-load into a new table",
    "dynamodb:deletebackup": "destructive and irreversible",
    # ── Secrets Manager ──
    "secretsmanager:deletesecret": "destructive and irreversible",
    "secretsmanager:putresourcepolicy": "secret resource-policy = resource IAM",
    "secretsmanager:createsecret": "new credential outside the reviewed set",
    "secretsmanager:putsecretvalue": "review R3: credential overwrite (token refreshers that need it are owner-deployed)",
    "secretsmanager:updatesecret*": "review R3: credential/metadata overwrite",
    "secretsmanager:rotatesecret": "review R3: triggers rotation under another principal",
    "secretsmanager:restoresecret": "review R3: undoes a deliberate deletion",
    "secretsmanager:replicatesecrettoregions": "review R3: copies a credential to another region",
    # ── SNS / SQS ──
    "sns:addpermission": "topic resource-policy grant",
    "sns:settopicattributes": "topic policy lives in attributes",
    "sns:subscribe": "review R3: adds a listener to the owner's alert stream",
    "sns:unsubscribe": "review R3: silently removes the owner's alert delivery",
    "sns:deletetopic": "review R3: destroys the alert channel",
    "sns:removepermission": "review R3: topic resource-policy edit",
    "sqs:addpermission": "queue resource-policy grant",
    "sqs:setqueueattributes": "queue policy lives in attributes",
    "sqs:deletequeue": "review R3: destroys a DLQ and its evidence",
    "sqs:purgequeue": "review R3: erases DLQ evidence",
    "sqs:removepermission": "review R3: queue resource-policy edit",
    # ── CloudWatch Logs ──
    "logs:deleteloggroup": "destructive (audit trail)",
    "logs:putresourcepolicy": "log resource-policy",
    "logs:putsubscriptionfilter": "review R3: an exfiltration channel for every log line",
    "logs:putdestination*": "review R3: cross-account log destination",
    "logs:putretentionpolicy": "review R3: shortens the security-log tier (#3278 asserts it weekly)",
    "logs:deleteretentionpolicy": "review R3: sets retention to never-expire / defeats the tier",
    "logs:deletelogstream": "review R3: erases evidence",
    # ── SSM ──
    "ssm:putparameter": "review R3: /life-platform/remediation-mode (kill-switch) and /budget-tier are control-plane state",
    "ssm:labelparameterversion": "review R3: parameter version pinning",
    "ssm:deleteparameter": "destructive and irreversible",
}


# ═══════════════════════════════════════════════════════════════════════════════
# Non-IAM churn that may ride alongside an additive IAM change
# ═══════════════════════════════════════════════════════════════════════════════


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
        "asset-hash churn — the bundle carries its commit (#2377) so Code moves every commit; CI's code path "
        "(deploy_lambda.sh / deploy_fleet.sh) ships exactly this class already (#2993). SHAPE-BOUND (review R1): "
        "tolerated only when the new Code is exactly {S3Bucket: the CDK bootstrap assets bucket for this "
        "account+region, S3Key: <64-hex>.zip} — a foreign bucket, ImageUri or inline ZipFile is not churn",
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

ASSET_KEY_RE = re.compile(r"[0-9a-f]{64}\.zip")
BOOTSTRAP_VERSION_RE = re.compile(r"/cdk-bootstrap/([a-z0-9]+)/version")


def bootstrap_qualifier(template: Any) -> str | None:
    """The CDK bootstrap qualifier this template was synthesized against, or None.

    CDK emits a `BootstrapVersion` SSM-lookup parameter whose Default is
    `/cdk-bootstrap/<qualifier>/version`. It is the template's own statement of which
    bootstrap stack — and therefore which asset bucket — it belongs to. None means the gate
    cannot know the sanctioned asset bucket, and R1's tolerance then admits nothing.
    """
    if not isinstance(template, dict):
        return None
    params = template.get("Parameters")
    if not isinstance(params, dict):
        return None
    bootstrap = params.get("BootstrapVersion")
    default = bootstrap.get("Default") if isinstance(bootstrap, dict) else None
    m = BOOTSTRAP_VERSION_RE.search(str(default or ""))
    return m.group(1) if m else None


def bootstrap_assets_bucket(qualifier: str, account: str, region: str) -> str:
    """The one bucket a CI-deployed Lambda may load its code from (review R1)."""
    return f"cdk-{qualifier}-assets-{account}-{region}"


def code_asset_problem(code: Any, account: str, region: str, qualifier: str | None) -> str | None:
    """Review R1: is this `AWS::Lambda::Function.Code` value asset-hash churn, or new code?

    None = it is churn of exactly the shape CI's own code path already ships. A string = why
    it is not, which sends the stack to `pending_non_iam` and therefore to OWNER-REQUIRED.
    """
    if not qualifier:
        return "the template declares no /cdk-bootstrap/<qualifier>/version parameter, so the sanctioned asset bucket is unknowable"
    if not isinstance(code, dict):
        return f"Code is {type(code).__name__}, not an {{S3Bucket, S3Key}} asset reference"
    if set(code) != {"S3Bucket", "S3Key"}:
        return (
            f"Code carries {sorted(code)} — only {{S3Bucket, S3Key}} is asset-hash churn "
            "(ImageUri, ZipFile and S3ObjectVersion are code CI did not build from this repo)"
        )
    bucket, key = code.get("S3Bucket"), code.get("S3Key")
    expected = bootstrap_assets_bucket(qualifier, account, region)
    if not isinstance(bucket, str) or bucket != expected:
        return f"Code.S3Bucket {bucket!r} is not this environment's CDK asset bucket {expected!r}"
    if not isinstance(key, str) or not ASSET_KEY_RE.fullmatch(key):
        return f"Code.S3Key {key!r} is not a <64-hex>.zip CDK asset key"
    return None


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


def registry_fingerprint() -> str:
    """sha256 over the registry data — the ledger records WHICH allowed shape admitted a change."""
    blob = json.dumps(
        {
            "namespace": [asdict(f) for f in NAMESPACE_FAMILIES],
            "wildcard_shapes": [list(s) for s in WILDCARD_RESOURCE_SHAPES],
            "s3_protected": [list(p) for p in S3_PROTECTED],
            "s3_mutable_by_ci_today": list(S3_MUTABLE_BY_CI_TODAY),
            "forbidden": FORBIDDEN_ACTION_PATTERNS,
            "tolerated": [asdict(t) for t in TOLERATED_NON_IAM],
            "resource_policy_types": sorted(RESOURCE_POLICY_TYPES),
            "iam_property_names": sorted(IAM_PROPERTY_NAMES),
        },
        sort_keys=True,
    )
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


def baseline_snapshot() -> dict[str, Any]:
    """The ratchet's view of this registry — compared against the ADR-065 fenced block (review R5).

    Only the HAND-DECLARED sets are in here. `S3_PROTECTED` is deliberately absent: it is
    derived from `deploy/bucket_policy.json`, a file the owner already reads and edits, and
    pinning it here would mean a new protected prefix needed an ADR edit before it took
    effect — the opposite of what deriving it is for. Its derivation is guarded instead, by
    `tests/test_iam_additive_gate_2834.py::test_the_s3_protection_is_derived_from_the_bucket_policy_not_retyped__review_R2b`.
    """
    return {
        "forbidden_actions": sorted(FORBIDDEN_ACTION_PATTERNS),
        "namespace_families": sorted(f.name for f in NAMESPACE_FAMILIES),
        "wildcard_resource_shapes": sorted(s[0] for s in WILDCARD_RESOURCE_SHAPES),
        "tolerated_non_iam": sorted([t.resource_type, t.prop or "", t.logical_id_prefix] for t in TOLERATED_NON_IAM),
        "resource_policy_types": sorted(RESOURCE_POLICY_TYPES),
        "iam_property_names": sorted(IAM_PROPERTY_NAMES),
        "s3_mutable_by_ci_today": sorted(S3_MUTABLE_BY_CI_TODAY),
    }


if __name__ == "__main__":  # pragma: no cover — prints the block that belongs in the ADR-065 amendment
    print(json.dumps(baseline_snapshot(), indent=2, sort_keys=True))
