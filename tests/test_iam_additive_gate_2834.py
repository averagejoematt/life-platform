"""#2834 — the additive-IAM gate, contract-tested on the REAL wire (charter primitive 4, §9a).

The fixture is a slice of an actual `cdk synth` template (LifePlatformEmail: the daily-brief
role + its DefaultPolicy + function + LogRetention singleton + one alarm + CDKMetadata), i.e.
the exact JSON `aws cloudformation get-template --template-stage Original` returns and the
exact JSON `cdk.out/` contains. Every test below mutates a deep copy of that slice — never a
hand-drawn "policy-shaped" dict — so a green here is evidence about the shape CI will see.

One mutation per forbidden shape (each must name its class), positive controls for every
admitted shape, and the fail-closed contract for anything unparseable. Marked deploy_critical:
this gate decides whether CI may run `cdk deploy`, so it gates the deploy that would use it.
"""

from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "deploy"))

import iam_additive_gate as g  # noqa: E402
import iam_additive_registry as g_reg  # noqa: E402

pytestmark = pytest.mark.deploy_critical

FIXTURE = ROOT / "tests" / "fixtures" / "iam_additive_gate" / "LifePlatformEmail.slice.template.json"
STACK = "LifePlatformEmail"
REGION = "us-west-2"

POLICY = "DailyBriefRoleDefaultPolicyC441914D"
ROLE = "DailyBriefRoleCE6CDC95"
FN = "DailyBrief22B24B58"
LOGRET_FN = "LogRetentionaae0aa3c5b4d4f87b02d85b201efdd8aFD4BFC8A"
LOGRET_POLICY = "LogRetentionaae0aa3c5b4d4f87b02d85b201efdd8aServiceRoleDefaultPolicyADDA7DEB"
LOGRET_ROLE = "LogRetentionaae0aa3c5b4d4f87b02d85b201efdd8aServiceRole9741ECFB"
ALARM = "WeeklySignalDeliveryHeartbeatFB9ECC22"
PERMISSION = "DailyBriefScheduleAllowEventRuleLifePlatformEmailDailyBriefDC5205DAA1BA5E7D"

BUCKET = g._C.S3_BUCKET
ACCT = g.ACCOUNT


@pytest.fixture(scope="module")
def base() -> dict:
    with open(FIXTURE, encoding="utf-8") as fh:
        return json.load(fh)


def _fresh(base: dict) -> tuple[dict, dict]:
    return copy.deepcopy(base), copy.deepcopy(base)


def _ev(deployed, synth) -> g.StackVerdict:
    return g.evaluate_templates(STACK, deployed, synth, REGION, ACCT)


def _stmts(t: dict, policy: str = POLICY) -> list:
    return t["Resources"][policy]["Properties"]["PolicyDocument"]["Statement"]


def _stmt(t: dict, sid: str, policy: str = POLICY) -> dict:
    return next(s for s in _stmts(t, policy) if s.get("Sid") == sid)


def _kinds(v: g.StackVerdict) -> set[str]:
    return {f.kind for f in v.findings}


NEW_ALLOW = {
    "Action": "s3:GetObject",
    "Effect": "Allow",
    "Resource": f"arn:aws:s3:::{BUCKET}/config/content_filter.json",
    "Sid": "ContentFilterRead",
}


# ── the fixture IS the wire ────────────────────────────────────────────────────────


def test_fixture_is_a_real_synth_slice(base):
    """Guard the fixture's provenance: CDK bookkeeping + the real statement shapes must be present."""
    res = base["Resources"]
    assert res[POLICY]["Type"] == "AWS::IAM::Policy"
    assert res[POLICY]["Properties"]["Roles"] == [{"Ref": ROLE}]
    assert res[ROLE]["Metadata"]["aws:cdk:path"].startswith("LifePlatformEmail/")
    assert res[FN]["Properties"]["Code"]["S3Key"].endswith(".zip")
    assert base["Parameters"]["BootstrapVersion"]["Default"] == "/cdk-bootstrap/hnb659fds/version"
    # a real Resource:"*" statement exists on the LogRetention policy — the gate must tolerate its
    # PRESENCE (unchanged) and refuse its GROWTH (tested below)
    assert any(s.get("Resource") == "*" for s in _stmts(base, LOGRET_POLICY))


# ── positive controls ──────────────────────────────────────────────────────────────


def test_identical_templates_are_no_iam_change(base):
    v = _ev(*_fresh(base))
    assert v.verdict == g.NO_CHANGE and not v.findings and not v.pending_non_iam and not v.admitted


def test_new_allow_on_bucket_object_is_admitted__the_0814_grant_shape(base):
    """INCIDENT_LOG 2026-08-14 P1: two roles needed s3:GetObject on config/content_filter.json."""
    dep, syn = _fresh(base)
    _stmts(syn).append(dict(NEW_ALLOW))
    v = _ev(dep, syn)
    assert v.verdict == g.ALLOW, v.findings
    assert len(v.admitted) == 1
    a = v.admitted[0]
    assert a.how == "new-statement" and a.role_refs == [ROLE] and a.sid == "ContentFilterRead"
    assert a.resources == [NEW_ALLOW["Resource"]]


def test_sqs_sendmessage_on_platform_queue_is_admitted__the_0815_grant_shape(base):
    """INCIDENT_LOG 2026-08-15 P3: the sqs:SendMessage grant that stranded the pipeline ~14h."""
    dep, syn = _fresh(base)
    _stmts(syn).append(
        {
            "Action": "sqs:SendMessage",
            "Effect": "Allow",
            "Resource": f"arn:aws:sqs:{REGION}:{ACCT}:life-platform-ai-quality-canary-dlq",
            "Sid": "CanaryDlq",
        }
    )
    assert _ev(dep, syn).verdict == g.ALLOW


def test_grown_statement_resource_is_admitted__cdk_minimize_policies_shape(base):
    """@aws-cdk/aws-iam:minimizePolicies is on: a like-shaped grant MERGES into an existing statement."""
    dep, syn = _fresh(base)
    s = _stmt(syn, "S3ConfigRead")
    s["Resource"] = [s["Resource"], f"arn:aws:s3:::{BUCKET}/config/content_filter.json"]
    v = _ev(dep, syn)
    assert v.verdict == g.ALLOW, v.findings
    assert v.admitted[0].how == "grown-statement"


def test_grown_statement_action_is_admitted(base):
    dep, syn = _fresh(base)
    s = _stmt(syn, "DynamoDB")
    s["Action"] = s["Action"] + ["dynamodb:DeleteItem"]
    v = _ev(dep, syn)
    assert v.verdict == g.ALLOW, v.findings


