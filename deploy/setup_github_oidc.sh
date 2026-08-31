#!/usr/bin/env bash
# deploy/setup_github_oidc.sh — OIDC bootstrap for GitHub Actions CI/CD
#
# Creates / updates:
#   1. the GitHub OIDC identity provider in AWS IAM
#   2. github-actions-deploy-role — trust policy + inline permissions policy
#
# Run ONCE per AWS account; idempotent — safe to re-run. The role ARN is hardcoded
# in ci-cd.yml as arn:aws:iam::205930651321:role/github-actions-deploy-role.
#
# ONE SOURCE (#3336). This script carries NO policy text and NO provider
# constants. It applies the checked-in documents under infra/iam/ VERBATIM:
#   infra/iam/github-oidc-provider.json                    → provider Url / ClientIDList / ThumbprintList
#   infra/iam/github-actions-deploy-role.trust.json        → the role's trust policy
#   infra/iam/github-actions-deploy-role.permissions.json  → inline policy `life-platform-cicd-permissions`
# To change a grant: edit the JSON in a PR (git revert = rollback), merge, re-run
# this. tests/test_iam_twin_free_3336.py fails the suite if an inline IAM policy
# document for any infra/iam-governed role reappears under deploy/.
#
# WHY. Until #3336 this file was a hand-maintained twin of those documents whose
# own header admitted its trust block was "still the pre-#687 repo-wide subject
# ... do not re-run this bootstrap without reconciling trust". The remediation
# role's identical twin WAS re-run on 2026-08-30 and put a stale document live for
# ≈6 minutes (docs/INCIDENT_LOG.md). Deriving both scripts from the JSON is the
# structural answer: there is nothing left in here to reconcile.
#
# What the deploy role can do is the permissions JSON, statement by statement —
# read it, not a summary here. The read-only diagnosis surface (IAM read,
# Bedrock vision-QA, CloudWatch metric reads) was shed from this role in #903 and
# lives on github-actions-diagnosis-role / github-actions-remediation-role.
#
# Prerequisites: AWS CLI with admin credentials, python3.
# Usage:
#   bash deploy/setup_github_oidc.sh
#
# v1.0.0 — 2026-03-15 (R13-F01 CI/CD enablement)
# v2.0.0 — 2026-08-30 (#3336: derived from infra/iam/, no inline documents)

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
IAM_DIR="${REPO_ROOT}/infra/iam"

ACCOUNT="205930651321"
REGION="us-west-2"
ROLE_NAME="github-actions-deploy-role"
GITHUB_ORG="averagejoematt"
GITHUB_REPO="life-platform"
# Must equal deploy/verify_oidc_iam.py ROLES[ROLE_NAME]["inline_policy_name"].
POLICY_NAME="life-platform-cicd-permissions"
PROVIDER_FILE="${IAM_DIR}/github-oidc-provider.json"
TRUST_FILE="${IAM_DIR}/github-actions-deploy-role.trust.json"
PERMS_FILE="${IAM_DIR}/github-actions-deploy-role.permissions.json"

echo "═══════════════════════════════════════════════════════"
echo "  Life Platform — GitHub Actions OIDC Setup (from infra/iam/)"
echo "  Account: $ACCOUNT  Region: $REGION"
echo "═══════════════════════════════════════════════════════"
echo ""

for f in "$PROVIDER_FILE" "$TRUST_FILE" "$PERMS_FILE"; do
  if [[ ! -r "$f" ]]; then
    echo "❌ missing source document: $f" >&2
    exit 2
  fi
  if ! python3 -m json.tool "$f" >/dev/null; then
    echo "❌ not valid JSON, refusing to apply: $f" >&2
    exit 2
  fi
done

# ── Step 1: OIDC provider (idempotent; fields read from the provider JSON) ────
echo "Step 1: GitHub OIDC identity provider"

_provider_field() {
  # _provider_field <key>  → the JSON value; lists are printed space-separated
  python3 - "$PROVIDER_FILE" "$1" <<'PY'
import json, sys
doc = json.load(open(sys.argv[1], encoding="utf-8"))
val = doc[sys.argv[2]]
print(" ".join(val) if isinstance(val, list) else val)
PY
}
OIDC_URL="$(_provider_field Url)"
OIDC_CLIENT_IDS="$(_provider_field ClientIDList)"
OIDC_THUMBPRINTS="$(_provider_field ThumbprintList)"

EXISTING_PROVIDER=$(aws iam list-open-id-connect-providers \
  --query "OpenIDConnectProviderList[?ends_with(Arn, 'oidc-provider/${OIDC_URL}')].Arn" \
  --output text 2>/dev/null || echo "")

