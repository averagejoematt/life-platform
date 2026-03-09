#!/bin/bash
# p1_fix_scheduler_role_and_migrate.sh
# Fixes the scheduler role trust policy then re-runs the migration.
# Usage: cd ~/Documents/Claude/life-platform && bash deploy/p1_fix_scheduler_role_and_migrate.sh

set -euo pipefail
REGION="us-west-2"
ACCOUNT="205930651321"

echo "── Fixing scheduler role trust policy ──"

TRUST_POLICY=$(python3 - <<'PYEOF'
import json
policy = {
    "Version": "2012-10-17",
    "Statement": [{
        "Effect": "Allow",
        "Principal": {"Service": "scheduler.amazonaws.com"},
        "Action": "sts:AssumeRole",
        "Condition": {
            "StringEquals": {
                "aws:SourceAccount": "205930651321"
            }
        }
    }]
}
print(json.dumps(policy))
PYEOF
)

aws iam update-assume-role-policy \
    --role-name "life-platform-scheduler-role" \
    --policy-document "$TRUST_POLICY" \
    --no-cli-pager
echo "  ✅ Trust policy updated"

echo ""
echo "── Waiting 10s for IAM propagation ──"
sleep 10

echo ""
echo "── Running scheduler migration ──"
bash deploy/p1_migrate_eventbridge_scheduler.sh