def test_code_hash_and_metadata_churn_alone_is_no_iam_change(base):
    """#2377: the asset hash moves every commit; #2993: CI's code path already ships this class."""
    dep, syn = _fresh(base)
    syn["Resources"][FN]["Properties"]["Code"]["S3Key"] = "0" * 64 + ".zip"
    syn["Resources"][FN]["Metadata"]["aws:asset:path"] = "asset.0000"
    syn["Resources"]["CDKMetadata"]["Properties"]["Analytics"] = "v2:deflate64:CHANGED"
    v = _ev(dep, syn)
    assert v.verdict == g.NO_CHANGE and not v.pending_non_iam


def test_additive_iam_riding_with_code_churn_is_admitted(base):
    """The realistic state: an IAM-only merge lands days after the last owner cdk deploy."""
    dep, syn = _fresh(base)
    syn["Resources"][FN]["Properties"]["Code"]["S3Key"] = "0" * 64 + ".zip"
    _stmts(syn).append(dict(NEW_ALLOW))
    assert _ev(dep, syn).verdict == g.ALLOW


def test_logretention_runtime_skew_is_tolerated__2468(base):
    dep, syn = _fresh(base)
    syn["Resources"][LOGRET_FN]["Properties"]["Runtime"] = "nodejs24.x"
    assert _ev(dep, syn).verdict == g.NO_CHANGE
    _stmts(syn).append(dict(NEW_ALLOW))
    assert _ev(dep, syn).verdict == g.ALLOW


def test_alarm_description_change_alone_is_no_iam_change_with_advisory(base):
    """A non-IAM CDK diff neither strands (the old grep did not either) nor ships — it is named."""
    dep, syn = _fresh(base)
    syn["Resources"][ALARM]["Properties"]["AlarmDescription"] = "reworded"
    v = _ev(dep, syn)
    assert v.verdict == g.NO_CHANGE
    assert v.pending_non_iam == [f"{ALARM} (AWS::CloudWatch::Alarm).AlarmDescription"]
    assert any("Pending owner cdk deploy" in line for line in g.render([v]))


def test_partition_ref_join_resource_resolves_into_namespace(base):
    dep, syn = _fresh(base)
    _stmts(syn).append(
        {
            "Action": "s3:PutObject",
            "Effect": "Allow",
            "Sid": "Gen",
            "Resource": {"Fn::Join": ["", ["arn:", {"Ref": "AWS::Partition"}, f":s3:::{BUCKET}/generated/*"]]},
        }
    )
    v = _ev(dep, syn)
    assert v.verdict == g.ALLOW, v.findings
    assert v.admitted[0].resources == [f"arn:aws:s3:::{BUCKET}/generated/*"]


def test_getatt_to_named_in_template_bucket_resolves(base):
    """A GetAtt to an in-template bucket with a LITERAL name renders to a real ARN."""
    dep, syn = _fresh(base)
    for t in (dep, syn):
        t["Resources"]["PlatformBucket"] = {"Type": "AWS::S3::Bucket", "Properties": {"BucketName": BUCKET}}
    _stmts(syn).append(
        {
            "Action": "s3:GetObject",
            "Effect": "Allow",
            "Sid": "ViaGetAtt",
            "Resource": {"Fn::Join": ["", [{"Fn::GetAtt": ["PlatformBucket", "Arn"]}, "/generated/og/*"]]},
        }
    )
    v = _ev(dep, syn)
    assert v.verdict == g.ALLOW, v.findings
    assert v.admitted[0].resources == [f"arn:aws:s3:::{BUCKET}/generated/og/*"]


def test_dil027_replica_bucket_is_out_of_namespace__review_R2a(base):
    """R2(a): the DIL-027 cross-region raw/ replica left the namespace. No Lambda role reads
    or writes it (the replication is an S3 service role), it has no Object Lock, and a grant
    there was `ALLOW-ADDITIVE` for `s3:DeleteObject` before the review."""
    assert g.resource_in_namespace(f"arn:aws:s3:::{g._C.RAW_BACKUP_BUCKET}/raw/x") is None
    dep, syn = _fresh(base)
    for t in (dep, syn):
        t["Resources"]["RawBackup"] = {"Type": "AWS::S3::Bucket", "Properties": {"BucketName": g._C.RAW_BACKUP_BUCKET}}
    _stmts(syn).append(
        {
            "Action": "s3:GetObject",
            "Effect": "Allow",
            "Sid": "Replica",
            "Resource": {"Fn::Join": ["", [{"Fn::GetAtt": ["RawBackup", "Arn"]}, "/*"]]},
        }
    )
    v = _ev(dep, syn)
    assert v.verdict == g.OWNER and "out-of-namespace-resource" in _kinds(v)


def test_partial_wildcard_action_that_cannot_overlap_forbidden_is_admitted(base):
    """s3:GetObject* is what CDK's grant_read emits; nothing forbidden starts with s3:getobject."""
    dep, syn = _fresh(base)
    _stmts(syn).append(
        {
            "Action": ["s3:GetObject*", "s3:List*"],
            "Effect": "Allow",
            "Sid": "Read",
            "Resource": [f"arn:aws:s3:::{BUCKET}", f"arn:aws:s3:::{BUCKET}/*"],
        }
    )
    assert _ev(dep, syn).verdict == g.ALLOW


# ── one mutation per forbidden shape ───────────────────────────────────────────────


def _with_deny(t: dict) -> dict:
    _stmts(t).append(
        {
            "Action": "s3:DeleteObject",
            "Effect": "Deny",
            "Sid": "NoRawDelete",
            "Resource": [f"arn:aws:s3:::{BUCKET}/raw/*", f"arn:aws:s3:::{BUCKET}/config/*"],
        }
    )
    return t


def test_deny_removal_is_owner_required(base):
    dep, syn = _fresh(base)
    _with_deny(dep)
    v = _ev(dep, syn)
    assert v.verdict == g.OWNER and "deny-removed-or-altered" in _kinds(v)
    assert any("NoRawDelete" in f.detail for f in v.findings)


def test_deny_narrowed_is_owner_required(base):
    dep, syn = _fresh(base)
    _with_deny(dep)
    _with_deny(syn)
    _stmt(syn, "NoRawDelete")["Resource"] = [f"arn:aws:s3:::{BUCKET}/raw/*"]
    v = _ev(dep, syn)
    assert v.verdict == g.OWNER and "deny-removed-or-altered" in _kinds(v)


def test_deny_added_is_owner_required(base):
    dep, syn = _fresh(base)
    _with_deny(syn)
    v = _ev(dep, syn)
    assert v.verdict == g.OWNER and "deny-added" in _kinds(v)


def test_trust_policy_edit_is_owner_required(base):
    dep, syn = _fresh(base)
    syn["Resources"][ROLE]["Properties"]["AssumeRolePolicyDocument"]["Statement"][0]["Principal"] = {"Service": "ec2.amazonaws.com"}
    v = _ev(dep, syn)
    assert v.verdict == g.OWNER and "trust-policy-edit" in _kinds(v)