if [ -n "$EXISTING_PROVIDER" ]; then
  echo "  ✅ OIDC provider already exists: $EXISTING_PROVIDER"
  OIDC_ARN="$EXISTING_PROVIDER"
else
  echo "  Creating OIDC provider https://${OIDC_URL} from ${PROVIDER_FILE#"${REPO_ROOT}"/}..."
  # shellcheck disable=SC2086  # word-split on purpose: the lists are space-separated
  OIDC_ARN=$(aws iam create-open-id-connect-provider \
    --url "https://${OIDC_URL}" \
    --client-id-list ${OIDC_CLIENT_IDS} \
    --thumbprint-list ${OIDC_THUMBPRINTS} \
    --query "OpenIDConnectProviderArn" \
    --output text)
  echo "  ✅ Created: $OIDC_ARN"
fi

# ── Step 2: the role — trust policy from the checked-in JSON ─────────────────
echo ""
echo "Step 2: IAM role — $ROLE_NAME (trust from ${TRUST_FILE#"${REPO_ROOT}"/})"

EXISTING_ROLE=$(aws iam get-role --role-name "$ROLE_NAME" \
  --query "Role.Arn" --output text 2>/dev/null || echo "")

if [ -n "$EXISTING_ROLE" ]; then
  echo "  Role already exists: $EXISTING_ROLE"
  echo "  Updating trust policy..."
  aws iam update-assume-role-policy \
    --role-name "$ROLE_NAME" \
    --policy-document "file://${TRUST_FILE}"
  echo "  ✅ Trust policy updated"
else
  echo "  Creating role..."
  ROLE_ARN=$(aws iam create-role \
    --role-name "$ROLE_NAME" \
    --assume-role-policy-document "file://${TRUST_FILE}" \
    --description "GitHub Actions OIDC role for life-platform CI/CD (${GITHUB_ORG}/${GITHUB_REPO})" \
    --max-session-duration 3600 \
    --query "Role.Arn" \
    --output text)
  echo "  ✅ Created: $ROLE_ARN"
fi

# ── Step 3: inline permissions policy from the checked-in JSON ───────────────
echo ""
echo "Step 3: Permission policy ${POLICY_NAME} (from ${PERMS_FILE#"${REPO_ROOT}"/})"

aws iam put-role-policy \
  --role-name "$ROLE_NAME" \
  --policy-name "$POLICY_NAME" \
  --policy-document "file://${PERMS_FILE}"
echo "  ✅ Permissions applied"

# ── Step 4: verify — read-only, against live ─────────────────────────────────
echo ""
echo "Step 4: Verification"

FINAL_ARN=$(aws iam get-role --role-name "$ROLE_NAME" \
  --query "Role.Arn" --output text)
echo "  ✅ Role ARN: $FINAL_ARN"

POLICY_NAMES=$(aws iam list-role-policies --role-name "$ROLE_NAME" \
  --query "PolicyNames[]" --output text)
echo "  ✅ Inline policies: $POLICY_NAMES"

echo "  Post-apply proof (deploy/verify_oidc_iam.py --strict, read-only):"
if ! python3 "${REPO_ROOT}/deploy/verify_oidc_iam.py" --strict; then
  echo "❌ verify_oidc_iam.py --strict reports DRIFT. If the drifted target is ${ROLE_NAME} or the" >&2
  echo "   provider, this apply did not land — investigate before leaving. A DRIFT on a DIFFERENT" >&2
  echo "   role is a separate staged apply (infra/iam/README.md), not a failure of this script." >&2
  exit 1
fi

echo ""
echo "═══════════════════════════════════════════════════════"
echo "  ✅ OIDC setup complete"
echo ""
echo "  Role ARN: $FINAL_ARN"
echo ""
echo "  Next steps:"
echo "  1. Verify the role ARN matches ci-cd.yml:"
echo "     role-to-assume: arn:aws:iam::${ACCOUNT}:role/${ROLE_NAME}"
echo "  2. Create the GitHub 'production' Environment in repo settings"
echo "     (required for the manual approval gate on deploy jobs):"
echo "     https://github.com/${GITHUB_ORG}/${GITHUB_REPO}/settings/environments"
echo "  3. Push a change to main to trigger the first pipeline run"
echo "  4. Monitor the Actions tab:"
echo "     https://github.com/${GITHUB_ORG}/${GITHUB_REPO}/actions"
echo "═══════════════════════════════════════════════════════"
