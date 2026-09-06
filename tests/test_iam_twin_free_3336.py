"""tests/test_iam_twin_free_3336.py — the IAM derivation guard (#3336, epic #2842).

THE INCIDENT (2026-08-30, docs/INCIDENT_LOG.md). `deploy/setup_remediation_role.sh`
was a hand-maintained twin of `infra/iam/github-actions-remediation-role.{trust,
permissions}.json`. Its header said "the JSON wins"; nothing enforced it; the twin was
the copy that RAN. One post-merge run put its stale documents live: 15 of the JSON's 17
statements (four grants gone, because `put-role-policy` replaces the whole document)
and the pre-#687 trust subject `repo:averagejoematt/life-platform:*` — any ref of a
public repo could assume the role for ≈6 minutes. `verify_oidc_iam.py --strict` (the
#401 dead-man) caught it; the JSON restored it. The guard that should have made the
drift impossible did not exist, and #3321's own test cemented the twin by asserting a
grant string INSIDE the shell script.

WHAT IS PROVED HERE (the derivation-guard primitive, docs/CHARTER.md)
  A. no file under `deploy/` embeds an IAM policy document (the `"Version": "2012-10-17"`
     + `"Statement"` + `"Effect"` shape) that names a role with a checked-in
     `infra/iam/<role>.*.json` — the ONLY copies of those documents are the JSON files
  B. mutation proofs for the detector: a planted heredoc and a planted Python string both
     RED; policy-READING code (`policy.get("Statement")`) and a document for a role that
     has no `infra/iam/` JSON (a Lambda exec role) are NOT findings — the guard is scoped
     to the OIDC identities `verify_oidc_iam.py` owns, nothing looser, nothing stricter
  C. the apply scripts are derived: every `--policy-document` / `--assume-role-policy-
     document` they pass is a `file://` reference, they name the governed JSON files, and
     their inline policy name equals what the verifier reads back
  D. the incident's exact regression is pinned at the source: every governed role's trust
     subject is scoped to this repo and none is the any-ref wildcard
  E. (#3562, 2026-09-05) `Resource: "*"` appears only for actions on a dated registry of
     account-level ones. The remediation role granted `ses:SendEmail`/`sesv2:SendEmail`
     and `logs:GetLogEvents`/`FilterLogEvents` on `*` — both scopeable — so a compromised
     Mon/Wed/Fri workflow could send from any verified SES identity and read every
     Lambda's logs. Contrast the 38 `resources=["*"]` statements in
     `cdk/stacks/role_policies_*.py`, all on account-level actions: section E holds BOTH
     sources to that one registry.

All offline: the tests read repo files only; no AWS call.
"""

from __future__ import annotations

import ast
import json
import os
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
IAM_DIR = ROOT / "infra" / "iam"
DEPLOY_DIR = ROOT / "deploy"

if str(DEPLOY_DIR) not in sys.path:
    sys.path.insert(0, str(DEPLOY_DIR))

import verify_oidc_iam  # noqa: E402  (module-level imports are stdlib only; boto3 is inside main())

# ── the detector ─────────────────────────────────────────────────────────────
# An embedded IAM policy DOCUMENT is unambiguous: the policy-language version literal
# plus a Statement array with an Effect. Code that merely READS policies
# (`policy.get("Statement", [])`) never carries the version literal, so it is not a
# finding — see the mutation proofs below.
_DOC_MARKER = re.compile(r'"Version"\s*:\s*"2012-10-17"')
_STATEMENT = re.compile(r'"Statement"\s*:')
_EFFECT = re.compile(r'"Effect"\s*:')
_POLICY_DOC_ARG = re.compile(r"--(?:assume-role-)?policy-document\s+(\S+)")

SCANNED_SUFFIXES = (".sh", ".py")


def governed_roles() -> dict[str, dict[str, Path]]:
    """Every role with a checked-in document under infra/iam/ → its trust/permissions paths."""
    roles: dict[str, dict[str, Path]] = {}
    for p in sorted(IAM_DIR.glob("*.json")):
        stem = p.name
        for kind in ("trust", "permissions"):
            suffix = f".{kind}.json"
            if stem.endswith(suffix):
                roles.setdefault(stem[: -len(suffix)], {})[kind] = p
    return roles