def test_trust_policy_edit_with_additive_grant_still_owner_required(base):
    dep, syn = _fresh(base)
    syn["Resources"][ROLE]["Properties"]["AssumeRolePolicyDocument"]["Statement"].append(
        {"Action": "sts:AssumeRole", "Effect": "Allow", "Principal": {"AWS": f"arn:aws:iam::{ACCT}:root"}}
    )
    _stmts(syn).append(dict(NEW_ALLOW))
    v = _ev(dep, syn)
    assert v.verdict == g.OWNER and "trust-policy-edit" in _kinds(v)
    assert v.admitted  # the additive half was recognised AND the stack still refused


@pytest.mark.parametrize(
    "action,kind",
    [
        ("iam:PassRole", "forbidden-action"),
        ("iam:CreateRole", "forbidden-action"),
        ("sts:AssumeRole", "forbidden-action"),
        ("cloudformation:CreateStack", "forbidden-action"),
        ("lambda:UpdateFunctionCode", "forbidden-action"),
        ("lambda:AddPermission", "forbidden-action"),
        ("s3:PutBucketPolicy", "forbidden-action"),
        ("kms:PutKeyPolicy", "forbidden-action"),
        ("dynamodb:UpdateTable", "forbidden-action"),
        ("iam:*", "service-wide-wildcard-action"),
        ("s3:*", "service-wide-wildcard-action"),
        ("*", "malformed-or-wildcard-action"),
        ("lambda:Update*", "wildcard-action-overlaps-forbidden"),
        ("lambda:*", "service-wide-wildcard-action"),
        ("s3:Put*", "wildcard-action-overlaps-forbidden"),
    ],
)
def test_forbidden_action_shapes_are_owner_required(base, action, kind):
    dep, syn = _fresh(base)
    _stmts(syn).append({"Action": action, "Effect": "Allow", "Sid": "Bad", "Resource": f"arn:aws:s3:::{BUCKET}/generated/*"})
    v = _ev(dep, syn)
    assert v.verdict == g.OWNER, action
    assert kind in _kinds(v), (action, _kinds(v))
    assert any(action in f.detail for f in v.findings)


@pytest.mark.parametrize(
    "resource,kind",
    [
        ("arn:aws:s3:::someone-elses-bucket/*", "out-of-namespace-resource"),
        (f"arn:aws:dynamodb:{REGION}:{ACCT}:table/other-table", "out-of-namespace-resource"),
        (f"arn:aws:dynamodb:{REGION}:{ACCT}:table/*", "out-of-namespace-resource"),
        (f"arn:aws:secretsmanager:{REGION}:{ACCT}:secret:prod/db-*", "out-of-namespace-resource"),
        (f"arn:aws:lambda:{REGION}:{ACCT}:function:*", "out-of-namespace-resource"),
        (f"arn:aws:lambda:{REGION}:{ACCT}:function:not-a-platform-function", "out-of-namespace-resource"),
        (f"arn:aws:lambda:*:{ACCT}:function:daily-brief", "out-of-namespace-resource"),
        (f"arn:aws:s3:::{BUCKET}-*", "out-of-namespace-resource"),
        (f"arn:aws:dynamodb:{REGION}:999999999999:table/life-platform", "out-of-namespace-resource"),
        (f"arn:aws:iam::{ACCT}:role/life-platform-anything", "out-of-namespace-resource"),
        (f"arn:aws:bedrock:*:{ACCT}:inference-profile/us.anthropic.claude-*", "out-of-namespace-resource"),
        ("*", "wildcard-resource"),
        ("arn:aws:s3:::*", "out-of-namespace-resource"),
    ],
)
def test_out_of_namespace_and_wildcard_resources_are_owner_required(base, resource, kind):
    dep, syn = _fresh(base)
    _stmts(syn).append(
        {
            "Action": "s3:GetObject" if "s3" in resource or resource == "*" else "dynamodb:GetItem",
            "Effect": "Allow",
            "Sid": "Bad",
            "Resource": resource,
        }
    )
    v = _ev(dep, syn)
    assert v.verdict == g.OWNER, resource
    assert kind in _kinds(v), (resource, _kinds(v))


def test_grown_statement_on_star_resource_is_refused(base):
    """A new action on an existing Resource:"*" statement is a new grant on "*"."""
    dep, syn = _fresh(base)
    star = next(s for s in _stmts(syn, LOGRET_POLICY) if s.get("Resource") == "*")
    star["Action"] = list(star["Action"]) + ["logs:DescribeLogGroups"]
    v = _ev(dep, syn)
    assert v.verdict == g.OWNER and "wildcard-resource" in _kinds(v)


def test_managed_policy_attachment_is_owner_required(base):
    dep, syn = _fresh(base)
    syn["Resources"][ROLE]["Properties"]["ManagedPolicyArns"].append("arn:aws:iam::aws:policy/AmazonS3ReadOnlyAccess")
    v = _ev(dep, syn)
    assert v.verdict == g.OWNER and "managed-policy-attachment" in _kinds(v)


def test_permissions_boundary_edit_is_owner_required(base):
    dep, syn = _fresh(base)
    syn["Resources"][ROLE]["Properties"]["PermissionsBoundary"] = f"arn:aws:iam::{ACCT}:policy/some-boundary"
    v = _ev(dep, syn)
    assert v.verdict == g.OWNER and "permissions-boundary-edit" in _kinds(v)


def test_inline_role_policy_edit_is_owner_required(base):
    dep, syn = _fresh(base)
    syn["Resources"][ROLE]["Properties"]["Policies"] = [{"PolicyName": "inline", "PolicyDocument": {"Statement": [dict(NEW_ALLOW)]}}]
    v = _ev(dep, syn)
    assert v.verdict == g.OWNER and "inline-role-policy-edit" in _kinds(v)


def test_allow_removed_is_owner_required(base):
    dep, syn = _fresh(base)
    _stmts(syn).remove(_stmt(syn, "S3ConfigRead"))
    v = _ev(dep, syn)
    assert v.verdict == g.OWNER and "allow-removed-or-narrowed" in _kinds(v)
    assert any("S3ConfigRead" in f.detail for f in v.findings)


def test_allow_narrowed_is_owner_required(base):
    dep, syn = _fresh(base)
    s = _stmt(syn, "DynamoDB")
    s["Action"] = [a for a in s["Action"] if a != "dynamodb:UpdateItem"]
    v = _ev(dep, syn)
    assert v.verdict == g.OWNER and "allow-removed-or-narrowed" in _kinds(v)


