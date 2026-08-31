#!/usr/bin/env python3
"""
deploy/verify_oidc_iam.py — read-only drift check for the OIDC automation identities (#401 / ADR-120).

The two highest-privilege roles in the account — the CI/CD deploy role
(`github-actions-deploy-role`) and the self-healing remediation role
(`github-actions-remediation-role`) — plus the GitHub OIDC identity-federation
provider gate ALL automated deploys and the remediation agent's cloud access.
Before #401 they existed only as hand-managed AWS config with no source of truth
in the repo. This script makes them reviewable: the checked-in JSON under
`infra/iam/` is the source of truth, and this diffs it against what is live so any
out-of-band change (or a not-yet-applied tighten) shows up as loud, actionable drift.

It is STRICTLY READ-ONLY. It only calls:
  iam:GetRole, iam:GetRolePolicy, iam:GetOpenIDConnectProvider,
  iam:GetPolicy, iam:GetPolicyVersion   (the #3340 boundary read)
It never mutates anything. Applying a trust change is a separate, deliberate,
watched step — see infra/iam/README.md.

THE CFN-EXEC PERMISSIONS BOUNDARY (#3340). Since 2026-08-31 this script also asserts
that each of the three `cdk-<qualifier>-cfn-exec-role-<acct>-<region>` roles carries the
permissions boundary rendered by `deploy/derive_cfn_exec_boundary.py`, and that the live
document equals the committed `infra/iam/cdk-cfn-exec-boundary.permissions.json`. That
role is what CloudFormation acts as; it carries AdministratorAccess, and until the
boundary is attached, CI's additive-IAM gate (#2834) is the ONLY line. The three
possible findings are all RED under `--strict`, deliberately:

  BOUNDARY-MISSING     no boundary on the role — the pending #3340 apply, or a removal
  BOUNDARY-DRIFT       a boundary is attached but it is not this policy / not this document
  BOUNDARY-UNREADABLE  the calling identity cannot read the role or the policy version

`BOUNDARY-UNREADABLE` is a FINDING, not a skip: a boundary nobody can read is
indistinguishable from a boundary that is not there, and "the check could not run" has
never been a pass in this repo. It is what the weekly `drift_sentinel.check_oidc_iam`
run sees today — the remediation role's `IAMRoleRead` is scoped to the four OIDC roles —
so the enforcing runner for this assertion is the owner/driver `--strict` invocation
under `matthew-admin`. That gap, and the fact that `check_oidc_iam` calls this script
WITHOUT `--strict` (so its exit code is always 0), are stated in the ADR-065 amendment
of 2026-08-31 as named residuals rather than left for someone to discover.

ONE SOURCE (#3336). The checked-in JSON is applied VERBATIM by the operator scripts
`deploy/setup_remediation_role.sh` and `deploy/setup_github_oidc.sh`
(`aws iam update-assume-role-policy … --policy-document file://infra/iam/<role>.trust.json`,
`aws iam put-role-policy … --policy-document file://infra/iam/<role>.permissions.json`,
create-role-if-missing from the trust file). Until 2026-08-30 both scripts carried
their OWN inline copies of these documents — a hand-maintained shell twin with no
derivation guard — and the remediation one, run post-merge, put 15 of the JSON's 17
statements and a repo-wide (any-ref) trust subject live for ≈6 minutes before this
verifier caught it (docs/INCIDENT_LOG.md). The shell twins are gone:
`tests/test_iam_twin_free_3336.py` fails the suite if an inline policy document for
any role in ROLES reappears under deploy/. This script therefore guards ONE source
against live, not two repo copies against each other.

Comparison is SEMANTIC, not byte-for-byte: policy documents are canonicalised
(dict keys sorted, string lists sorted, statement lists order-normalised) so that
cosmetic ordering differences between the checked-in JSON and what IAM returns do
not read as drift.

Usage:
    python3 deploy/verify_oidc_iam.py            # print report, exit 0 always
    python3 deploy/verify_oidc_iam.py --strict   # exit 1 if any drift is found (CI/sentinel gate)
    python3 deploy/verify_oidc_iam.py --json      # machine-readable findings to stdout
"""

from __future__ import annotations

import argparse
import json
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_IAM_DIR = os.path.join(_ROOT, "infra", "iam")
sys.path.insert(0, os.path.join(_ROOT, "deploy"))

OIDC_PROVIDER_ARN = "arn:aws:iam::205930651321:oidc-provider/token.actions.githubusercontent.com"

