#!/usr/bin/env bash
# Fix 3 only: Add 13 new roles to KMS key policy
# Run from: ~/Documents/Claude/life-platform/
# Usage:    bash deploy/fix_kms_policy.sh

set -euo pipefail

REGION="us-west-2"
ACCOUNT="205930651321"
KMS_KEY_ID="444438d1-a5e0-43b8-9391-3cd2d70dde4d"

echo "=== Fix 3: KMS key policy update ==="
echo ""

python3 << PYEOF
import subprocess, json, sys

REGION = "us-west-2"
ACCOUNT = "205930651321"
KMS_KEY_ID = "444438d1-a5e0-43b8-9391-3cd2d70dde4d"

NEW_ROLE_ARNS = [
    f"arn:aws:iam::{ACCOUNT}:role/lambda-daily-brief-role",
    f"arn:aws:iam::{ACCOUNT}:role/lambda-weekly-digest-role-v2",
    f"arn:aws:iam::{ACCOUNT}:role/lambda-monthly-digest-role",
    f"arn:aws:iam::{ACCOUNT}:role/lambda-nutrition-review-role",
    f"arn:aws:iam::{ACCOUNT}:role/lambda-wednesday-chronicle-role",
    f"arn:aws:iam::{ACCOUNT}:role/lambda-weekly-plate-role",
    f"arn:aws:iam::{ACCOUNT}:role/lambda-monday-compass-role",
    f"arn:aws:iam::{ACCOUNT}:role/lambda-adaptive-mode-role",
    f"arn:aws:iam::{ACCOUNT}:role/lambda-daily-metrics-role",
    f"arn:aws:iam::{ACCOUNT}:role/lambda-daily-insight-role",
    f"arn:aws:iam::{ACCOUNT}:role/lambda-hypothesis-engine-role",
    f"arn:aws:iam::{ACCOUNT}:role/lambda-qa-smoke-role",
    f"arn:aws:iam::{ACCOUNT}:role/lambda-data-export-role",
]

# Use --output json so we get clean parseable output
r = subprocess.run(
    ["aws", "kms", "get-key-policy",
     "--key-id", KMS_KEY_ID,
     "--policy-name", "default",
     "--region", REGION,
     "--output", "json",
     "--no-cli-pager"],
    capture_output=True, text=True
)
if r.returncode != 0:
    print(f"  ✗ Could not read KMS policy: {r.stderr}")
    sys.exit(1)

# --output json wraps it as {"Policy": "<escaped-json-string>"}
outer = json.loads(r.stdout)
policy = json.loads(outer["Policy"])

# Show current state
print("Current KMS policy statements:")
for stmt in policy.get("Statement", []):
    sid = stmt.get("Sid", "unnamed")
    actions = stmt.get("Action", [])
    if isinstance(actions, str): actions = [actions]
    principal = stmt.get("Principal", {})
    aws_p = principal.get("AWS", []) if isinstance(principal, dict) else []
    if isinstance(aws_p, str): aws_p = [aws_p]
    print(f"  [{sid}] actions={actions[:2]} principals={len(aws_p)}")

# Find the Lambda decrypt statement and inject new ARNs
added = 0
found = False
for stmt in policy.get("Statement", []):
    actions = stmt.get("Action", [])
    if isinstance(actions, str): actions = [actions]
    if not any(a in ("kms:Decrypt", "kms:GenerateDataKey") for a in actions):
        continue
    found = True
    principal = stmt.get("Principal", {})
    aws_p = principal.get("AWS", [])
    if isinstance(aws_p, str):
        aws_p = [aws_p]
    for arn in NEW_ROLE_ARNS:
        if arn not in aws_p:
            aws_p.append(arn)
            added += 1
    stmt["Principal"]["AWS"] = aws_p
    print(f"\n  Found decrypt statement — adding {added} new ARNs")
    break

if not found:
    print("\n  No existing decrypt statement — creating new one")
    policy["Statement"].append({
        "Sid": "LambdaFunctionDecrypt",
        "Effect": "Allow",
        "Principal": {"AWS": NEW_ROLE_ARNS},
        "Action": ["kms:Decrypt", "kms:GenerateDataKey"],
        "Resource": "*"
    })
    added = len(NEW_ROLE_ARNS)

# Put updated policy
new_policy_str = json.dumps(policy)
r2 = subprocess.run(
    ["aws", "kms", "put-key-policy",
     "--key-id", KMS_KEY_ID,
     "--policy-name", "default",
     "--policy", new_policy_str,
     "--region", REGION,
     "--no-cli-pager"],
    capture_output=True, text=True
)
if r2.returncode != 0:
    print(f"  ✗ KMS update failed: {r2.stderr}")
    sys.exit(1)
print("  ✓ KMS key policy updated")

# Verify
r3 = subprocess.run(
    ["aws", "kms", "get-key-policy",
     "--key-id", KMS_KEY_ID,
     "--policy-name", "default",
     "--region", REGION,
     "--output", "json",
     "--no-cli-pager"],
    capture_output=True, text=True
)
outer2 = json.loads(r3.stdout)
policy2 = json.loads(outer2["Policy"])
for stmt in policy2.get("Statement", []):
    actions = stmt.get("Action", [])
    if isinstance(actions, str): actions = [actions]
    if not any(a in ("kms:Decrypt", "kms:GenerateDataKey") for a in actions):
        continue
    principals = stmt.get("Principal", {}).get("AWS", [])
    if isinstance(principals, str): principals = [principals]
    new_found = sum(1 for p in principals if any(
        r in p for r in [
            "daily-brief-role", "weekly-digest-role-v2", "monthly-digest-role",
            "nutrition-review-role", "wednesday-chronicle-role", "weekly-plate-role",
            "monday-compass-role", "adaptive-mode-role", "daily-metrics-role",
            "daily-insight-role", "hypothesis-engine-role", "qa-smoke-role", "data-export-role"
        ]
    ))
    print(f"  Verification: {len(principals)} total principals in decrypt stmt, {new_found}/13 new roles confirmed")
PYEOF

echo ""
echo "=== Done ==="
echo ""
echo "git add -A && git commit -m 'v3.1.2: KMS policy updated with 13 new Lambda roles' && git push"
