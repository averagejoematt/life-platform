#!/usr/bin/env bash
set -euo pipefail

# ══════════════════════════════════════════════════════════════════════════════
# Life Platform — P0/P1 Infrastructure Fixes
# 
# What this does:
#   1. Sets standardized environment variables on ALL 22 Lambdas
#   2. Standardizes runtimes to python3.12
#   3. Cleans up .bak files and stale artifacts
#   4. Deploys updated mcp_server.py (parameterized)
#   5. Deploys updated daily_brief_lambda.py (parameterized)
#
# Run from: ~/Documents/Claude/life-platform/
# ══════════════════════════════════════════════════════════════════════════════

REGION="us-west-2"
DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$DIR/.." && pwd)"

echo "╔══════════════════════════════════════════════════════╗"
echo "║  Life Platform — P0/P1 Fixes Deploy                 ║"
echo "║  Env vars + runtime + cleanup + code deploy         ║"
echo "╚══════════════════════════════════════════════════════╝"
echo ""

# ── Common env vars for ALL Lambdas ──────────────────────────────────────────
TABLE_NAME="life-platform"
S3_BUCKET="matthew-life-platform"
USER_ID="matthew"
EMAIL_RECIPIENT="awsdev@mattsusername.com"
EMAIL_SENDER="awsdev@mattsusername.com"

# ══════════════════════════════════════════════════════════════════════════════
# PHASE 0: Patch local source files so git tracks the parameterized code
# ══════════════════════════════════════════════════════════════════════════════
echo "═══ PHASE 0: Patching local source files ═══"
echo ""

echo "  Patching mcp_server.py..."
python3 "$ROOT/patches/patch_parameterize_mcp.py" "$ROOT/mcp_server.py"
cp "$ROOT/mcp_server.py" "$ROOT/lambdas/mcp_server.py"
echo ""

echo "  Patching lambdas/daily_brief_lambda.py..."
python3 "$ROOT/patches/patch_parameterize_daily_brief.py" "$ROOT/lambdas/daily_brief_lambda.py"
echo ""

echo "  ✅ PHASE 0 COMPLETE: Local source files parameterized"
echo ""

# ══════════════════════════════════════════════════════════════════════════════
# PHASE 1: Set environment variables on all Lambdas
# ══════════════════════════════════════════════════════════════════════════════
echo "═══ PHASE 1: Setting environment variables on all Lambdas ═══"
echo ""

# Helper: update-function-configuration with env vars
# Usage: set_env <function-name> <json-env-vars>
set_env() {
    local FUNC="$1"
    local ENV_JSON="$2"
    echo "  → $FUNC"
    aws lambda update-function-configuration \
        --function-name "$FUNC" \
        --region "$REGION" \
        --environment "{\"Variables\": $ENV_JSON}" \
        --output text --query 'FunctionName' > /dev/null 2>&1
    sleep 2  # Rate limiting between calls
}

# ── Ingestion Lambdas ────────────────────────────────────────────────────────
echo "  Ingestion Lambdas..."

set_env "whoop-data-ingestion" "{
    \"TABLE_NAME\": \"$TABLE_NAME\",
    \"S3_BUCKET\": \"$S3_BUCKET\",
    \"USER_ID\": \"$USER_ID\",
    \"SECRET_NAME\": \"life-platform/whoop\"
}"

set_env "eightsleep-data-ingestion" "{
    \"TABLE_NAME\": \"$TABLE_NAME\",
    \"S3_BUCKET\": \"$S3_BUCKET\",
    \"USER_ID\": \"$USER_ID\",
    \"SECRET_NAME\": \"life-platform/eightsleep\"
}"

set_env "strava-data-ingestion" "{
    \"TABLE_NAME\": \"$TABLE_NAME\",
    \"S3_BUCKET\": \"$S3_BUCKET\",
    \"USER_ID\": \"$USER_ID\",
    \"SECRET_NAME\": \"life-platform/strava\"
}"

set_env "garmin-data-ingestion" "{
    \"TABLE_NAME\": \"$TABLE_NAME\",
    \"S3_BUCKET\": \"$S3_BUCKET\",
    \"USER_ID\": \"$USER_ID\",
    \"SECRET_NAME\": \"life-platform/garmin\"
}"

set_env "withings-data-ingestion" "{
    \"TABLE_NAME\": \"$TABLE_NAME\",
    \"S3_BUCKET\": \"$S3_BUCKET\",
    \"USER_ID\": \"$USER_ID\",
    \"SECRET_NAME\": \"life-platform/withings\"
}"