def find_inline_policy_documents(text: str, rel_path: str, roles) -> list[str]:
    """Findings for ONE file's text: one line per governed role the embedded document names."""
    if not (_DOC_MARKER.search(text) and _STATEMENT.search(text) and _EFFECT.search(text)):
        return []
    return [
        f"{rel_path}: embeds an IAM policy document that names {role} — the only copy of that role's "
        f"documents is infra/iam/{role}.*.json; apply it with --policy-document file://… instead"
        for role in sorted(roles)
        if role in text
    ]


def sweep(root: Path, roles) -> list[str]:
    findings: list[str] = []
    for p in sorted(root.rglob("*")):
        if p.suffix not in SCANNED_SUFFIXES or not p.is_file():
            continue
        findings.extend(find_inline_policy_documents(p.read_text(encoding="utf-8", errors="replace"), str(p.relative_to(ROOT)), roles))
    return findings


# ═════════════════════════════════════════════════════════════════════════════
# A. the guard, on the real tree
# ═════════════════════════════════════════════════════════════════════════════
def test_governed_roles_are_exactly_the_verifier_owned_identities():
    """The role set the guard protects is derived from infra/iam/ and must equal what
    verify_oidc_iam.py diffs against live — one registry, read from both ends."""
    roles = governed_roles()
    assert set(roles) == set(verify_oidc_iam.ROLES), (set(roles), set(verify_oidc_iam.ROLES))
    for role, files in roles.items():
        assert {"trust", "permissions"} <= set(files), f"{role} is missing a trust or permissions JSON"
        for p in files.values():
            doc = json.loads(p.read_text(encoding="utf-8"))
            assert doc["Version"] == "2012-10-17" and doc["Statement"], p


def test_no_deploy_script_embeds_a_policy_document_for_a_governed_role():
    findings = sweep(DEPLOY_DIR, governed_roles())
    assert not findings, "inline IAM policy twins under deploy/ (#3336):\n  " + "\n  ".join(findings)


# ═════════════════════════════════════════════════════════════════════════════
# B. mutation proofs — the detector against planted defects (no real file touched)
# ═════════════════════════════════════════════════════════════════════════════
_PLANTED_HEREDOC = """#!/usr/bin/env bash
ROLE="github-actions-remediation-role"
PERM=$(cat <<JSON
{"Version":"2012-10-17","Statement":[{"Sid":"Bedrock","Effect":"Allow","Action":"bedrock:InvokeModel","Resource":"*"}]}
JSON
)
aws iam put-role-policy --role-name "$ROLE" --policy-name remediation-permissions --policy-document "$PERM"
"""

_PLANTED_PY_STRING = '''
TRUST = """{
  "Version": "2012-10-17",
  "Statement": [{"Effect": "Allow", "Principal": {"Federated": "x"}, "Action": "sts:AssumeRoleWithWebIdentity"}]
}"""
iam.update_assume_role_policy(RoleName="github-actions-deploy-role", PolicyDocument=TRUST)
'''

_READER_ONLY = """
role = iam.get_role(RoleName="github-actions-remediation-role")
for st in policy.get("Statement", []):
    if st.get("Effect") == "Allow":
        actions.update(st["Action"])
"""

_UNGOVERNED_ROLE_DOC = """
ROLE_NAME="life-platform-email-subscriber-role"
aws iam create-role --role-name "$ROLE_NAME" --assume-role-policy-document '{
  "Version": "2012-10-17",
  "Statement": [{"Effect": "Allow", "Principal": {"Service": "lambda.amazonaws.com"}, "Action": "sts:AssumeRole"}]
}'
"""


def test_detector_reds_on_a_planted_shell_heredoc_twin():
    found = find_inline_policy_documents(_PLANTED_HEREDOC, "deploy/planted.sh", governed_roles())
    assert len(found) == 1 and "github-actions-remediation-role" in found[0], found


def test_detector_reds_on_a_planted_python_string_twin():
    found = find_inline_policy_documents(_PLANTED_PY_STRING, "deploy/planted.py", governed_roles())
    assert len(found) == 1 and "github-actions-deploy-role" in found[0], found


def test_detector_ignores_code_that_only_reads_policies():
    assert find_inline_policy_documents(_READER_ONLY, "deploy/reader.py", governed_roles()) == []