# The identities this script owns. Each role maps to its checked-in trust policy and
# inline permissions policy (the live PolicyName that carries them).
ROLES = {
    "github-actions-deploy-role": {
        "trust_file": "github-actions-deploy-role.trust.json",
        "permissions_file": "github-actions-deploy-role.permissions.json",
        "inline_policy_name": "life-platform-cicd-permissions",
    },
    "github-actions-remediation-role": {
        "trust_file": "github-actions-remediation-role.trust.json",
        "permissions_file": "github-actions-remediation-role.permissions.json",
        "inline_policy_name": "remediation-permissions",
    },
    # #812: the least-privilege golden-eval role — weekly advisory Haiku voice
    # judge + CloudWatch LifePlatform/GoldenBrief emit + monthly EVALRET# harvest
    # read. Trust is main-only from day one (no repo-wide subject to tighten later).
    "github-actions-golden-eval-role": {
        "trust_file": "github-actions-golden-eval-role.trust.json",
        "permissions_file": "github-actions-golden-eval-role.permissions.json",
        "inline_policy_name": "golden-eval-permissions",
    },
    # #687: the read-only diagnosis role split from the deploy role — CI jobs that
    # only observe (Bedrock vision QA today) assume this instead of deploy-mutate.
    # Main-only trust from day one. Grows only as diagnosis jobs migrate to it.
    "github-actions-diagnosis-role": {
        "trust_file": "github-actions-diagnosis-role.trust.json",
        "permissions_file": "github-actions-diagnosis-role.permissions.json",
        "inline_policy_name": "diagnosis-permissions",
    },
}

PROVIDER_FILE = "github-oidc-provider.json"


def _boundary_spec():
    """(policy_arn, committed_document, role_names) for the #3340 cfn-exec boundary.

    Imported from the derivation rather than restated — ONE source (#3336). An import
    failure is returned as an error string and becomes a finding; it is never a skip.
    """
    try:
        import derive_cfn_exec_boundary as boundary
    except Exception as exc:  # noqa: BLE001 — any import failure must be visible, not silent
        return None, f"deploy/derive_cfn_exec_boundary.py is not importable ({type(exc).__name__}: {exc})"
    try:
        committed = boundary.committed()
    except Exception as exc:  # noqa: BLE001
        return None, f"{os.path.relpath(boundary.POLICY_PATH, _ROOT)} is unreadable ({type(exc).__name__}: {exc})"
    return (boundary.POLICY_ARN, committed, tuple(boundary.CFN_EXEC_ROLE_NAMES)), None


def verify_cfn_exec_boundary(iam, findings):
    """#3340: each cfn-exec role carries the committed boundary, and the live document matches.

    Returns the number of targets compared. Appends one finding per role that is missing
    the boundary, carries a different one, or cannot be read.
    """
    spec, err = _boundary_spec()
    if spec is None:
        findings.append(
            {
                "target": "cdk-cfn-exec-boundary",
                "status": "BOUNDARY-UNREADABLE",
                "checked_in": "infra/iam/cdk-cfn-exec-boundary.permissions.json",
                "live": err,
            }
        )
        return 1

    policy_arn, committed_doc, role_names = spec
    live_doc = None
    checks = 0

    for role_name in role_names:
        checks += 1
        try:
            role = iam.get_role(RoleName=role_name)["Role"]
        except Exception as exc:  # noqa: BLE001 — NoSuchEntity, AccessDenied, throttle: all findings
            findings.append(
                {
                    "target": f"{role_name}:permissions-boundary",
                    "status": "BOUNDARY-UNREADABLE",
                    "checked_in": policy_arn,
                    "live": f"iam:GetRole failed ({type(exc).__name__}: {exc})",
                }
            )
            continue

        attached = (role.get("PermissionsBoundary") or {}).get("PermissionsBoundaryArn")
        if not attached:
            findings.append(
                {
                    "target": f"{role_name}:permissions-boundary",
                    "status": "BOUNDARY-MISSING",
                    "checked_in": policy_arn,
                    "live": "no permissions boundary — the pending #3340 apply (infra/iam/README.md), or a removal",
                }
            )
            continue
        if attached != policy_arn:
            findings.append(
                {
                    "target": f"{role_name}:permissions-boundary",
                    "status": "BOUNDARY-DRIFT",
                    "checked_in": policy_arn,
                    "live": attached,
                }
            )
            continue

        # The document itself, read once and reused: the same managed policy is attached
        # to all three roles, so one GetPolicyVersion answers for all of them.
        if live_doc is None:
            try:
                version_id = iam.get_policy(PolicyArn=policy_arn)["Policy"]["DefaultVersionId"]
                live_doc = iam.get_policy_version(PolicyArn=policy_arn, VersionId=version_id)["PolicyVersion"]["Document"]
            except Exception as exc:  # noqa: BLE001
                findings.append(
                    {
                        "target": f"{policy_arn}:document",
                        "status": "BOUNDARY-UNREADABLE",
                        "checked_in": "cdk-cfn-exec-boundary.permissions.json",
                        "live": f"iam:GetPolicy/GetPolicyVersion failed ({type(exc).__name__}: {exc})",
                    }
                )
                return checks
        checks += 1
        _diff(f"{role_name}:permissions-boundary-document", committed_doc, live_doc, findings)

    return checks