set_env "macrofactor-data-ingestion" "{
    \"TABLE_NAME\": \"$TABLE_NAME\",
    \"S3_BUCKET\": \"$S3_BUCKET\",
    \"USER_ID\": \"$USER_ID\"
}"

set_env "todoist-data-ingestion" "{
    \"TABLE_NAME\": \"$TABLE_NAME\",
    \"S3_BUCKET\": \"$S3_BUCKET\",
    \"USER_ID\": \"$USER_ID\",
    \"SECRET_NAME\": \"life-platform/todoist\"
}"

set_env "notion-journal-ingestion" "{
    \"TABLE_NAME\": \"$TABLE_NAME\",
    \"S3_BUCKET\": \"$S3_BUCKET\",
    \"USER_ID\": \"$USER_ID\",
    \"SECRET_NAME\": \"life-platform/notion\"
}"

set_env "habitify-data-ingestion" "{
    \"TABLE_NAME\": \"$TABLE_NAME\",
    \"S3_BUCKET\": \"$S3_BUCKET\",
    \"USER_ID\": \"$USER_ID\",
    \"SECRET_NAME\": \"life-platform/habitify\"
}"

set_env "weather-data-ingestion" "{
    \"TABLE_NAME\": \"$TABLE_NAME\",
    \"S3_BUCKET\": \"$S3_BUCKET\",
    \"USER_ID\": \"$USER_ID\"
}"

set_env "apple-health-ingestion" "{
    \"TABLE_NAME\": \"$TABLE_NAME\",
    \"S3_BUCKET\": \"$S3_BUCKET\",
    \"USER_ID\": \"$USER_ID\"
}"

set_env "health-auto-export-webhook" "{
    \"TABLE_NAME\": \"$TABLE_NAME\",
    \"S3_BUCKET\": \"$S3_BUCKET\",
    \"USER_ID\": \"$USER_ID\",
    \"SECRET_NAME\": \"life-platform/health-auto-export\"
}"

set_env "dropbox-poll" "{
    \"TABLE_NAME\": \"$TABLE_NAME\",
    \"S3_BUCKET\": \"$S3_BUCKET\",
    \"USER_ID\": \"$USER_ID\",
    \"SECRET_NAME\": \"life-platform/dropbox\"
}"

echo "  ✅ Ingestion Lambdas configured"
echo ""

# ── Enrichment Lambdas ───────────────────────────────────────────────────────
echo "  Enrichment Lambdas..."

set_env "activity-enrichment" "{
    \"TABLE_NAME\": \"$TABLE_NAME\",
    \"S3_BUCKET\": \"$S3_BUCKET\",
    \"USER_ID\": \"$USER_ID\"
}"

set_env "journal-enrichment" "{
    \"TABLE_NAME\": \"$TABLE_NAME\",
    \"S3_BUCKET\": \"$S3_BUCKET\",
    \"USER_ID\": \"$USER_ID\",
    \"ANTHROPIC_SECRET\": \"life-platform/anthropic\"
}"

echo "  ✅ Enrichment Lambdas configured"
echo ""

# ── Email/Digest Lambdas ─────────────────────────────────────────────────────
echo "  Email/Digest Lambdas..."

set_env "daily-brief" "{
    \"TABLE_NAME\": \"$TABLE_NAME\",
    \"S3_BUCKET\": \"$S3_BUCKET\",
    \"USER_ID\": \"$USER_ID\",
    \"EMAIL_RECIPIENT\": \"$EMAIL_RECIPIENT\",
    \"EMAIL_SENDER\": \"$EMAIL_SENDER\",
    \"ANTHROPIC_SECRET\": \"life-platform/anthropic\"
}"

set_env "weekly-digest" "{
    \"TABLE_NAME\": \"$TABLE_NAME\",
    \"S3_BUCKET\": \"$S3_BUCKET\",
    \"USER_ID\": \"$USER_ID\",
    \"EMAIL_RECIPIENT\": \"$EMAIL_RECIPIENT\",
    \"EMAIL_SENDER\": \"$EMAIL_SENDER\",
    \"ANTHROPIC_SECRET\": \"life-platform/anthropic\"
}"

set_env "monthly-digest" "{
    \"TABLE_NAME\": \"$TABLE_NAME\",
    \"S3_BUCKET\": \"$S3_BUCKET\",
    \"USER_ID\": \"$USER_ID\",
    \"EMAIL_RECIPIENT\": \"$EMAIL_RECIPIENT\",
    \"EMAIL_SENDER\": \"$EMAIL_SENDER\",
    \"ANTHROPIC_SECRET\": \"life-platform/anthropic\"
}"