def test_sid_rename_reads_as_removal_not_addition(base):
    """Cosmetic renames fail closed: identity is (Effect, Sid, Condition)."""
    dep, syn = _fresh(base)
    _stmt(syn, "S3ConfigRead")["Sid"] = "S3ConfigReadRenamed"
    v = _ev(dep, syn)
    assert v.verdict == g.OWNER and "allow-removed-or-narrowed" in _kinds(v)


def test_condition_change_on_existing_allow_is_owner_required(base):
    dep, syn = _fresh(base)
    _stmt(syn, "S3ConfigRead")["Condition"] = {"Bool": {"aws:SecureTransport": "true"}}
    v = _ev(dep, syn)
    assert v.verdict == g.OWNER and "allow-removed-or-narrowed" in _kinds(v)


def test_new_role_is_owner_required(base):
    dep, syn = _fresh(base)
    syn["Resources"]["NewRoleABC"] = copy.deepcopy(syn["Resources"][ROLE])
    v = _ev(dep, syn)
    assert v.verdict == g.OWNER and "new-role-or-resource-policy" in _kinds(v)


def test_new_policy_bound_to_new_role_is_owner_required(base):
    dep, syn = _fresh(base)
    syn["Resources"]["NewRoleABC"] = copy.deepcopy(syn["Resources"][ROLE])
    pol = copy.deepcopy(syn["Resources"][POLICY])
    pol["Properties"]["Roles"] = [{"Ref": "NewRoleABC"}]
    syn["Resources"]["NewPolicyABC"] = pol
    v = _ev(dep, syn)
    assert v.verdict == g.OWNER
    assert {"new-role-or-resource-policy", "policy-bound-to-new-or-changed-role"} <= _kinds(v)


def test_role_removed_is_owner_required(base):
    dep, syn = _fresh(base)
    del syn["Resources"][LOGRET_ROLE]
    v = _ev(dep, syn)
    assert v.verdict == g.OWNER and "iam-resource-removed" in _kinds(v)


def test_new_lambda_permission_is_owner_required(base):
    """Resource-based policies grant to PRINCIPALS — a different predicate, deliberately out of shape."""
    dep, syn = _fresh(base)
    syn["Resources"]["ExtraInvoke"] = copy.deepcopy(syn["Resources"][PERMISSION])
    v = _ev(dep, syn)
    assert v.verdict == g.OWNER and "new-iam-resource" in _kinds(v)


def test_lambda_permission_principal_change_is_owner_required(base):
    dep, syn = _fresh(base)
    syn["Resources"][PERMISSION]["Properties"]["Principal"] = "*"
    v = _ev(dep, syn)
    assert v.verdict == g.OWNER and "iam-resource-modified" in _kinds(v)


@pytest.mark.parametrize(
    "typ",
    [
        "AWS::SQS::QueuePolicy",
        "AWS::S3::BucketPolicy",
        "AWS::SNS::TopicPolicy",
        "AWS::Lambda::Url",
        "AWS::KMS::Key",
        "AWS::IAM::ManagedPolicy",
        "AWS::IAM::User",
    ],
)
def test_new_resource_policy_or_identity_types_are_owner_required(base, typ):
    dep, syn = _fresh(base)
    syn["Resources"]["Extra"] = {"Type": typ, "Properties": {}}
    v = _ev(dep, syn)
    assert v.verdict == g.OWNER and "new-iam-resource" in _kinds(v)


def test_policy_rebinding_to_another_role_is_owner_required(base):
    dep, syn = _fresh(base)
    syn["Resources"][POLICY]["Properties"]["Roles"] = [{"Ref": ROLE}, {"Ref": LOGRET_ROLE}]
    v = _ev(dep, syn)
    assert v.verdict == g.OWNER and "policy-binding-changed" in _kinds(v)


def test_policy_bound_to_user_or_group_is_owner_required(base):
    dep, syn = _fresh(base)
    syn["Resources"][POLICY]["Properties"]["Users"] = ["matthew-admin"]
    _stmts(syn).append(dict(NEW_ALLOW))
    v = _ev(dep, syn)
    assert v.verdict == g.OWNER and {"policy-bound-to-users", "policy-binding-changed"} <= _kinds(v)


@pytest.mark.parametrize("key", ["NotAction", "NotResource", "Principal", "NotPrincipal"])
def test_inverted_or_principal_statements_are_owner_required(base, key):
    dep, syn = _fresh(base)
    s = {"Effect": "Allow", "Sid": "Inv", "Action": "s3:GetObject", "Resource": f"arn:aws:s3:::{BUCKET}/x"}
    s[key] = "*" if key.endswith("Principal") else ["s3:GetObject"]
    _stmts(syn).append(s)
    v = _ev(dep, syn)
    assert v.verdict == g.OWNER and "inverted-or-principal-statement" in _kinds(v)


def test_unresolvable_resource_is_owner_required(base):
    """A GetAtt to a bucket with a CFN-generated name cannot be placed in the namespace."""
    dep, syn = _fresh(base)
    for t in (dep, syn):
        t["Resources"]["Anon"] = {"Type": "AWS::S3::Bucket", "Properties": {}}
    _stmts(syn).append({"Action": "s3:GetObject", "Effect": "Allow", "Sid": "Anon", "Resource": {"Fn::GetAtt": ["Anon", "Arn"]}})
    v = _ev(dep, syn)
    assert v.verdict == g.OWNER and "unresolvable-resource" in _kinds(v)


def test_additive_iam_riding_with_lambda_config_change_is_owner_required(base):
    """The stack deploy would ship the env-var change too — CI may not (R20-F02 class)."""
    dep, syn = _fresh(base)
    _stmts(syn).append(dict(NEW_ALLOW))
    syn["Resources"][FN]["Properties"]["Environment"]["Variables"]["NEW_FLAG"] = "1"
    v = _ev(dep, syn)
    assert v.verdict == g.OWNER and "rides-with-non-iam-change" in _kinds(v)
    assert any(f"{FN} (AWS::Lambda::Function).Environment" in f.detail for f in v.findings)


def test_additive_iam_riding_with_new_queue_is_owner_required(base):
    """The 08-15 PR shape in full (#2655: new DLQ + DeadLetterConfig + grant) stays owner-run."""
    dep, syn = _fresh(base)
    syn["Resources"]["CanaryDlq"] = {"Type": "AWS::SQS::Queue", "Properties": {"QueueName": "life-platform-canary-dlq"}}
    _stmts(syn).append({"Action": "sqs:SendMessage", "Effect": "Allow", "Sid": "Dlq", "Resource": {"Fn::GetAtt": ["CanaryDlq", "Arn"]}})
    v = _ev(dep, syn)
    assert v.verdict == g.OWNER and "rides-with-non-iam-change" in _kinds(v)


def test_additive_iam_riding_with_alarm_change_is_owner_required(base):
    dep, syn = _fresh(base)
    _stmts(syn).append(dict(NEW_ALLOW))
    syn["Resources"][ALARM]["Properties"]["Threshold"] = 2
    assert _ev(dep, syn).verdict == g.OWNER