def canon(obj):
    """Order-insensitive canonicalisation for semantic policy comparison.

    - dict: keys sorted, values recursed.
    - list of strings (Action / Resource / sub / thumbprints): sorted.
    - list of dicts (Statement[]): order-normalised by canonical JSON repr.
    """
    if isinstance(obj, dict):
        return {k: canon(obj[k]) for k in sorted(obj)}
    if isinstance(obj, list):
        items = [canon(x) for x in obj]
        if all(isinstance(x, str) for x in items):
            return sorted(items)
        return sorted(items, key=lambda x: json.dumps(x, sort_keys=True))
    return obj


def _load_json(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _diff(label, checked_in, live, findings):
    """Compare two structures semantically; append a finding on mismatch."""
    if canon(checked_in) == canon(live):
        return True
    findings.append(
        {
            "target": label,
            "status": "DRIFT",
            "checked_in": checked_in,
            "live": live,
        }
    )
    return False


def verify(iam):
    findings: list[dict] = []
    checks = 0

    # 1. OIDC provider (Url / ClientIDList / ThumbprintList).
    checks += 1
    provider_ci = _load_json(os.path.join(_IAM_DIR, PROVIDER_FILE))
    live_prov = iam.get_open_id_connect_provider(OpenIDConnectProviderArn=OIDC_PROVIDER_ARN)
    live_prov_norm = {
        "Url": live_prov.get("Url"),
        "ClientIDList": live_prov.get("ClientIDList", []),
        "ThumbprintList": live_prov.get("ThumbprintList", []),
    }
    provider_ci_norm = {
        "Url": provider_ci.get("Url"),
        "ClientIDList": provider_ci.get("ClientIDList", []),
        "ThumbprintList": provider_ci.get("ThumbprintList", []),
    }
    _diff("oidc-provider:token.actions.githubusercontent.com", provider_ci_norm, live_prov_norm, findings)

    # 2. Each role: trust policy + inline permissions policy.
    for role_name, spec in ROLES.items():
        try:
            role = iam.get_role(RoleName=role_name)["Role"]
        except iam.exceptions.NoSuchEntityException:
            # A checked-in identity that doesn't exist live: either it was deleted
            # out-of-band (investigate!) or it is staged and not yet applied (the
            # #812 golden-eval role ships as JSON first — see infra/iam/README.md).
            checks += 1
            findings.append(
                {
                    "target": f"{role_name}",
                    "status": "MISSING",
                    "checked_in": f"{spec['trust_file']} + {spec['permissions_file']}",
                    "live": "role does not exist — staged-not-applied, or deleted out-of-band",
                }
            )
            continue

        checks += 1
        trust_ci = _load_json(os.path.join(_IAM_DIR, spec["trust_file"]))
        _diff(f"{role_name}:trust-policy", trust_ci, role["AssumeRolePolicyDocument"], findings)

        checks += 1
        perms_ci = _load_json(os.path.join(_IAM_DIR, spec["permissions_file"]))
        live_perms = iam.get_role_policy(RoleName=role_name, PolicyName=spec["inline_policy_name"])["PolicyDocument"]
        _diff(f"{role_name}:{spec['inline_policy_name']}", perms_ci, live_perms, findings)

    # 3. The CDK cfn-exec roles' permissions boundary (#3340).
    checks += verify_cfn_exec_boundary(iam, findings)

    return checks, findings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--strict", action="store_true", help="exit 1 if any drift is found")
    parser.add_argument("--json", action="store_true", help="emit machine-readable findings")
    args = parser.parse_args()

    try:
        import boto3
    except ImportError:
        print("error: boto3 is required (pip install boto3)", file=sys.stderr)
        return 2

    iam = boto3.client("iam")
    checks, findings = verify(iam)

    if args.json:
        print(json.dumps({"checks": checks, "drift": findings}, indent=2))
    else:
        print(f"OIDC/IAM codification drift check — {checks} target(s) compared against live.\n")
        if not findings:
            print("CLEAN — every checked-in identity matches live exactly.")
        else:
            print(f"DRIFT — {len(findings)} target(s) differ from the checked-in source of truth:\n")
            for f in findings:
                print(f"  [{f['status']}] {f['target']}")
                print(f"    checked-in: {json.dumps(canon(f['checked_in']))}")
                print(f"    live:       {json.dumps(canon(f['live']))}")
            print(
                "\nIf this drift is an intended change, update the JSON under infra/iam/ in a PR "
                "(git revert = rollback). If it is out-of-band, investigate: these identities gate all deploys."
            )

    if args.strict and findings:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
