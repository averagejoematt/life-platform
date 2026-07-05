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
  iam:GetRole, iam:GetRolePolicy, iam:GetOpenIDConnectProvider
It never mutates anything. Applying a trust change is a separate, deliberate,
watched step — see infra/iam/README.md.

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
}

PROVIDER_FILE = "github-oidc-provider.json"


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
        role = iam.get_role(RoleName=role_name)["Role"]

        checks += 1
        trust_ci = _load_json(os.path.join(_IAM_DIR, spec["trust_file"]))
        _diff(f"{role_name}:trust-policy", trust_ci, role["AssumeRolePolicyDocument"], findings)

        checks += 1
        perms_ci = _load_json(os.path.join(_IAM_DIR, spec["permissions_file"]))
        live_perms = iam.get_role_policy(RoleName=role_name, PolicyName=spec["inline_policy_name"])["PolicyDocument"]
        _diff(f"{role_name}:{spec['inline_policy_name']}", perms_ci, live_perms, findings)

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