def test_function_role_swap_is_owner_required(base):
    dep, syn = _fresh(base)
    syn["Resources"][FN]["Properties"]["Role"] = {"Fn::GetAtt": [LOGRET_ROLE, "Arn"]}
    v = _ev(dep, syn)
    assert v.verdict == g.OWNER and "iam-property-edit" in _kinds(v)


def test_resource_type_classification_matches_the_decision(base):
    assert g.is_iam_relevant_type("AWS::IAM::Policy")
    assert g.is_iam_relevant_type("AWS::SQS::QueuePolicy")
    assert g.is_iam_relevant_type("AWS::Lambda::Permission")
    assert g.is_iam_relevant_type("AWS::Lambda::Url")
    # the R8-ST6 grep's measured false positive (DECISIONS.md, the #1678 CSP ADR): not IAM
    assert not g.is_iam_relevant_type("AWS::CloudFront::ResponseHeadersPolicy")
    assert not g.is_iam_relevant_type("AWS::CloudWatch::Alarm")


# ── review R1: the Lambda `Code` tolerance is SHAPE-bound, not name-bound ──────────
# As shipped, ("AWS::Lambda::Function", "Code", "") matched on (type, property) alone: an
# additive grant riding with Code pointing at a bucket the account does not own — or at a
# foreign container image, or at an inline ZipFile — was ALLOW-ADDITIVE, and CI shipped code
# that is not in this repo. Each probe below is one of those shapes.

ASSET_BUCKET = f"cdk-hnb659fds-assets-{ACCT}-{REGION}"
HASH_A = "a" * 64 + ".zip"


@pytest.mark.parametrize(
    "code,why",
    [
        ({"S3Bucket": "attacker-public-bucket", "S3Key": HASH_A}, "foreign bucket"),
        ({"S3Bucket": f"cdk-hnb659fds-assets-999999999999-{REGION}", "S3Key": HASH_A}, "another account's asset bucket"),
        ({"S3Bucket": "cdk-hnb659fds-assets-205930651321-eu-west-1", "S3Key": HASH_A}, "another region's asset bucket"),
        ({"ImageUri": "123456789012.dkr.ecr.us-west-2.amazonaws.com/evil:latest"}, "container image"),
        ({"ZipFile": "def handler(e, c): pass"}, "inline ZipFile"),
        ({"S3Bucket": ASSET_BUCKET, "S3Key": HASH_A, "S3ObjectVersion": "v2"}, "a pinned object version"),
        ({"S3Bucket": ASSET_BUCKET, "S3Key": "not-a-hash.zip"}, "a non-asset key"),
        ({"S3Bucket": ASSET_BUCKET, "S3Key": HASH_A[:-4]}, "an asset key that is not a .zip"),
    ],
)
def test_lambda_code_outside_the_asset_shape_is_owner_required__review_R1(base, code, why):
    dep, syn = _fresh(base)
    syn["Resources"][FN]["Properties"]["Code"] = code
    _stmts(syn).append(dict(NEW_ALLOW))
    v = _ev(dep, syn)
    assert v.verdict == g.OWNER, why
    assert "rides-with-non-iam-change" in _kinds(v), why
    assert any(f"{FN} (AWS::Lambda::Function).Code" in f.detail for f in v.findings), why


@pytest.mark.parametrize(
    "code",
    [
        {"S3Bucket": "attacker-public-bucket", "S3Key": HASH_A},
        {"ZipFile": "def handler(e, c): pass"},
    ],
)
def test_lambda_code_outside_the_asset_shape_is_named_even_with_no_iam_change__review_R1(base, code):
    """Without an IAM delta the stack is still NO-IAM-CHANGE (this gate does not decide code
    deploys) — but the shape violation is NAMED in the pending list, never silent."""
    dep, syn = _fresh(base)
    syn["Resources"][FN]["Properties"]["Code"] = code
    v = _ev(dep, syn)
    assert v.verdict == g.NO_CHANGE
    assert any("(AWS::Lambda::Function).Code —" in entry for entry in v.pending_non_iam), v.pending_non_iam


def test_asset_hash_only_move_is_still_tolerated__review_R1_positive_control(base):
    """The whole point of the tolerance: the same bucket, a new 64-hex asset key."""
    dep, syn = _fresh(base)
    syn["Resources"][FN]["Properties"]["Code"] = {"S3Bucket": ASSET_BUCKET, "S3Key": HASH_A}
    _stmts(syn).append(dict(NEW_ALLOW))
    v = _ev(dep, syn)
    assert v.verdict == g.ALLOW, v.findings
    assert not v.pending_non_iam


def test_asset_bucket_written_as_an_intrinsic_resolves__review_R1(base):
    """An env-agnostic synth writes S3Bucket as an Fn::Sub; the shape check reads the
    RESOLVED string, so the same bucket is tolerated in either spelling."""
    dep, syn = _fresh(base)
    syn["Resources"][FN]["Properties"]["Code"] = {
        "S3Bucket": {"Fn::Sub": "cdk-hnb659fds-assets-${AWS::AccountId}-${AWS::Region}"},
        "S3Key": HASH_A,
    }
    _stmts(syn).append(dict(NEW_ALLOW))
    assert _ev(dep, syn).verdict == g.ALLOW


def test_a_template_with_no_bootstrap_parameter_tolerates_no_code_move__review_R1(base):
    """Fail closed: without the template's own /cdk-bootstrap/<qualifier>/version parameter
    the sanctioned asset bucket is unknowable, so NO Code change is churn."""
    dep, syn = _fresh(base)
    del dep["Parameters"], syn["Parameters"]
    syn["Resources"][FN]["Properties"]["Code"] = {"S3Bucket": ASSET_BUCKET, "S3Key": HASH_A}
    _stmts(syn).append(dict(NEW_ALLOW))
    v = _ev(dep, syn)
    assert v.verdict == g.OWNER and "rides-with-non-iam-change" in _kinds(v)


# ── review R2: S3 mutating grants are prefix-scoped and respect the bucket policy ──


def _s3_probe(base, action, resource):
    dep, syn = _fresh(base)
    _stmts(syn).append({"Action": action, "Effect": "Allow", "Sid": "S3Probe", "Resource": resource})
    return _ev(dep, syn)


