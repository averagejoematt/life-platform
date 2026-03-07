#!/bin/bash
# Deploy Todoist integration — v2.83.0
# 1. Enhanced todoist_lambda (overdue/due-today/priority breakdown)
# 2. New tools_todoist.py module (5 MCP tools)
# 3. Updated registry.py (import + 5 tool registrations)
# 4. Daily Brief + html_builder (task load section)

set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

echo "=== Todoist Integration Deploy ==="

# Step 1: Deploy enhanced todoist ingestion Lambda
echo ""
echo "Step 1/3: Deploying enhanced todoist-data-ingestion Lambda..."
bash "$SCRIPT_DIR/deploy_lambda.sh" todoist-data-ingestion "$ROOT/lambdas/todoist_lambda.py"
echo "Waiting 10s..."
sleep 10

# Step 2: Deploy MCP server (new tools_todoist module + registry update)
echo ""
echo "Step 2/3: Deploying life-platform-mcp (5 new Todoist tools)..."
bash "$SCRIPT_DIR/deploy_lambda.sh" life-platform-mcp "$ROOT/lambdas/mcp_server.py"
echo "Waiting 10s..."
sleep 10

# Step 3: Deploy Daily Brief (task load section in html_builder)
echo ""
echo "Step 3/3: Deploying daily-brief Lambda (task load tile)..."
bash "$SCRIPT_DIR/deploy_lambda.sh" daily-brief "$ROOT/lambdas/daily_brief_lambda.py"

echo ""
echo "=== Deploy complete ==="
echo ""
echo "Verify:"
echo "  1. Trigger todoist-data-ingestion manually to test new fields:"
echo "     aws lambda invoke --function-name todoist-data-ingestion --payload '{\"date\":\"$(date -v-1d +%Y-%m-%d 2>/dev/null || date -d yesterday +%Y-%m-%d)\"}' /tmp/todoist_test.json --region us-west-2"
echo "     cat /tmp/todoist_test.json"
echo ""
echo "  2. Check CloudWatch logs for 'Overdue: X, Due today: Y':"
echo "     aws logs describe-log-streams --log-group-name /aws/lambda/todoist-data-ingestion --order-by LastEventTime --descending --limit 1 --region us-west-2"
echo ""
echo "  3. MCP tools now available: get_task_completion_trend, get_task_load_summary,"
echo "     get_project_activity, get_decision_fatigue_signal, get_todoist_day"
