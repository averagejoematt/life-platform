#!/usr/bin/env bash
# Fix 2 + 3 from IAM-1 audit (re-run of the failed parts)
# Fix 2: Update api-keys-read policies to domain-specific secret ARNs
# Fix 3: Add 13 new roles to KMS key policy
#
# Run from: ~/Documents/Claude/life-platform/
# Usage:    bash deploy/fix_iam1_part2.sh

set -euo pipefail

REGION="us-west-2"
ACCOUNT="205930651321"
KMS_KEY_ID="444438d1-a5e0-43b8-9391-3cd2d70dde4d"

echo "=== IAM-1 Fix Part 2: Secret ARNs + KMS policy ==="
echo ""

# ─────────────────────────────────────────────────────────────────────────────
# FIX 2: Update api-keys-read inline policy on each ingestion role
# Uses python3 for the loop instead of bash associative arrays (bash 3 compat)
# ─────────────────────────────────────────────────────────────────────────────
echo "Fix 2: Scoping api-keys-read policies to domain-specific secret ARNs..."

python3 << 'PYEOF'
import subprocess, json, sys

REGION = "us-west-2"
ACCOUNT = "205930651321"

# role -> list of secret ARN patterns it legitimately needs
ROLE_SECRETS = {
    "lambda-notion-ingestion-role":    [f"arn:aws:secretsmanager:{REGION}:{ACCOUNT}:secret:life-platform/notion-*"],
    "lambda-dropbox-poll-role":        [f"arn:aws:secretsmanager:{REGION}:{ACCOUNT}:secret:life-platform/dropbox-*"],
    "lambda-todoist-role":             [f"arn:aws:secretsmanager:{REGION}:{ACCOUNT}:secret:life-platform/todoist-*"],
    "lambda-habitify-ingestion-role":  [f"arn:aws:secretsmanager:{REGION}:{ACCOUNT}:secret:life-platform/ingestion-keys-*"],
    "lambda-health-auto-export-role":  [f"arn:aws:secretsmanager:{REGION}:{ACCOUNT}:secret:life-platform/ingestion-keys-*"],
    "lambda-mcp-server-role":          [f"arn:aws:secretsmanager:{REGION}:{ACCOUNT}:secret:life-platform/mcp-api-key-*"],
    "lambda-monday-compass-role":      [
        f"arn:aws:secretsmanager:{REGION}:{ACCOUNT}:secret:life-platform/ai-keys-*",
        f"arn:aws:secretsmanager:{REGION}:{ACCOUNT}:secret:life-platform/todoist-*",
    ],
    "lambda-canary-role":              [f"arn:aws:secretsmanager:{REGION}:{ACCOUNT}:secret:life-platform/ai-keys-*"],
}

def run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    return r.stdout.strip(), r.returncode

for role, secret_arns in ROLE_SECRETS.items():
    # Get the api-keys-read policy if it exists
    out, rc = run(["aws", "iam", "get-role-policy",
                   "--role-name", role,
                   "--policy-name", "api-keys-read",
                   "--query", "PolicyDocument",
                   "--output", "json",
                   "--region", REGION,
                   "--no-cli-pager"])
    if rc != 0:
        print(f"  — {role}: no api-keys-read policy (skipping)")
        continue

    try:
        doc = json.loads(out)
    except json.JSONDecodeError:
        print(f"  ✗ {role}: could not parse policy JSON")
        continue

    # Update the secretsmanager resource to the scoped ARNs
    changed = False
    for stmt in doc.get("Statement", []):
        actions = stmt.get("Action", [])
        if isinstance(actions, str):
            actions = [actions]
        if any("secretsmanager" in a for a in actions):
            new_resource = secret_arns[0] if len(secret_arns) == 1 else secret_arns
            stmt["Resource"] = new_resource
            changed = True

    if not changed:
        print(f"  — {role}: no secretsmanager action found in policy")
        continue

    new_policy = json.dumps(doc)
    _, rc = run(["aws", "iam", "put-role-policy",
                 "--role-name", role,
                 "--policy-name", "api-keys-read",
                 "--policy-document", new_policy,
                 "--region", REGION,
                 "--no-cli-pager"])
    if rc == 0:
        print(f"  ✓ {role}: api-keys-read → scoped")
    else:
        print(f"  ✗ {role}: update failed")