set_env "anomaly-detector" "{
    \"TABLE_NAME\": \"$TABLE_NAME\",
    \"S3_BUCKET\": \"$S3_BUCKET\",
    \"USER_ID\": \"$USER_ID\",
    \"EMAIL_RECIPIENT\": \"$EMAIL_RECIPIENT\",
    \"EMAIL_SENDER\": \"$EMAIL_SENDER\"
}"

set_env "life-platform-freshness-checker" "{
    \"TABLE_NAME\": \"$TABLE_NAME\",
    \"S3_BUCKET\": \"$S3_BUCKET\",
    \"USER_ID\": \"$USER_ID\",
    \"EMAIL_RECIPIENT\": \"$EMAIL_RECIPIENT\",
    \"EMAIL_SENDER\": \"$EMAIL_SENDER\",
    \"SNS_ARN\": \"arn:aws:sns:us-west-2:205930651321:life-platform-alerts\"
}"

set_env "insight-email-parser" "{
    \"TABLE_NAME\": \"$TABLE_NAME\",
    \"S3_BUCKET\": \"$S3_BUCKET\",
    \"USER_ID\": \"$USER_ID\",
    \"ALLOWED_SENDERS\": \"awsdev@mattsusername.com,mattsthrowaway@protonmail.com\"
}"

echo "  ✅ Email/Digest Lambdas configured"
echo ""

# ── MCP Server ───────────────────────────────────────────────────────────────
echo "  MCP Server..."

set_env "life-platform-mcp" "{
    \"TABLE_NAME\": \"$TABLE_NAME\",
    \"S3_BUCKET\": \"$S3_BUCKET\",
    \"USER_ID\": \"$USER_ID\",
    \"API_SECRET_NAME\": \"life-platform/mcp-api-key\"
}"

echo "  ✅ MCP Server configured"
echo ""
echo "  ✅ PHASE 1 COMPLETE: All 22 Lambdas have standardized env vars"
echo ""

# ══════════════════════════════════════════════════════════════════════════════
# PHASE 2: Standardize runtimes to python3.12
# ══════════════════════════════════════════════════════════════════════════════
echo "═══ PHASE 2: Standardizing runtimes to python3.12 ═══"
echo ""

for FUNC in daily-brief monthly-digest anomaly-detector weekly-digest; do
    echo "  → $FUNC: python3.11 → python3.12"
    aws lambda update-function-configuration \
        --function-name "$FUNC" \
        --region "$REGION" \
        --runtime python3.12 \
        --output text --query 'FunctionName' > /dev/null 2>&1
    sleep 3
done

echo "  ✅ PHASE 2 COMPLETE: All Lambdas on python3.12"
echo ""

# ══════════════════════════════════════════════════════════════════════════════
# PHASE 3: Deploy updated MCP server (parameterized)
# ══════════════════════════════════════════════════════════════════════════════
echo "═══ PHASE 3: Deploying parameterized MCP server ═══"
echo ""

WORK="/tmp/mcp-p1-deploy"
rm -rf "$WORK" && mkdir -p "$WORK"

# Download current
echo "  Downloading current MCP Lambda..."
CODE_URL=$(aws lambda get-function \
    --function-name life-platform-mcp \
    --region "$REGION" \
    --query 'Code.Location' --output text)
curl -sL "$CODE_URL" -o "$WORK/current.zip"
cd "$WORK"
unzip -qo current.zip -d src/
echo "  ✅ Downloaded"

# Apply parameterization patcher
# Handler is mcp_server.lambda_handler → file is mcp_server.py
MCP_FILE="$WORK/src/mcp_server.py"
if [ ! -f "$MCP_FILE" ]; then
    MCP_FILE="$WORK/src/lambda_function.py"
fi
echo "  Applying parameterization patch to $(basename $MCP_FILE)..."
python3 "$ROOT/patches/patch_parameterize_mcp.py" "$MCP_FILE"
echo "  ✅ Patched"

# Repackage
echo "  Packaging..."
cd "$WORK/src"
zip -q -r "$WORK/mcp-parameterized.zip" .
echo "  ✅ Packaged ($(du -h "$WORK/mcp-parameterized.zip" | cut -f1))"