@pytest.mark.parametrize(
    "action,resource,kind",
    [
        ("s3:DeleteObject", f"arn:aws:s3:::{BUCKET}/raw/*", "s3-protected-prefix"),
        ("s3:DeleteObject", f"arn:aws:s3:::{BUCKET}/raw/matthew/whoop/*", "s3-protected-prefix"),
        ("s3:DeleteObject", f"arn:aws:s3:::{BUCKET}/config/*", "s3-protected-prefix"),
        ("s3:DeleteObject", f"arn:aws:s3:::{BUCKET}/generated/*", "s3-protected-prefix"),
        ("s3:DeleteObject", f"arn:aws:s3:::{BUCKET}/mcp-audit/*", "s3-protected-prefix"),
        ("s3:DeleteObject", f"arn:aws:s3:::{BUCKET}/claude-memory-backup/*", "s3-protected-prefix"),
        ("s3:DeleteObjectTagging", f"arn:aws:s3:::{BUCKET}/raw/*", "s3-protected-prefix"),
        ("s3:Delete*", f"arn:aws:s3:::{BUCKET}/uploads/*", "s3-protected-prefix"),
        ("s3:PutObject", f"arn:aws:s3:::{BUCKET}/*", "s3-mutating-action-on-unscoped-bucket"),
        ("s3:DeleteObject", f"arn:aws:s3:::{BUCKET}/*", "s3-mutating-action-on-unscoped-bucket"),
        ("s3:PutObject", f"arn:aws:s3:::{BUCKET}", "s3-mutating-action-on-unscoped-bucket"),
    ],
)
def test_s3_mutating_grants_are_bounded__review_R2b(base, action, resource, kind):
    v = _s3_probe(base, action, resource)
    assert v.verdict == g.OWNER, (action, resource)
    assert kind in _kinds(v), (action, resource, _kinds(v))


@pytest.mark.parametrize(
    "action,resource",
    [
        # the review's two named positive controls
        ("s3:PutObject", f"arn:aws:s3:::{BUCKET}/generated/og/*"),
        ("s3:GetObject", f"arn:aws:s3:::{BUCKET}/config/content_filter.json"),
        # reads over the whole bucket are unaffected — only MUTATING actions are bounded
        ("s3:GetObject", f"arn:aws:s3:::{BUCKET}/raw/*"),
        ("s3:ListBucket", f"arn:aws:s3:::{BUCKET}"),
        # the two prefixes CI's own paths already write and delete end to end
        ("s3:PutObject", f"arn:aws:s3:::{BUCKET}/site/*"),
        ("s3:PutObject", f"arn:aws:s3:::{BUCKET}/remediation-log/*"),
    ],
)
def test_s3_positive_controls_still_allow__review_R2b(base, action, resource):
    v = _s3_probe(base, action, resource)
    assert v.verdict == g.ALLOW, (action, resource, v.findings)


def test_the_s3_protection_is_derived_from_the_bucket_policy_not_retyped__review_R2b():
    """Guard the SET: every Deny prefix in deploy/bucket_policy.json is protected here, and
    the derivation is the file — add a prefix there and it is live the same day."""
    policy = json.loads((ROOT / "deploy" / "bucket_policy.json").read_text())
    denied = {
        res.split("/", 1)[1].rsplit("/*", 1)[0] + "/"
        for st in policy["Statement"]
        if st.get("Effect") == "Deny"
        for res in (st["Resource"] if isinstance(st["Resource"], list) else [st["Resource"]])
    }
    assert denied, "the bucket policy parse found no Deny prefixes — the derivation is broken, not the policy"
    protected = {prefix for _a, prefix, _s in g_reg.S3_PROTECTED}
    assert denied == protected, denied ^ protected
    for prefix in sorted(denied):
        assert g_reg.s3_grant_problem("s3:DeleteObject", f"arn:aws:s3:::{BUCKET}/{prefix}x") is not None, prefix


@pytest.mark.parametrize(
    "action",
    [
        "s3:PutBucketNotification",
        "s3:PutBucketOwnershipControls",
        "s3:PutBucketLogging",
        "s3:PutBucketObjectLockConfiguration",
        "s3:PutEncryptionConfiguration",
        "s3:PutInventoryConfiguration",
        "s3:PutMetricsConfiguration",
        "s3:DeleteObjectVersion",
        "s3:DeleteObjectVersionTagging",
        "s3:PutObjectRetention",
        "s3:PutObjectLegalHold",
        "s3:BypassGovernanceRetention",
    ],
)
def test_s3_control_plane_actions_are_forbidden__review_R2c(base, action):
    v = _s3_probe(base, action, f"arn:aws:s3:::{BUCKET}/generated/og/*")
    assert v.verdict == g.OWNER, action
    assert "forbidden-action" in _kinds(v), (action, _kinds(v))


# ── review R3: the in-namespace control-plane flips ────────────────────────────────


@pytest.mark.parametrize(
    "action,resource",
    [
        ("ssm:PutParameter", f"arn:aws:ssm:{REGION}:{ACCT}:parameter/life-platform/remediation-mode"),
        ("ssm:PutParameter", f"arn:aws:ssm:{REGION}:{ACCT}:parameter/life-platform/budget-tier"),
        ("sns:Subscribe", f"arn:aws:sns:{REGION}:{ACCT}:life-platform-alerts"),
        ("sns:Unsubscribe", f"arn:aws:sns:{REGION}:{ACCT}:life-platform-alerts"),
        ("sns:DeleteTopic", f"arn:aws:sns:{REGION}:{ACCT}:life-platform-alerts"),
        ("dynamodb:UpdateTimeToLive", f"arn:aws:dynamodb:{REGION}:{ACCT}:table/life-platform"),
        ("secretsmanager:PutSecretValue", f"arn:aws:secretsmanager:{REGION}:{ACCT}:secret:life-platform/whoop-AbCdEf"),
        ("secretsmanager:UpdateSecret", f"arn:aws:secretsmanager:{REGION}:{ACCT}:secret:life-platform/whoop-AbCdEf"),
        ("secretsmanager:RotateSecret", f"arn:aws:secretsmanager:{REGION}:{ACCT}:secret:life-platform/whoop-AbCdEf"),
        ("logs:PutSubscriptionFilter", f"arn:aws:logs:{REGION}:{ACCT}:log-group:/aws/lambda/daily-brief:*"),
        ("logs:PutRetentionPolicy", f"arn:aws:logs:{REGION}:{ACCT}:log-group:/aws/lambda/daily-brief:*"),
        ("logs:DeleteLogStream", f"arn:aws:logs:{REGION}:{ACCT}:log-group:/aws/lambda/daily-brief:*"),
        ("sqs:PurgeQueue", f"arn:aws:sqs:{REGION}:{ACCT}:life-platform-ingestion-dlq"),
        ("sqs:DeleteQueue", f"arn:aws:sqs:{REGION}:{ACCT}:life-platform-ingestion-dlq"),
        ("kms:ReplicateKey", f"arn:aws:kms:{REGION}:{ACCT}:key/{g._C.KMS_KEY_ID}"),
        ("lambda:PutProvisionedConcurrencyConfig", f"arn:aws:lambda:{REGION}:{ACCT}:function:daily-brief"),
    ],
)
def test_in_namespace_control_plane_flips_are_forbidden__review_R3(base, action, resource):
    """Every one of these was ALLOW-ADDITIVE before the review — inside the namespace, on a
    resource the platform owns, and each one flips a control the owner relies on."""
    dep, syn = _fresh(base)
    _stmts(syn).append({"Action": action, "Effect": "Allow", "Sid": "ControlPlane", "Resource": resource})
    v = _ev(dep, syn)
    assert v.verdict == g.OWNER, action
    assert "forbidden-action" in _kinds(v), (action, _kinds(v))
    assert any(action in f.detail for f in v.findings), action