def test_detector_ignores_documents_for_roles_without_a_checked_in_json():
    """A Lambda execution role bootstrapped inline (setup_email_subscriber.sh) has no
    infra/iam/ source of truth to twin — out of this guard's scope by construction,
    and NOT a licence: the moment such a role gains an infra/iam/ JSON, it is governed."""
    assert find_inline_policy_documents(_UNGOVERNED_ROLE_DOC, "deploy/setup_email_subscriber.sh", governed_roles()) == []


def test_planted_twin_in_a_tree_is_found_by_the_sweep(tmp_path):
    (tmp_path / "ok.sh").write_text('aws iam put-role-policy --policy-document "file://x.json"\n', encoding="utf-8")
    (tmp_path / "twin.sh").write_text(_PLANTED_HEREDOC, encoding="utf-8")
    (tmp_path / "notes.md").write_text(_PLANTED_HEREDOC, encoding="utf-8")  # not a scanned suffix
    found = sweep(tmp_path, governed_roles()) if tmp_path.is_relative_to(ROOT) else _sweep_outside_root(tmp_path)
    assert len(found) == 1 and "twin.sh" in found[0], found


def _sweep_outside_root(root: Path) -> list[str]:
    # tmp_path is normally outside the repo; relative_to(ROOT) would raise, so path-label by name.
    findings: list[str] = []
    for p in sorted(root.rglob("*")):
        if p.suffix in SCANNED_SUFFIXES and p.is_file():
            findings.extend(find_inline_policy_documents(p.read_text(encoding="utf-8"), p.name, governed_roles()))
    return findings


# ═════════════════════════════════════════════════════════════════════════════
# C. the apply scripts are DERIVED from the JSON, not parallel to it
# ═════════════════════════════════════════════════════════════════════════════
APPLY_SCRIPTS = {
    "github-actions-remediation-role": DEPLOY_DIR / "setup_remediation_role.sh",
    "github-actions-deploy-role": DEPLOY_DIR / "setup_github_oidc.sh",
}


@pytest.mark.parametrize("role", sorted(APPLY_SCRIPTS))
def test_apply_script_passes_only_file_references_and_names_the_governed_json(role):
    script = APPLY_SCRIPTS[role]
    text = script.read_text(encoding="utf-8")
    rel = script.relative_to(ROOT)

    args = _POLICY_DOC_ARG.findall(text)
    assert args, f"{rel}: no --policy-document at all — it no longer applies anything?"
    for arg in args:
        assert arg.strip('"').startswith("file://"), f"{rel}: --policy-document {arg} is not a file:// reference to infra/iam/"

    for kind in ("trust", "permissions"):
        assert f"{role}.{kind}.json" in text, f"{rel}: must apply infra/iam/{role}.{kind}.json by name"

    for verb in ("create-role", "update-assume-role-policy", "put-role-policy"):
        assert f"aws iam {verb}" in text, f"{rel}: lost the `aws iam {verb}` step"

    expected_policy_name = verify_oidc_iam.ROLES[role]["inline_policy_name"]
    assert (
        f'POLICY_NAME="{expected_policy_name}"' in text
    ), f"{rel}: inline policy name must be {expected_policy_name!r} — that is the name verify_oidc_iam.py reads back"
    assert "verify_oidc_iam.py" in text and "--strict" in text, f"{rel}: the apply must end with the read-only verifier as its proof"


def test_verifier_docstring_records_the_one_source_rule():
    doc = verify_oidc_iam.__doc__ or ""
    assert "#3336" in doc and "setup_remediation_role.sh" in doc and "file://" in doc


# ═════════════════════════════════════════════════════════════════════════════
# D. the incident's regression, pinned at the source
# ═════════════════════════════════════════════════════════════════════════════
def _trust_subjects(doc) -> list[str]:
    subs: list[str] = []
    for st in doc["Statement"]:
        like = st.get("Condition", {}).get("StringLike", {}).get("token.actions.githubusercontent.com:sub")
        eq = st.get("Condition", {}).get("StringEquals", {}).get("token.actions.githubusercontent.com:sub")
        for v in (like, eq):
            if isinstance(v, str):
                subs.append(v)
            elif isinstance(v, list):
                subs.extend(v)
    return subs


def test_remediation_role_trust_is_main_only():
    doc = json.loads((IAM_DIR / "github-actions-remediation-role.trust.json").read_text(encoding="utf-8"))
    assert _trust_subjects(doc) == ["repo:averagejoematt/life-platform:ref:refs/heads/main"]


