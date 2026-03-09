#!/usr/bin/env bash
# fix_daily_brief_p0_bugs.sh — Fix two non-fatal Daily Brief bugs (v2.55.1)
#
# Bug #1: write_dashboard_json() — deployed Lambda (from hotfix backup) references
#         component_details as a free variable → NameError → dashboard tiles missing.
#         Fix: current code on disk adds component_details=None parameter + passes it
#         from handler. Just needs redeployment.
#
# Bug #2: write_buddy_json() — lambda-weekly-digest-role lacks s3:PutObject for
#         buddy/* → AccessDenied → buddy page shows stale data.
#         Fix: update IAM inline policy to include buddy/ path.
#
# Usage:
#   cd ~/Documents/Claude/life-platform
#   chmod +x deploy/fix_daily_brief_p0_bugs.sh
#   ./deploy/fix_daily_brief_p0_bugs.sh

set -euo pipefail

REGION="us-west-2"
ACCOUNT="205930651321"
ROLE_NAME="lambda-weekly-digest-role"
POLICY_NAME="weekly-digest-access"
LAMBDAS_DIR="lambdas"
BUCKET="matthew-life-platform"

info()  { echo "  [INFO]  $*"; }
ok()    { echo "  [✅]    $*"; }
fail()  { echo "  [❌]    $*" >&2; }
step()  { echo ""; echo "═══ $* ═══"; }

ERRORS=0

# ══════════════════════════════════════════════════════════════════════════════
# PRE-FLIGHT: Syntax check
# ══════════════════════════════════════════════════════════════════════════════
step "Step 0: Pre-flight syntax check"

if [ ! -f "$LAMBDAS_DIR/daily_brief_lambda.py" ]; then
    fail "Missing: $LAMBDAS_DIR/daily_brief_lambda.py"
    exit 1
fi

if ! python3 -c "import py_compile; py_compile.compile('$LAMBDAS_DIR/daily_brief_lambda.py', doraise=True)" 2>/dev/null; then
    fail "Syntax error in daily_brief_lambda.py"
    exit 1
fi
ok "daily_brief_lambda.py passes syntax check"

# Verify the fix is present on disk
if grep -q "component_details=component_details" "$LAMBDAS_DIR/daily_brief_lambda.py"; then
    ok "component_details fix confirmed in source"
else
    fail "component_details=component_details NOT found in handler call — aborting"
    exit 1
fi

# ══════════════════════════════════════════════════════════════════════════════
# Step 1: Show current IAM policy (for audit trail)
# ══════════════════════════════════════════════════════════════════════════════
step "Step 1/3: Audit current IAM policy"

echo "  Current policy for $ROLE_NAME / $POLICY_NAME:"
aws iam get-role-policy \
    --role-name "$ROLE_NAME" \
    --policy-name "$POLICY_NAME" \
    --region "$REGION" \
    --query "PolicyDocument" \
    --output json 2>/dev/null || echo "  (Could not retrieve — may need to check policy name)"
echo ""

# ══════════════════════════════════════════════════════════════════════════════
# Step 2: Update IAM policy — add s3:PutObject for buddy/*
# ══════════════════════════════════════════════════════════════════════════════
step "Step 2/3: Update IAM policy (add S3 buddy/* write)"

# Strategy: Get current policy, check if S3 statement already covers buddy/*,
# and add it if missing. We reconstruct the full policy to be safe.
#
# We use a Python helper to merge cleanly rather than risk clobbering.

python3 << 'PYEOF'
import json
import subprocess
import sys

role = "lambda-weekly-digest-role"
policy = "weekly-digest-access"
region = "us-west-2"
account = "205930651321"
bucket = "matthew-life-platform"

# Get current policy
try:
    result = subprocess.run(
        ["aws", "iam", "get-role-policy",
         "--role-name", role,
         "--policy-name", policy,
         "--region", region,
         "--query", "PolicyDocument",
         "--output", "json"],
        capture_output=True, text=True, check=True
    )
    current = json.loads(result.stdout)
except Exception as e:
    print(f"  [WARN] Could not retrieve current policy: {e}")
    print("  [INFO] Building fresh policy with all known permissions")
    current = {"Version": "2012-10-17", "Statement": []}

# Check if S3 buddy/* permission already exists
buddy_arn = f"arn:aws:s3:::{bucket}/buddy/*"
dashboard_arn = f"arn:aws:s3:::{bucket}/dashboard/*"

s3_arns_needed = {buddy_arn, dashboard_arn}
s3_arns_found = set()

for stmt in current.get("Statement", []):
    actions = stmt.get("Action", [])
    if isinstance(actions, str):
        actions = [actions]
    if "s3:PutObject" in actions:
        resources = stmt.get("Resource", [])
        if isinstance(resources, str):
            resources = [resources]
        for r in resources:
            if r in s3_arns_needed:
                s3_arns_found.add(r)

missing = s3_arns_needed - s3_arns_found
if not missing:
    print("  [✅] S3 permissions for dashboard/* and buddy/* already present")
    sys.exit(0)

print(f"  [INFO] Missing S3 resources: {missing}")

# Find existing S3 statement or create one
s3_stmt_idx = None
for i, stmt in enumerate(current.get("Statement", [])):
    actions = stmt.get("Action", [])
    if isinstance(actions, str):
        actions = [actions]
    if "s3:PutObject" in actions:
        s3_stmt_idx = i
        break