@pytest.mark.parametrize(
    "action,resource",
    [
        ("ssm:GetParameter", f"arn:aws:ssm:{REGION}:{ACCT}:parameter/life-platform/budget-tier"),
        ("sns:Publish", f"arn:aws:sns:{REGION}:{ACCT}:life-platform-alerts"),
        ("secretsmanager:GetSecretValue", f"arn:aws:secretsmanager:{REGION}:{ACCT}:secret:life-platform/whoop-AbCdEf"),
        ("logs:PutLogEvents", f"arn:aws:logs:{REGION}:{ACCT}:log-group:/aws/lambda/daily-brief:*"),
        ("sqs:SendMessage", f"arn:aws:sqs:{REGION}:{ACCT}:life-platform-ingestion-dlq"),
        ("dynamodb:PutItem", f"arn:aws:dynamodb:{REGION}:{ACCT}:table/life-platform"),
        ("kms:Decrypt", f"arn:aws:kms:{REGION}:{ACCT}:key/{g._C.KMS_KEY_ID}"),
    ],
)
def test_the_ordinary_data_plane_grants_still_allow__review_R3_positive_control(base, action, resource):
    dep, syn = _fresh(base)
    _stmts(syn).append({"Action": action, "Effect": "Allow", "Sid": "DataPlane", "Resource": resource})
    v = _ev(dep, syn)
    assert v.verdict == g.ALLOW, (action, v.findings)


# ── review N3: a wildcard INSIDE an in-namespace ARN is an explicit decision ───────


@pytest.mark.parametrize(
    "resource",
    [
        f"arn:aws:lambda:{REGION}:{ACCT}:function:life-platform-*",
        f"arn:aws:sns:{REGION}:{ACCT}:life-platform-*",
        f"arn:aws:sqs:{REGION}:{ACCT}:life-platform-*",
        f"arn:aws:logs:{REGION}:{ACCT}:log-group:/aws/lambda/life-platform-*",
    ],
)
def test_name_prefix_wildcards_inside_the_namespace_are_refused__review_N3(base, resource):
    """REFUSED, by decision: `function:life-platform-*` grants over every function the
    platform will ever have, including ones that do not exist yet. The namespace still
    admits those same prefixes for CONCRETE names."""
    assert g.resource_in_namespace(resource) is not None, "the probe must be in-namespace or it proves nothing"
    dep, syn = _fresh(base)
    _stmts(syn).append({"Action": "lambda:InvokeFunction", "Effect": "Allow", "Sid": "Wild", "Resource": resource})
    v = _ev(dep, syn)
    assert v.verdict == g.OWNER, resource
    assert "wildcard-resource-outside-established-shape" in _kinds(v), (resource, _kinds(v))


@pytest.mark.parametrize(
    "action,resource,shape",
    [
        ("s3:GetObject", f"arn:aws:s3:::{BUCKET}/config/*", "s3-object-key"),
        ("secretsmanager:GetSecretValue", f"arn:aws:secretsmanager:{REGION}:{ACCT}:secret:life-platform/whoop-*", "secret-name-or-version"),
        ("ssm:GetParameter", f"arn:aws:ssm:{REGION}:{ACCT}:parameter/life-platform/*", "ssm-parameter-tree"),
        ("dynamodb:Query", f"arn:aws:dynamodb:{REGION}:{ACCT}:table/life-platform/index/*", "dynamodb-index"),
        ("logs:PutLogEvents", f"arn:aws:logs:{REGION}:{ACCT}:log-group:/aws/lambda/daily-brief:*", "log-group-streams"),
    ],
)
def test_established_wildcard_shapes_are_admitted__review_N3(base, action, resource, shape):
    assert g_reg.wildcard_resource_shape(resource) == shape
    dep, syn = _fresh(base)
    _stmts(syn).append({"Action": action, "Effect": "Allow", "Sid": "Shaped", "Resource": resource})
    v = _ev(dep, syn)
    assert v.verdict == g.ALLOW, (resource, v.findings)


# ── fail closed: anything unevaluable is OWNER-REQUIRED ────────────────────────────


@pytest.mark.parametrize("deployed", ["Resources:\n  Foo: bar\n", None, 42, {"NoResources": {}}, []])
def test_unparseable_deployed_side_is_owner_required(base, deployed):
    v = _ev(deployed, copy.deepcopy(base))
    assert v.verdict == g.OWNER and v.unevaluable and "unevaluable" in _kinds(v)


def test_unparseable_policy_document_is_owner_required(base):
    dep, syn = _fresh(base)
    syn["Resources"][POLICY]["Properties"]["PolicyDocument"] = {"Statement": "not-a-list"}
    v = _ev(dep, syn)
    assert v.verdict == g.OWNER and "unparseable-policy-document" in _kinds(v)


def _write_synth(tmp_path: Path, template: dict, stack: str = STACK, account: str = ACCT) -> Path:
    synth = tmp_path / "cdk.out"
    synth.mkdir(parents=True, exist_ok=True)
    (synth / f"{stack}.template.json").write_text(json.dumps(template))
    manifest = {
        "artifacts": {
            stack: {
                "type": "aws:cloudformation:stack",
                "environment": f"aws://{account}/{REGION}",
                "properties": {"templateFile": f"{stack}.template.json"},
            }
        }
    }
    (synth / "manifest.json").write_text(json.dumps(manifest))
    return synth


def _run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(ROOT / "deploy" / "iam_additive_gate.py"), *args], capture_output=True, text=True, cwd=ROOT, timeout=120
    )