@pytest.mark.parametrize("role", sorted(governed_roles()))
def test_no_governed_role_trusts_the_any_ref_wildcard(role):
    doc = json.loads((IAM_DIR / f"{role}.trust.json").read_text(encoding="utf-8"))
    subs = _trust_subjects(doc)
    assert subs, f"{role}: trust has no OIDC subject condition at all"
    for sub in subs:
        assert sub.startswith("repo:averagejoematt/life-platform:"), (role, sub)
        assert not sub.endswith(":*"), f"{role}: {sub!r} is the any-ref subject the 2026-08-30 twin put live"


# ═════════════════════════════════════════════════════════════════════════════
# E. Resource:"*" only where AWS gives no narrower handle (#3562)
# ═════════════════════════════════════════════════════════════════════════════

#: Actions allowed to carry `Resource: "*"`, each with WHY. Membership was probed
#: on 2026-09-05 with `aws iam simulate-custom-policy` (read-only): granting the
#: action on the narrowest plausible ARN and simulating the live request shape.
#:
#:   no-resource        the probe implicitDenies — the call carries no scopeable
#:                      resource at all, so a narrower ARN denies it outright
#:   account-wide-read  an enumerate-the-account read whose answer IS the account
#:                      (the set the 38 CDK `resources=["*"]` statements satisfy)
#:
#: RATCHET: this registry may only SHRINK. Adding an action here widens every role
#: that names it at once, so a new entry needs its own argument in its own PR.
_WILDCARD_OK_ACTIONS = {
    "ce:GetCostAndUsage": "no-resource",
    "cloudformation:DescribeStackDriftDetectionStatus": "no-resource",  # takes a detection id
    "cloudformation:ListStacks": "no-resource",
    "cloudformation:ValidateTemplate": "no-resource",
    "ec2:DescribeRegions": "no-resource",
    "events:ListRules": "no-resource",
    "lambda:ListFunctions": "no-resource",
    "logs:DescribeLogGroups": "no-resource",
    "secretsmanager:ListSecrets": "no-resource",
    "xray:GetSamplingRules": "no-resource",
    "xray:GetSamplingTargets": "no-resource",
    "xray:PutTelemetryRecords": "no-resource",
    "xray:PutTraceSegments": "no-resource",
    "cloudwatch:DescribeAlarmHistory": "account-wide-read",
    "cloudwatch:DescribeAlarms": "account-wide-read",
    "cloudwatch:GetMetricData": "account-wide-read",
    "cloudwatch:GetMetricStatistics": "account-wide-read",
    "cloudwatch:ListMetrics": "account-wide-read",
    # PutMetricData takes no resource at all — its ONLY handle is the namespace
    # condition, which the stricter rule below requires of the OIDC identities.
    "cloudwatch:PutMetricData": "no-resource",
}

#: A SECOND, stricter rule applied to the four OIDC identities only: their one
#: resourceless write must still name the namespace it may write. All three of their
#: PutMetricData statements already do (`LifePlatform/AI`, `LifePlatform/GoldenBrief`),
#: so this is a ratchet holding a posture that is already met, not a new demand.
#:
#: The CDK Lambda fleet does NOT meet it — ~30 `role_policies_*` statements grant
#: PutMetricData on `*` with no condition. That is a real, pre-existing difference
#: between the two halves, out of #3562's scope (it is a fleet-wide deploy change),
#: recorded here rather than silently folded into the registry.
_WILDCARD_REQUIRES_CONDITION = {"cloudwatch:PutMetricData": "cloudwatch:namespace"}

