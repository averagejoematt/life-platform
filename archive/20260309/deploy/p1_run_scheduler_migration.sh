#!/bin/bash
# p1_run_scheduler_migration.sh — Deploy monthly-digest update then run scheduler migration
# Usage: cd ~/Documents/Claude/life-platform && bash deploy/p1_run_scheduler_migration.sh

set -euo pipefail

echo "── Deploying updated monthly-digest (Monday guard) ──"
bash deploy/deploy_lambda.sh monthly-digest lambdas/monthly_digest_lambda.py \
    --extra-files lambdas/board_loader.py lambdas/insight_writer.py lambdas/retry_utils.py
sleep 5

echo ""
echo "── Running EventBridge → Scheduler migration ──"
bash deploy/p1_migrate_eventbridge_scheduler.sh
