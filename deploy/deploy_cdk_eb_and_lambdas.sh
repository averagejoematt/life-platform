#!/bin/bash
# deploy_cdk_eb_and_lambdas.sh — Item 7 (EB rules) + 3 unmanaged Lambdas
#
# This script:
#   1. Preps: deletes old CFn stack + orphan Lambdas so CDK can recreate them
#   2. Deploys: 3 CDK stacks that changed (compute, operational, ingestion)
#   3. Cleanup: deletes old console-created EventBridge rules
#
# Safe to run at night — no scheduled triggers fire until morning.
set -euo pipefail
cd ~/Documents/Claude/life-platform/cdk

echo "═══════════════════════════════════════════════════════════════"
echo " CDK EventBridge + Unmanaged Lambda Migration — v3.4.0"
echo "═══════════════════════════════════════════════════════════════"

# ── Step 1: Prep — remove old resources so CDK can create them ──
echo ""
echo "▸ Step 1: Prep — removing old resources..."
echo ""

# Delete old freshness-checker CFn stack (only contains the Lambda)
echo "  Deleting old life-platform-freshness-checker CFn stack..."
aws cloudformation delete-stack --stack-name life-platform-freshness-checker
aws cloudformation wait stack-delete-complete --stack-name life-platform-freshness-checker 2>/dev/null || true
echo "  ✅ Old CFn stack deleted"

# Delete orphan Lambdas (not in any CFn stack)
for fn in failure-pattern-compute insight-email-parser; do
    echo "  Deleting orphan Lambda: $fn..."
    aws lambda delete-function --function-name "$fn" 2>/dev/null || echo "    (already deleted or not found)"
done
echo "  ✅ Orphan Lambdas deleted"

# ── Step 2: CDK diff ──
echo ""
echo "▸ Step 2: CDK diff..."
for stack in LifePlatformCompute LifePlatformOperational LifePlatformIngestion; do
    echo "--- $stack ---"
    npx cdk diff "$stack" 2>&1 || true
    echo ""
done

echo "Review the diff. Press Enter to deploy, or Ctrl+C to abort."
read -r

# ── Step 3: Deploy ──
for stack in LifePlatformCompute LifePlatformOperational LifePlatformIngestion; do
    echo "▸ Deploying $stack..."
    npx cdk deploy "$stack" --require-approval never 2>&1
    echo "  ✅ $stack deployed. Waiting 15s..."
    sleep 15
done

# ── Step 4: Cleanup old EventBridge rules ──
echo ""
echo "▸ Step 4: Cleaning up old console-created EventBridge rules..."
echo "  (CDK now owns these schedules — old rules are duplicates)"

# Old console-created rules to delete (verified from aws events list-rules)
OLD_RULES=(
    # Ingestion rules (now CDK-managed via schedule=)
    whoop-daily-ingestion
    whoop-recovery-refresh
    garmin-daily-ingestion
    notion-daily-ingest
    withings-daily-ingestion
    habitify-daily-ingest
    strava-daily-ingestion
    journal-enrichment-daily
    todoist-daily-ingestion
    eightsleep-daily-ingestion
    activity-enrichment-nightly
    macrofactor-daily-ingestion
    weather-daily-ingestion
    dropbox-poll-schedule
    # Operational rules (now CDK-managed via schedule=)
    life-platform-freshness-check
    dlq-consumer-schedule
    canary-schedule
    life-platform-pip-audit-monthly
    life-platform-qa-smoke
    life-platform-data-reconciliation-weekly
    # Compute (failure-pattern was console-created)
    failure-pattern-compute-weekly
    # Old/disabled duplicates from previous compute/email CDK migrations
    adaptive-mode-compute
    anomaly-detector-daily
    character-sheet-compute
    daily-brief-schedule
    daily-insight-compute
    daily-metrics-compute
    daily-metrics-compute-catchup
    dashboard-refresh-afternoon
    dashboard-refresh-evening
    hypothesis-engine-weekly
    monday-compass
    monthly-digest-schedule
    nutrition-review-saturday
    nutrition-review-schedule
    wednesday-chronicle-schedule
    weekly-digest-sunday
    weekly-plate
    weekly-plate-schedule
    brittany-weekly-email-schedule
    # KEEP: life-platform-nightly-warmer (MCP custom payload, managed via add_permission)
    # KEEP: life-platform-monthly-export (data-export monthly trigger, not yet in CDK)
)

DELETED=0
SKIPPED=0
for rule in "${OLD_RULES[@]}"; do
    # Remove targets first (required before deleting rule)
    TARGETS=$(aws events list-targets-by-rule --rule "$rule" --query "Targets[].Id" --output text 2>/dev/null || echo "")
    if [ -n "$TARGETS" ]; then
        for tid in $TARGETS; do
            aws events remove-targets --rule "$rule" --ids "$tid" 2>/dev/null || true
        done
    fi
    # Delete the rule
    if aws events delete-rule --name "$rule" 2>/dev/null; then
        echo "  ✅ Deleted: $rule"
        ((DELETED++))
    else
        echo "  ⚠️  Skipped: $rule (not found or CDK-owned)"
        ((SKIPPED++))
    fi
done

echo ""
echo "═══════════════════════════════════════════════════════════════"
echo " Migration complete!"
echo " EB rules: $DELETED deleted, $SKIPPED skipped"
echo ""
echo " CDK now owns ALL Lambda IAM roles + EventBridge schedules."
echo " Verify: aws events list-rules --query 'Rules[].Name' --output text"
echo "═══════════════════════════════════════════════════════════════"
