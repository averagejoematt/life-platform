#!/usr/bin/env bash
# Deploy all security hardening changes in order:
#   SEC-1: per-function IAM roles
#   SEC-2: split secrets
#   MCP deploy (SEC-3: input validation in handler.py is already on disk)
#   REL-1: compute failure alarms
#   IAM-1: audit (read-only, no changes)
#
# Run from: ~/Documents/Claude/life-platform/
# Usage:    bash deploy/deploy_security_hardening.sh
#
# Each step can be run independently if needed.

set -euo pipefail
REGION="us-west-2"

echo "=== Security Hardening Deploy — v3.1.0 ==="
echo ""
echo "Steps:"
echo "  1. SEC-1: Create per-function IAM roles"
echo "  2. SEC-2: Split consolidated secrets"
echo "  3. SEC-3: Deploy MCP Lambda with input validation"
echo "  4. REL-1: CloudWatch compute failure alarms"
echo "  5. IAM-1: Role audit (read-only)"
echo ""

read -p "Proceed? (y/N): " CONFIRM
if [[ "${CONFIRM}" != "y" && "${CONFIRM}" != "Y" ]]; then
  echo "Aborted."
  exit 0
fi

# ── STEP 1: SEC-1 ────────────────────────────────────────────────────────────
echo ""
echo "═══ Step 1/5: SEC-1 — IAM role decomposition ═══"
bash deploy/setup_sec1_iam_roles.sh

echo ""
echo "Waiting 15 seconds for IAM propagation..."
sleep 15

# ── STEP 2: SEC-2 ────────────────────────────────────────────────────────────
echo ""
echo "═══ Step 2/5: SEC-2 — Secret split ═══"
bash deploy/setup_sec2_secrets.sh

echo ""
echo "Waiting 10 seconds..."
sleep 10

# ── STEP 3: SEC-3 — Deploy MCP Lambda ────────────────────────────────────────
echo ""
echo "═══ Step 3/5: SEC-3 — Deploy MCP Lambda with input validation ═══"
bash deploy/deploy_mcp.sh

echo ""
echo "Waiting 10 seconds for Lambda update to complete..."
sleep 10

# ── STEP 4: REL-1 ────────────────────────────────────────────────────────────
echo ""
echo "═══ Step 4/5: REL-1 — Compute failure alarms ═══"
bash deploy/rel1_compute_alarm.sh

# ── STEP 5: IAM-1 audit ───────────────────────────────────────────────────────
echo ""
echo "═══ Step 5/5: IAM-1 — Role audit ═══"
bash deploy/iam1_audit_roles.sh

echo ""
echo "=== Security hardening complete ==="
echo ""
echo "Verify MCP input validation:"
echo "  aws lambda invoke --function-name life-platform-mcp \\"
echo "    --payload '{\"jsonrpc\":\"2.0\",\"method\":\"tools/call\",\"params\":{\"name\":\"get_sleep_data\",\"arguments\":{\"date\":12345}},\"id\":1}' \\"
echo "    /tmp/mcp_validation_test.json --region ${REGION} && cat /tmp/mcp_validation_test.json"
echo "  (Should return error about wrong type for 'date')"
echo ""
echo "Then commit:"
echo "  git add -A && git commit -m 'v3.1.0: Security hardening — SEC-1/2/3, IAM-1, REL-1' && git push"
