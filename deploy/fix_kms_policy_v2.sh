#!/usr/bin/env bash
# Fix KMS key policy: prune invalid principals, add 13 new roles
# Run from: ~/Documents/Claude/life-platform/
# Usage:    bash deploy/fix_kms_policy_v2.sh

set -euo pipefail
REGION="us-west-2"
ACCOUNT="205930651321"
KMS_KEY_ID="444438d1-a5e0-43b8-9391-3cd2d70dde4d"

echo "=== KMS key policy update (with dead-principal pruning) ==="
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

def run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    return r.stdout.strip(), r.stderr.strip(), r.returncode

# ── 1. Fetch current policy ───────────────────────────────────────────────────
out, err, rc = run(["aws", "kms", "get-key-policy",
    "--key-id", KMS_KEY_ID, "--policy-name", "default",
    "--region", REGION, "--output", "json", "--no-cli-pager"])
if rc != 0:
    print(f"✗ Could not read KMS policy: {err}"); sys.exit(1)

policy = json.loads(json.loads(out)["Policy"])

# ── 2. Get all valid role ARNs in the account ─────────────────────────────────
print("Fetching all live IAM roles to prune dead principals...")
out2, _, _ = run(["aws", "iam", "list-roles",
    "--query", "Roles[*].Arn", "--output", "json", "--no-cli-pager"])
live_role_arns = set(json.loads(out2))

# Also collect valid user ARNs (root + any IAM users)
out3, _, _ = run(["aws", "iam", "list-users",
    "--query", "Users[*].Arn", "--output", "json", "--no-cli-pager"])
live_user_arns = set(json.loads(out3))

# Root account ARN is always valid
root_arn = f"arn:aws:iam::{ACCOUNT}:root"
live_arns = live_role_arns | live_user_arns | {root_arn}
print(f"  Found {len(live_role_arns)} live roles, {len(live_user_arns)} users")

# ── 3. Update the Lambda decrypt statement ────────────────────────────────────
for stmt in policy.get("Statement", []):
    actions = stmt.get("Action", [])
    if isinstance(actions, str): actions = [actions]
    if not any(a in ("kms:Decrypt", "kms:GenerateDataKey") for a in actions):
        continue

    principal = stmt.get("Principal", {})
    aws_p = principal.get("AWS", [])
    if isinstance(aws_p, str): aws_p = [aws_p]

    before = len(aws_p)

    # Prune dead ARNs (keep root, keep anything that's still a live role/user)
    # ARNs that are numeric-only (deleted principals show as AROA... or just the ID)
    valid = []
    pruned = []
    for arn in aws_p:
        # Assumed-role ARNs (arn:aws:sts::) are session-based — skip them
        # Role ARNs (arn:aws:iam::) must exist in live set
        if "sts::" in arn:
            pruned.append(arn)
        elif arn == root_arn:
            valid.append(arn)
        elif arn in live_arns:
            valid.append(arn)
        else:
            pruned.append(arn)

    if pruned:
        print(f"  Pruning {len(pruned)} invalid/stale principals:")
        for p in pruned:
            print(f"    - {p}")

    # Add new role ARNs
    added = 0
    for arn in NEW_ROLE_ARNS:
        if arn not in valid:
            valid.append(arn)
            added += 1

    stmt["Principal"]["AWS"] = valid
    print(f"  Before: {before} principals | Pruned: {len(pruned)} | Added: {added} | After: {len(valid)}")
    break

# ── 4. Apply updated policy ───────────────────────────────────────────────────
new_policy_str = json.dumps(policy)
_, err2, rc2 = run(["aws", "kms", "put-key-policy",
    "--key-id", KMS_KEY_ID, "--policy-name", "default",
    "--policy", new_policy_str,
    "--region", REGION, "--no-cli-pager"])
if rc2 != 0:
    print(f"✗ KMS update failed: {err2}")
    # Save for manual inspection
    with open("/tmp/kms_policy_attempted.json", "w") as f:
        json.dump(policy, f, indent=2)
    print("  Policy saved to /tmp/kms_policy_attempted.json for inspection")
    sys.exit(1)

print("✓ KMS key policy updated successfully")

# ── 5. Verify ─────────────────────────────────────────────────────────────────
out4, _, _ = run(["aws", "kms", "get-key-policy",
    "--key-id", KMS_KEY_ID, "--policy-name", "default",
    "--region", REGION, "--output", "json", "--no-cli-pager"])
policy2 = json.loads(json.loads(out4)["Policy"])
for stmt in policy2.get("Statement", []):
    actions = stmt.get("Action", [])
    if isinstance(actions, str): actions = [actions]
    if not any(a in ("kms:Decrypt", "kms:GenerateDataKey") for a in actions):
        continue
    principals = stmt.get("Principal", {}).get("AWS", [])
    if isinstance(principals, str): principals = [principals]
    new_found = sum(1 for p in principals if any(r in p for r in [
        "daily-brief-role", "weekly-digest-role-v2", "monthly-digest-role",
        "nutrition-review-role", "wednesday-chronicle-role", "weekly-plate-role",
        "monday-compass-role", "adaptive-mode-role", "daily-metrics-role",
        "daily-insight-role", "hypothesis-engine-role", "qa-smoke-role", "data-export-role"
    ]))
    print(f"Verification: {len(principals)} principals in decrypt stmt, {new_found}/13 new roles confirmed")
    break

PYEOF

echo ""
echo "git add -A && git commit -m 'v3.1.2: KMS policy — pruned stale principals, added 13 new roles' && git push"