#: Wildcards on SCOPEABLE actions that are not narrowed yet. Dated, argued, and
#: SHRINK-ONLY: `test_the_deferral_queue_only_shrinks` reds when an entry becomes
#: stale, so this cannot quietly become a graveyard. #3562 narrowed the remediation
#: role; the deploy role is deliberately NOT in this PR — its CloudFormation reads
#: include the CDKToolkit bootstrap stack and whatever stack `cdk diff` resolves, so
#: narrowing it is a deploy-path change that has to be argued (and rehearsed) on its
#: own rather than ridden in on a security-boundary fix to a different identity.
_WILDCARD_SCOPING_DEFERRED = {
    ("github-actions-deploy-role", "EventBridge", "events:DescribeRule"): "2026-09-05 (#3562): deploy path, own issue",
    ("github-actions-deploy-role", "EventBridge", "events:ListTargetsByRule"): "2026-09-05 (#3562): deploy path, own issue",
    ("github-actions-deploy-role", "CloudFormationDiff", "cloudformation:DescribeStacks"): "2026-09-05 (#3562): reads CDKToolkit too",
    (
        "github-actions-deploy-role",
        "CloudFormationDiff",
        "cloudformation:DescribeStackResource",
    ): "2026-09-05 (#3562): reads CDKToolkit too",
    ("github-actions-deploy-role", "CloudFormationDiff", "cloudformation:GetTemplate"): "2026-09-05 (#3562): reads CDKToolkit too",
    ("github-actions-deploy-role", "CloudFormationDiff", "cloudformation:ListStackResources"): "2026-09-05 (#3562): reads CDKToolkit too",
    ("github-actions-deploy-role", "CloudFormationDiff", "cloudformation:DescribeStackEvents"): "2026-09-05 (#3562): reads CDKToolkit too",
    ("github-actions-deploy-role", "CloudFormationDiff", "cloudformation:DescribeStackSet"): "2026-09-05 (#3562): stackset, own issue",
}

_DEFERRAL_DATE = re.compile(r"^\d{4}-\d{2}-\d{2} \(#\d+\): \S")


def _as_list(v):
    return v if isinstance(v, list) else [v]


def wildcard_grants_in(doc: dict, role: str) -> list[tuple]:
    """(role, Sid, action, has_condition, condition_keys) for every `Resource: "*"` action."""
    out = []
    for st in doc.get("Statement", []):
        if "*" not in _as_list(st.get("Resource")):
            continue
        keys = set()
        for _op, kv in (st.get("Condition") or {}).items():
            keys |= set(kv)
        for action in _as_list(st.get("Action")):
            out.append((role, st.get("Sid"), action, bool(st.get("Condition")), keys))
    return out


def all_declared_wildcards() -> list[tuple]:
    return [
        g
        for role, files in sorted(governed_roles().items())
        for g in wildcard_grants_in(json.loads(files["permissions"].read_text(encoding="utf-8")), role)
    ]


def _offenders(grants, require_conditions: bool = True) -> list[str]:
    """The rule itself, over a grant list — pure, so it can be positively controlled.

    `require_conditions` turns on the stricter OIDC-identity half; the CDK fleet is
    swept against the registry alone (see _WILDCARD_REQUIRES_CONDITION's note)."""
    bad = []
    for role, sid, action, has_cond, keys in grants:
        if require_conditions and action in _WILDCARD_REQUIRES_CONDITION:
            need = _WILDCARD_REQUIRES_CONDITION[action]
            if not has_cond or need not in keys:
                bad.append(f"{role}/{sid}: {action} on Resource:* without its required {need} condition")
            continue
        if action in _WILDCARD_OK_ACTIONS:
            continue
        if (role, sid, action) in _WILDCARD_SCOPING_DEFERRED:
            continue
        bad.append(f"{role}/{sid}: {action} on Resource:* — scopeable, and not on the account-level registry")
    return bad


def test_no_wildcard_resource_on_a_scopeable_action():
    """#3562. The remediation role's `ses:SendEmail`/`sesv2:SendEmail` and
    `logs:GetLogEvents`/`logs:FilterLogEvents` were the finding: both take a resource
    (an SES identity ARN, a log-group ARN) and both were granted on `*`."""
    grants = all_declared_wildcards()
    assert grants, "no Resource:* statement found in any governed permissions doc — the sweep broke, not the docs"
    assert not _offenders(grants), "wildcard resource on a scopeable action:\n  " + "\n  ".join(_offenders(grants))


def test_the_remediation_role_ses_and_log_grants_name_what_they_need():
    """The specific regressions, pinned by shape rather than only by the rule above —
    a future edit that re-broadened them would otherwise only trip the generic message."""
    doc = json.loads((IAM_DIR / "github-actions-remediation-role.permissions.json").read_text(encoding="utf-8"))
    by_action: dict[str, list] = {}
    for st in doc["Statement"]:
        for a in _as_list(st.get("Action")):
            by_action.setdefault(a, []).extend(_as_list(st.get("Resource")))
            if a in ("ses:SendEmail", "sesv2:SendEmail"):
                cond = (st.get("Condition") or {}).get("StringEquals", {})
                assert "ses:FromAddress" in cond, f"{a}: SES grant must pin the From address, not just the identity"
    for action in ("ses:SendEmail", "sesv2:SendEmail"):
        assert by_action[action] == ["arn:aws:ses:us-west-2:205930651321:identity/mattsusername.com"], by_action[action]
    for action in ("logs:GetLogEvents", "logs:FilterLogEvents"):
        assert by_action[action] and all(r.startswith("arn:aws:logs:") and ":log-group:/aws/" in r for r in by_action[action]), by_action[
            action
        ]