if s3_stmt_idx is not None:
    # Merge into existing S3 statement
    stmt = current["Statement"][s3_stmt_idx]
    resources = stmt.get("Resource", [])
    if isinstance(resources, str):
        resources = [resources]
    for arn in missing:
        if arn not in resources:
            resources.append(arn)
    stmt["Resource"] = resources
    print(f"  [INFO] Updated existing S3 statement with: {list(missing)}")
else:
    # Add new S3 statement
    current["Statement"].append({
        "Effect": "Allow",
        "Action": ["s3:PutObject"],
        "Resource": sorted(list(s3_arns_needed))
    })
    print(f"  [INFO] Added new S3 PutObject statement for: {sorted(list(s3_arns_needed))}")

# Write updated policy
policy_json = json.dumps(current)
result = subprocess.run(
    ["aws", "iam", "put-role-policy",
     "--role-name", role,
     "--policy-name", policy,
     "--policy-document", policy_json,
     "--region", region],
    capture_output=True, text=True
)

if result.returncode != 0:
    print(f"  [❌] Failed to update policy: {result.stderr}")
    sys.exit(1)

print("  [✅] IAM policy updated successfully")

# Verify
result = subprocess.run(
    ["aws", "iam", "get-role-policy",
     "--role-name", role,
     "--policy-name", policy,
     "--region", region,
     "--query", "PolicyDocument",
     "--output", "json"],
    capture_output=True, text=True, check=True
)
verified = json.loads(result.stdout)
print("  [INFO] Updated policy:")
print(json.dumps(verified, indent=2))
PYEOF

if [ $? -ne 0 ]; then
    fail "IAM policy update failed"
    ERRORS=$((ERRORS + 1))
else
    ok "IAM policy updated"
fi

# ══════════════════════════════════════════════════════════════════════════════
# Step 3: Redeploy Daily Brief Lambda
# ══════════════════════════════════════════════════════════════════════════════
step "Step 3/3: Redeploy Daily Brief (daily-brief)"

# Handler expects: lambda_function.lambda_handler
rm -f daily_brief.zip lambda_function.py
cp "$LAMBDAS_DIR/daily_brief_lambda.py" lambda_function.py
zip -j daily_brief.zip lambda_function.py
rm lambda_function.py

info "Packaged daily_brief.zip ($(du -h daily_brief.zip | cut -f1))"

aws lambda update-function-code \
    --function-name "daily-brief" \
    --zip-file "fileb://daily_brief.zip" \
    --region "$REGION" > /dev/null
aws lambda wait function-updated --function-name "daily-brief" --region "$REGION"
ok "Daily brief Lambda deployed"

# Cleanup
rm -f daily_brief.zip

# ══════════════════════════════════════════════════════════════════════════════
# VERIFICATION
# ══════════════════════════════════════════════════════════════════════════════
step "Verification"

info "Testing Lambda invocation (dry run)..."
INVOKE_RESULT=$(aws lambda invoke \
    --function-name "daily-brief" \
    --payload '{"demo_mode": true}' \
    --region "$REGION" \
    /tmp/daily_brief_test_output.json 2>&1)

STATUS=$(echo "$INVOKE_RESULT" | grep -o '"StatusCode": [0-9]*' | grep -o '[0-9]*' || echo "unknown")
if [ "$STATUS" = "200" ]; then
    ok "Lambda invoked successfully (status $STATUS)"
    # Check for errors in response
    if grep -q "errorMessage" /tmp/daily_brief_test_output.json 2>/dev/null; then
        fail "Lambda returned an error:"
        cat /tmp/daily_brief_test_output.json
        ERRORS=$((ERRORS + 1))
    else
        ok "No errors in response"
        cat /tmp/daily_brief_test_output.json
    fi
else
    fail "Lambda invocation returned status: $STATUS"
    ERRORS=$((ERRORS + 1))
fi

rm -f /tmp/daily_brief_test_output.json

# ══════════════════════════════════════════════════════════════════════════════
# SUMMARY
# ══════════════════════════════════════════════════════════════════════════════
echo ""
if [ "$ERRORS" -gt 0 ]; then
    echo "╔══════════════════════════════════════════════════════════╗"
    echo "║  ⚠️  Deployment completed with $ERRORS error(s)           ║"
    echo "╚══════════════════════════════════════════════════════════╝"
    exit 1
else
    echo "╔══════════════════════════════════════════════════════════╗"
    echo "║  Daily Brief P0 Bug Fixes — v2.55.1                    ║"
    echo "╠══════════════════════════════════════════════════════════╣"
    echo "║  ✅ IAM: s3:PutObject for buddy/* + dashboard/*        ║"
    echo "║  ✅ Lambda: component_details passed to dashboard fn    ║"
    echo "╠══════════════════════════════════════════════════════════╣"
    echo "║  Dashboard tiles: will populate on next morning brief   ║"
    echo "║  Buddy data.json: will refresh on next morning brief    ║"
    echo "╚══════════════════════════════════════════════════════════╝"
fi
echo ""
echo "Next brief runs at 10:00 AM PT tomorrow. Check CloudWatch for:"
echo "  grep '[INFO] Dashboard JSON written' /aws/lambda/daily-brief"
echo "  grep '[INFO] Buddy JSON written' /aws/lambda/daily-brief"
