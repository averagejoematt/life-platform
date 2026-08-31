#!/usr/bin/env bash
# setup_remediation_role.sh — create/update the OIDC role for the self-healing
# remediation agent (.github/workflows/remediation-agent.yml). Idempotent.
#
# ONE SOURCE (#3336). This script carries NO policy text. It applies the two
# checked-in documents under infra/iam/ VERBATIM, via file:// — nothing else can
# reach the live role from this repo:
#   infra/iam/github-actions-remediation-role.trust.json        → the role's trust policy
#   infra/iam/github-actions-remediation-role.permissions.json  → inline policy `remediation-permissions`
# To change a grant: edit the JSON in a PR (git revert = rollback), merge, re-run
# this. tests/test_iam_twin_free_3336.py fails the suite if an inline IAM policy
# document for any infra/iam-governed role ever reappears under deploy/.
#
# WHY (incident 2026-08-30, docs/INCIDENT_LOG.md). The previous version of this
# file was a hand-maintained TWIN of those two documents. Its header said "the
# JSON wins", nothing enforced it, and the twin was the copy that ran: it carried
# 15 of the JSON's 17 statements and the pre-#687 repo-wide trust subject, so one
# run regressed four grants and let ANY ref of this public repo assume the role
# for ≈6 minutes, until deploy/verify_oidc_iam.py --strict caught it.
#
# HIGH-SEVERITY IAM change (OIDC trust + Bedrock/KMS/SES) → operator-run, never
# agent-run. Reuses the GitHub OIDC provider created by setup_github_oidc.sh:
#   bash deploy/setup_remediation_role.sh
# Ends with the read-only verifier so the apply proves itself against live
# before the prompt returns.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
IAM_DIR="${REPO_ROOT}/infra/iam"

ACCOUNT="205930651321"
ROLE="github-actions-remediation-role"
# Must equal deploy/verify_oidc_iam.py ROLES[ROLE]["inline_policy_name"] — the
# verifier reads the live policy under this name.
POLICY_NAME="remediation-permissions"
TRUST_FILE="${IAM_DIR}/github-actions-remediation-role.trust.json"
PERMS_FILE="${IAM_DIR}/github-actions-remediation-role.permissions.json"

for f in "$TRUST_FILE" "$PERMS_FILE"; do
  if [[ ! -r "$f" ]]; then
    echo "❌ missing source document: $f" >&2
    exit 2
  fi
  if ! python3 -m json.tool "$f" >/dev/null; then
    echo "❌ not valid JSON, refusing to apply: $f" >&2
    exit 2
  fi
done

if aws iam get-role --role-name "$ROLE" >/dev/null 2>&1; then
  echo "Updating trust policy on ${ROLE} from ${TRUST_FILE#"${REPO_ROOT}"/}..."
  aws iam update-assume-role-policy --role-name "$ROLE" --policy-document "file://${TRUST_FILE}"
else
  echo "Creating ${ROLE} from ${TRUST_FILE#"${REPO_ROOT}"/}..."
  aws iam create-role --role-name "$ROLE" --assume-role-policy-document "file://${TRUST_FILE}" \
    --description "Self-healing remediation agent (GH Actions OIDC; Bedrock + read-only diagnosis)" >/dev/null
fi

echo "Applying ${PERMS_FILE#"${REPO_ROOT}"/} as inline policy ${POLICY_NAME}..."
aws iam put-role-policy --role-name "$ROLE" --policy-name "$POLICY_NAME" --policy-document "file://${PERMS_FILE}"

echo "✅ ${ROLE} applied from infra/iam/: arn:aws:iam::${ACCOUNT}:role/${ROLE}"
echo "   The workflow (.github/workflows/remediation-agent.yml) assumes this role via OIDC."
echo ""
echo "Post-apply proof (read-only — iam:GetRole / GetRolePolicy / GetOpenIDConnectProvider):"
if ! python3 "${REPO_ROOT}/deploy/verify_oidc_iam.py" --strict; then
  echo "❌ verify_oidc_iam.py --strict reports DRIFT. If the drifted target is ${ROLE}, this apply" >&2
  echo "   did not land — investigate before leaving. A DRIFT on a DIFFERENT role is a separate" >&2
  echo "   staged apply (infra/iam/README.md), not a failure of this script." >&2
  exit 1
fi
