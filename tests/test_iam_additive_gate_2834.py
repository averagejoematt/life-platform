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
    assert _ev(dep, syn).verdict == g.ALLOW


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