# Deploy
echo "  Deploying..."
aws lambda update-function-code \
    --function-name life-platform-mcp \
    --region "$REGION" \
    --zip-file "fileb://$WORK/mcp-parameterized.zip" \
    --output text --query 'FunctionName'
echo "  ✅ MCP server deployed with parameterized config"
echo ""

sleep 5

# ══════════════════════════════════════════════════════════════════════════════
# PHASE 4: Deploy updated Daily Brief (parameterized)
# ══════════════════════════════════════════════════════════════════════════════
echo "═══ PHASE 4: Deploying parameterized Daily Brief ═══"
echo ""

WORK_DB="/tmp/brief-p1-deploy"
rm -rf "$WORK_DB" && mkdir -p "$WORK_DB"

echo "  Downloading current Daily Brief Lambda..."
CODE_URL=$(aws lambda get-function \
    --function-name daily-brief \
    --region "$REGION" \
    --query 'Code.Location' --output text)
curl -sL "$CODE_URL" -o "$WORK_DB/current.zip"
cd "$WORK_DB"
unzip -qo current.zip -d src/
echo "  ✅ Downloaded"

# Handler is lambda_function.lambda_handler → file is lambda_function.py
BRIEF_FILE="$WORK_DB/src/lambda_function.py"
if [ ! -f "$BRIEF_FILE" ]; then
    BRIEF_FILE="$WORK_DB/src/daily_brief_lambda.py"
fi
echo "  Applying parameterization patch to $(basename $BRIEF_FILE)..."
python3 "$ROOT/patches/patch_parameterize_daily_brief.py" "$BRIEF_FILE"
echo "  ✅ Patched"

echo "  Packaging..."
cd "$WORK_DB/src"
zip -q -r "$WORK_DB/brief-parameterized.zip" .
echo "  ✅ Packaged ($(du -h "$WORK_DB/brief-parameterized.zip" | cut -f1))"

echo "  Deploying..."
aws lambda update-function-code \
    --function-name daily-brief \
    --region "$REGION" \
    --zip-file "fileb://$WORK_DB/brief-parameterized.zip" \
    --output text --query 'FunctionName'
echo "  ✅ Daily Brief deployed with parameterized config"
echo ""

# ══════════════════════════════════════════════════════════════════════════════
# PHASE 5: Cleanup
# ══════════════════════════════════════════════════════════════════════════════
echo "═══ PHASE 5: Cleanup ═══"
echo ""

cd "$ROOT"

echo "  Removing .bak files..."
find . -name "*.bak*" -not -path "./.git/*" -delete -print 2>/dev/null | while read f; do echo "    🗑  $f"; done
echo "  ✅ .bak files removed"

echo ""
echo "  Removing stale .zip files from lambdas/..."
find lambdas/ -name "*.zip" -delete -print 2>/dev/null | while read f; do echo "    🗑  $f"; done
echo "  ✅ Stale zips removed"

echo ""
echo "  Removing root mcp_server.zip..."
rm -f mcp_server.zip
echo "  ✅ Root zip removed"

echo ""

# ══════════════════════════════════════════════════════════════════════════════
# VERIFICATION
# ══════════════════════════════════════════════════════════════════════════════
echo "═══ VERIFICATION ═══"
echo ""

echo "  MCP server env vars:"
aws lambda get-function-configuration \
    --function-name life-platform-mcp \
    --region "$REGION" \
    --query 'Environment.Variables' --output json
echo ""

echo "  Daily Brief env vars:"
aws lambda get-function-configuration \
    --function-name daily-brief \
    --region "$REGION" \
    --query 'Environment.Variables' --output json
echo ""

echo "  Runtime check (should all be python3.12):"
aws lambda list-functions \
    --region "$REGION" \
    --query "Functions[].{Name:FunctionName,Runtime:Runtime}" --output table
echo ""

echo "╔══════════════════════════════════════════════════════╗"
echo "║  ✅ ALL PHASES COMPLETE                             ║"
echo "║                                                     ║"
echo "║  Phase 1: Env vars set on 22 Lambdas                ║"
echo "║  Phase 2: All runtimes → python3.12                 ║"
echo "║  Phase 3: MCP server parameterized + deployed       ║"
echo "║  Phase 4: Daily Brief parameterized + deployed      ║"
echo "║  Phase 5: .bak + stale zips cleaned up              ║"
echo "║                                                     ║"
echo "║  NEXT: Test MCP query + verify tomorrow's brief     ║"
echo "╚══════════════════════════════════════════════════════╝"