PYEOF

echo ""

# ─────────────────────────────────────────────────────────────────────────────
# FIX 3: Add 13 new IAM roles to KMS key policy
# ─────────────────────────────────────────────────────────────────────────────
echo "Fix 3: Adding 13 new roles to KMS key policy..."

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

# Get current KMS policy
r = subprocess.run(
    ["aws", "kms", "get-key-policy",
     "--key-id", KMS_KEY_ID,
     "--policy-name", "default",
     "--region", REGION,
     "--output", "text",
     "--no-cli-pager"],
    capture_output=True, text=True
)
if r.returncode != 0:
    print(f"  ✗ Could not read KMS policy: {r.stderr}")
    sys.exit(1)

policy = json.loads(r.stdout)

# Find the Lambda decrypt statement and add new ARNs
added = 0
found_stmt = False
for stmt in policy.get("Statement", []):
    actions = stmt.get("Action", [])
    if isinstance(actions, str):
        actions = [actions]
    if not any(a in ("kms:Decrypt", "kms:GenerateDataKey") for a in actions):
        continue
    found_stmt = True
    principal = stmt.get("Principal", {})
    aws_p = principal.get("AWS", [])
    if isinstance(aws_p, str):
        aws_p = [aws_p]
    for arn in NEW_ROLE_ARNS:
        if arn not in aws_p:
            aws_p.append(arn)
            added += 1
    stmt["Principal"]["AWS"] = aws_p

if not found_stmt:
    # No existing Lambda decrypt statement — create one
    print("  No existing Lambda decrypt statement found — creating one")
    policy["Statement"].append({
        "Sid": "LambdaDecrypt",
        "Effect": "Allow",
        "Principal": {"AWS": NEW_ROLE_ARNS},
        "Action": ["kms:Decrypt", "kms:GenerateDataKey"],
        "Resource": "*"
    })
    added = len(NEW_ROLE_ARNS)

print(f"  Added {added} new ARNs to KMS policy")

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
if r2.returncode == 0:
    print(f"  ✓ KMS key policy updated")
else:
    print(f"  ✗ KMS update failed: {r2.stderr}")
    sys.exit(1)

# Verify
r3 = subprocess.run(
    ["aws", "kms", "get-key-policy",
     "--key-id", KMS_KEY_ID,
     "--policy-name", "default",
     "--region", REGION,
     "--output", "text",
     "--no-cli-pager"],
    capture_output=True, text=True
)
policy2 = json.loads(r3.stdout)
for stmt in policy2.get("Statement", []):
    actions = stmt.get("Action", [])
    if isinstance(actions, str): actions = [actions]
    if any(a in ("kms:Decrypt", "kms:GenerateDataKey") for a in actions):
        principals = stmt.get("Principal", {}).get("AWS", [])
        if isinstance(principals, str): principals = [principals]
        new_found = sum(1 for p in principals if any(
            r in p for r in ["daily-brief-role", "weekly-digest-role-v2", "monthly-digest-role",
                              "nutrition-review-role", "wednesday-chronicle-role", "weekly-plate-role",
                              "monday-compass-role", "adaptive-mode-role", "daily-metrics-role",
                              "daily-insight-role", "hypothesis-engine-role", "qa-smoke-role", "data-export-role"]
        ))
        print(f"  Verification: {len(principals)} total principals, {new_found}/13 new roles confirmed")
PYEOF

echo ""
echo "=== Fix complete ==="
echo ""
echo "git add -A && git commit -m 'v3.1.1: IAM-1 part 2 — secret ARNs scoped, KMS updated' && git push"