def test_cli_exit_codes_and_github_output(base, tmp_path):
    synth_t = copy.deepcopy(base)
    _stmts(synth_t).append(dict(NEW_ALLOW))
    synth = _write_synth(tmp_path, synth_t)
    deployed = tmp_path / "deployed"
    deployed.mkdir()
    (deployed / f"{STACK}.template.json").write_text(json.dumps(base))
    out = tmp_path / "gh.out"
    rec = tmp_path / "rec.json"

    p = _run("--synth-dir", str(synth), "--deployed-dir", str(deployed), "--github-output", str(out), "--json", str(rec))
    assert p.returncode == 0, p.stdout + p.stderr
    assert "ALLOW-ADDITIVE" in p.stdout and "ContentFilterRead" in p.stdout
    assert f"iam_gate_verdict={g.ALLOW}\niam_additive_stacks={STACK}\n" == out.read_text()
    record = json.loads(rec.read_text())
    assert record["gate"] == "iam_additive_gate" and record["issue"] == 2834
    assert record["registry_fingerprint"] == g.registry_fingerprint()
    assert record["stacks"][STACK]["admitted"][0]["sid"] == "ContentFilterRead"

    # --expect-converged: the IAM diff is still present → exit 1
    assert _run("--synth-dir", str(synth), "--deployed-dir", str(deployed), "--expect-converged").returncode == 1
    # converged (deployed == synth) → exit 0 and NO stacks to deploy
    (deployed / f"{STACK}.template.json").write_text(json.dumps(synth_t))
    out2 = tmp_path / "gh2.out"
    p = _run("--synth-dir", str(synth), "--deployed-dir", str(deployed), "--expect-converged", "--github-output", str(out2))
    assert p.returncode == 0 and f"iam_gate_verdict={g.NO_CHANGE}\niam_additive_stacks=\n" == out2.read_text()

    # OWNER-REQUIRED → exit 1 and the owner path is printed
    bad = copy.deepcopy(base)
    _stmts(bad).append({"Action": "iam:PassRole", "Effect": "Allow", "Sid": "Bad", "Resource": f"arn:aws:iam::{ACCT}:role/x"})
    (synth / f"{STACK}.template.json").write_text(json.dumps(bad))
    p = _run("--synth-dir", str(synth), "--deployed-dir", str(deployed))
    assert p.returncode == 1 and "OWNER-REQUIRED" in p.stdout and "cdk_deploy.sh" in p.stdout and "iam:PassRole" in p.stdout


def test_cli_fails_closed_on_unevaluable_input(base, tmp_path):
    """Dead-man: missing deployed template, missing manifest, foreign account → exit 2 + OWNER-REQUIRED."""
    synth = _write_synth(tmp_path, base)
    empty = tmp_path / "empty"
    empty.mkdir()
    p = _run("--synth-dir", str(synth), "--deployed-dir", str(empty))
    assert p.returncode == 2 and "OWNER-REQUIRED" in p.stdout and "UNEVALUABLE" in p.stdout

    p = _run("--synth-dir", str(empty), "--deployed-dir", str(empty))
    assert p.returncode == 2 and "OWNER-REQUIRED" in p.stdout

    foreign = _write_synth(tmp_path / "f", base, account="999999999999")
    (empty / f"{STACK}.template.json").write_text(json.dumps(base))
    p = _run("--synth-dir", str(foreign), "--deployed-dir", str(empty))
    assert p.returncode == 2 and "not the platform account" in p.stdout

    # a stack asked for that the manifest does not know → unevaluable, never silently skipped
    p = _run("--synth-dir", str(synth), "--deployed-dir", str(empty), "--stacks", "LifePlatformNope")
    assert p.returncode == 2 and "LifePlatformNope" in p.stdout


def test_cli_writes_the_admitted_statements_to_the_step_summary__review_R4(base, tmp_path):
    """R4: the `production` approver reads the run page, not a collapsed ::group:: and not
    an S3 ledger. The admitted statements have to be ON that page."""
    synth_t = copy.deepcopy(base)
    _stmts(synth_t).append(dict(NEW_ALLOW))
    synth = _write_synth(tmp_path, synth_t)
    deployed = tmp_path / "deployed"
    deployed.mkdir()
    (deployed / f"{STACK}.template.json").write_text(json.dumps(base))
    summary = tmp_path / "summary.md"

    p = _run("--synth-dir", str(synth), "--deployed-dir", str(deployed), "--step-summary", str(summary))
    assert p.returncode == 0, p.stdout + p.stderr
    text = summary.read_text()
    assert g.ALLOW in text and STACK in text
    assert "ContentFilterRead" in text and NEW_ALLOW["Action"] in text and NEW_ALLOW["Resource"] in text
    assert ROLE in text, "the approver needs to see WHICH role gains the statement"
    assert g.registry_fingerprint() in text
    assert text.count("|---") >= 1, "the summary must render as a markdown table"

    # the OWNER-REQUIRED half: every finding is named on the same page, and it APPENDS
    bad = copy.deepcopy(base)
    _stmts(bad).append({"Action": "iam:PassRole", "Effect": "Allow", "Sid": "Bad", "Resource": f"arn:aws:iam::{ACCT}:role/x"})
    (synth / f"{STACK}.template.json").write_text(json.dumps(bad))
    p = _run("--synth-dir", str(synth), "--deployed-dir", str(deployed), "--step-summary", str(summary))
    assert p.returncode == 1
    text2 = summary.read_text()
    assert text2.startswith(text), "the summary file is appended to, never truncated (other steps write there too)"
    assert "OWNER-REQUIRED findings" in text2 and "forbidden-action" in text2 and "iam:PassRole" in text2


def test_cli_refuses_a_stack_name_that_is_not_a_shell_word__review_N1(base, tmp_path):
    """N1: every admitted stack name is word-split into `npx cdk deploy "$STACK"`. A name
    outside CloudFormation's own grammar is a corrupt manifest or a smuggled shell word."""
    deployed = tmp_path / "deployed"
    deployed.mkdir()
    (deployed / f"{STACK}.template.json").write_text(json.dumps(base))

    evil = tmp_path / "evil"
    evil.mkdir()
    (evil / "t.template.json").write_text(json.dumps(base))
    (evil / "manifest.json").write_text(
        json.dumps(
            {
                "artifacts": {
                    "Life; rm -rf /": {
                        "type": "aws:cloudformation:stack",
                        "environment": f"aws://{ACCT}/{REGION}",
                        "properties": {"templateFile": "t.template.json"},
                    }
                }
            }
        )
    )
    p = _run("--synth-dir", str(evil), "--deployed-dir", str(deployed))
    assert p.returncode == 2 and "OWNER-REQUIRED" in p.stdout
    assert "refusing to pass it to a shell" in p.stdout

    # and via --stacks, the other door onto the same shell line
    synth = _write_synth(tmp_path, base)
    p = _run("--synth-dir", str(synth), "--deployed-dir", str(deployed), "--stacks", "LifePlatformEmail $(id)")
    assert p.returncode == 2 and "refusing to pass it to a shell" in p.stdout

    # the positive control: the real name still evaluates
    assert g.validate_stack_name(STACK) == STACK
    for ok in ("LifePlatformEmail", "A", "a-b-c9"):
        assert g.validate_stack_name(ok) == ok
    for bad in ("", "9Stack", "-Stack", "Life Platform", "Life;rm", "Life_Platform", "Life\nPlatform"):
        with pytest.raises(ValueError):
            g.validate_stack_name(bad)