def _cdk_wildcard_actions() -> list[tuple]:
    """The CDK half: every `resources=["*"]` PolicyStatement in the role-policy family."""
    out = []
    for src in sorted((ROOT / "cdk" / "stacks").glob("role_policies_*.py")) + [ROOT / "cdk" / "stacks" / "lambda_helpers.py"]:
        tree = ast.parse(src.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            kw = {k.arg: k.value for k in node.keywords if k.arg}
            res = kw.get("resources")
            if not isinstance(res, ast.List) or [e.value for e in res.elts if isinstance(e, ast.Constant)] != ["*"]:
                continue
            actions = kw.get("actions")
            names = [e.value for e in actions.elts if isinstance(e, ast.Constant)] if isinstance(actions, ast.List) else []
            keys = set()
            cond = kw.get("conditions")
            if isinstance(cond, ast.Dict):
                for v in cond.values:
                    if isinstance(v, ast.Dict):
                        keys |= {k.value for k in v.keys if isinstance(k, ast.Constant)}
            for a in names:
                out.append((f"cdk:{src.name}", f"line {node.lineno}", a, bool(keys), keys))
    return out


def test_the_cdk_role_policies_satisfy_the_same_registry():
    """One registry, both sources. The CDK sweep was the review's own control ('all 38
    are on non-scopeable actions'); if that is true it must pass the identical rule, and
    if it stops being true this reds instead of the claim quietly rotting."""
    grants = _cdk_wildcard_actions()
    assert len(grants) >= 12, f"the CDK wildcard sweep found only {len(grants)} actions — the AST walk broke"
    bad = _offenders(grants, require_conditions=False)
    assert not bad, "CDK wildcard resource on a scopeable action:\n  " + "\n  ".join(bad)


def test_the_deferral_queue_only_shrinks():
    """Every deferred entry must still be a live wildcard in the docs. Once it is
    narrowed, the entry must be deleted — a queue, not a graveyard (#2824's rule)."""
    live = {(role, sid, action) for role, sid, action, _c, _k in all_declared_wildcards()}
    stale = sorted(k for k in _WILDCARD_SCOPING_DEFERRED if k not in live)
    assert not stale, "these deferrals are already narrowed — delete them:\n  " + "\n  ".join(map(str, stale))
    for key, reason in _WILDCARD_SCOPING_DEFERRED.items():
        assert _DEFERRAL_DATE.match(reason), f"{key}: deferral needs a `YYYY-MM-DD (#issue): reason` line, got {reason!r}"


def test_the_wildcard_rule_reds_on_a_planted_grant():
    """Positive control. The rule must FAIL on each of the three shapes it exists to
    catch, and PASS on the narrowed real ones — otherwise it is a check that cannot."""
    assert _offenders([("r", "SES", "sesv2:SendEmail", False, set())]), "a wildcard SES send would not be caught"
    assert _offenders([("r", "Diagnose", "logs:GetLogEvents", False, set())]), "a wildcard log read would not be caught"
    assert _offenders([("r", "Telem", "cloudwatch:PutMetricData", False, set())]), "an unconditioned OIDC PutMetricData would not be caught"
    assert not _offenders([("r", "Telem", "cloudwatch:PutMetricData", True, {"cloudwatch:namespace"})])
    assert not _offenders([("r", "DiagnoseAccountLevel", "logs:DescribeLogGroups", False, set())])
    # …and the CDK half, which is swept against the registry alone, must NOT red on the
    # fleet's unconditioned PutMetricData — otherwise the two halves silently disagree.
    assert not _offenders([("cdk", "line 1", "cloudwatch:PutMetricData", False, set())], require_conditions=False)
    assert _offenders([("cdk", "line 1", "ses:SendEmail", False, set())], require_conditions=False)


def test_scanned_tree_is_the_deploy_dir_and_exists():
    assert DEPLOY_DIR.is_dir() and os.access(DEPLOY_DIR, os.R_OK)
