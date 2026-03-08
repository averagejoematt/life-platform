#!/bin/bash
# deploy_daily_brief_v2_timing.sh — Session 1: Profile v2 + timing shift
#
# Changes:
#   1. Seeds Profile v2.0 to DynamoDB
#   2. Patches Whoop Lambda to accept date_override event parameter
#   3. Adds Whoop recovery refresh at 9:30 AM PT (pulls today's recovery)
#   4. Shifts freshness check to 9:45 AM PT
#   5. Shifts daily brief to 10:00 AM PT
#
# Run: cd ~/Documents/Claude/life-platform && bash deploy_daily_brief_v2_timing.sh

set -euo pipefail
REGION="us-west-2"
ACCOUNT="205930651321"

echo "═══════════════════════════════════════════════════════"
echo "  Daily Brief v2 — Session 1: Profile + Timing"
echo "═══════════════════════════════════════════════════════"

# ── Step 1: Seed Profile v2.0 ────────────────────────────────────────────────
echo ""
echo "🔧 Step 1: Seeding Profile v2.0..."
python3 seed_profile_v2.py
echo ""

# ── Step 1b: Quick-patch daily brief constants until Session 2 rewrite ─────────
echo "🔧 Step 1b: Patching daily brief constants (wake=4:30, sleep=7.5h, protein=190)..."

python3 -c "
import re

with open('daily_brief_lambda.py', 'r') as f:
    content = f.read()

# Fix hardcoded targets
content = content.replace('TARGET_WAKE_HOUR  = 6', 'TARGET_WAKE_HOUR  = 4      # 4:30am PT target (Profile v2)')
content = content.replace('SLEEP_TARGET_HRS  = 7.5', 'SLEEP_TARGET_HRS  = 7.5    # 7-9h range, 7.5 ideal (Profile v2)')
content = content.replace('PROTEIN_TARGET_G  = 180', 'PROTEIN_TARGET_G  = 190    # Board: 1g/lb goal weight (Profile v2)')
content = content.replace('CALORIE_TARGET    = 1800', 'CALORIE_TARGET    = 1800   # From Profile v2 (will be dynamic in v2 rewrite)')

with open('daily_brief_lambda.py', 'w') as f:
    f.write(content)
print('✅ Daily brief constants patched')
"

# Repackage and deploy daily brief
echo "📦 Repackaging daily brief Lambda..."
cd /tmp
rm -rf brief_build daily_brief_lambda.zip
mkdir brief_build
cp ~/Documents/Claude/life-platform/daily_brief_lambda.py brief_build/lambda_function.py
cd brief_build && zip -q ../daily_brief_lambda.zip lambda_function.py && cd ..

echo "🚀 Deploying daily brief Lambda..."
aws lambda update-function-code \
    --function-name daily-brief \
    --zip-file fileb:///tmp/daily_brief_lambda.zip \
    --region $REGION \
    --no-cli-pager

cp /tmp/daily_brief_lambda.zip ~/Documents/Claude/life-platform/daily_brief_lambda.zip
echo "✅ Daily brief Lambda deployed with corrected targets"
echo ""

# ── Step 2: Patch Whoop Lambda for date_override ──────────────────────────────
echo "🔧 Step 2: Patching Whoop Lambda for recovery refresh support..."

# Create patched whoop lambda
cp whoop_lambda.py whoop_lambda_backup.py

# Patch the handler to accept date_override from event
python3 -c "
import re

with open('whoop_lambda.py', 'r') as f:
    content = f.read()

# Replace the hardcoded yesterday date with event-driven date
old_handler_start = '''def lambda_handler(event, context):
    yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).date()
    date_str = yesterday.strftime(\"%Y-%m-%d\")
    print(f\"[INFO] Starting Whoop data ingestion for date: {date_str}\")'''

new_handler_start = '''def lambda_handler(event, context):
    # Support date_override from EventBridge event payload
    # 'today' = pull today's data (for recovery refresh after wake)
    # 'YYYY-MM-DD' = pull specific date
    # None/missing = default to yesterday
    date_override = event.get('date_override') if isinstance(event, dict) else None
    
    if date_override == 'today':
        target_date = datetime.now(timezone.utc).date()
    elif date_override:
        target_date = datetime.strptime(date_override, '%Y-%m-%d').date()
    else:
        target_date = (datetime.now(timezone.utc) - timedelta(days=1)).date()
    
    yesterday = target_date  # Keep variable name for downstream compat
    date_str = yesterday.strftime(\"%Y-%m-%d\")
    print(f\"[INFO] Starting Whoop data ingestion for date: {date_str} (override={date_override})\")'''

if old_handler_start in content:
    content = content.replace(old_handler_start, new_handler_start)
    with open('whoop_lambda.py', 'w') as f:
        f.write(content)
    print('✅ Whoop Lambda patched for date_override')
else:
    print('⚠️  Could not find exact handler pattern — may need manual patch')
    print('    Check whoop_lambda.py handler start')
"

# Package and deploy whoop lambda
echo "📦 Packaging Whoop Lambda..."
cd /tmp
rm -rf whoop_build whoop_lambda.zip
mkdir whoop_build
cp ~/Documents/Claude/life-platform/whoop_lambda.py whoop_build/lambda_function.py
cd whoop_build && zip -q ../whoop_lambda.zip lambda_function.py && cd ..

echo "🚀 Deploying Whoop Lambda..."
aws lambda update-function-code \
    --function-name whoop-data-ingestion \
    --zip-file fileb:///tmp/whoop_lambda.zip \
    --region $REGION \
    --no-cli-pager

# Copy zip back for reference
cp /tmp/whoop_lambda.zip ~/Documents/Claude/life-platform/whoop_lambda.zip

echo "✅ Whoop Lambda deployed with date_override support"
echo ""

# ── Step 3: Add Whoop Recovery Refresh at 9:30 AM PT ─────────────────────────
echo "🔧 Step 3: Creating Whoop recovery refresh schedule (9:30 AM PT)..."

# 9:30 AM PT = 17:30 UTC
aws events put-rule \
    --name "whoop-recovery-refresh" \
    --schedule-expression "cron(30 17 * * ? *)" \
    --state ENABLED \
    --description "Whoop recovery refresh — 9:30 AM PT, pulls today's recovery after wake" \
    --region $REGION \
    --no-cli-pager

# Get the Whoop Lambda ARN
WHOOP_ARN=$(aws lambda get-function \
    --function-name whoop-data-ingestion \
    --query 'Configuration.FunctionArn' \
    --output text \
    --region $REGION)

# Add permission for EventBridge to invoke Lambda (idempotent)
aws lambda add-permission \
    --function-name whoop-data-ingestion \
    --statement-id "whoop-recovery-refresh-invoke" \
    --action "lambda:InvokeFunction" \
    --principal events.amazonaws.com \
    --source-arn "arn:aws:events:${REGION}:${ACCOUNT}:rule/whoop-recovery-refresh" \
    --region $REGION \
    --no-cli-pager 2>/dev/null || echo "   (permission already exists — OK)"

# Target with date_override = "today"
aws events put-targets \
    --rule "whoop-recovery-refresh" \
    --targets "[{
        \"Id\": \"whoop-recovery-refresh-target\",
        \"Arn\": \"${WHOOP_ARN}\",
        \"Input\": \"{\\\"date_override\\\": \\\"today\\\"}\"
    }]" \
    --region $REGION \
    --no-cli-pager

echo "✅ Whoop recovery refresh scheduled at 9:30 AM PT (today's recovery)"
echo ""

# ── Step 4: Shift freshness check to 9:45 AM PT ──────────────────────────────
echo "🔧 Step 4: Moving freshness check to 9:45 AM PT..."

# 9:45 AM PT = 17:45 UTC
aws events put-rule \
    --name "life-platform-freshness-check" \
    --schedule-expression "cron(45 17 * * ? *)" \
    --state ENABLED \
    --description "Daily data freshness check — 9:45 AM PT, after recovery refresh" \
    --region $REGION \
    --no-cli-pager

echo "✅ Freshness check moved to 9:45 AM PT"
echo ""

# ── Step 5: Shift daily brief to 10:00 AM PT ─────────────────────────────────
echo "🔧 Step 5: Moving daily brief to 10:00 AM PT..."

# 10:00 AM PT = 18:00 UTC
aws events put-rule \
    --name "daily-brief-schedule" \
    --schedule-expression "cron(0 18 * * ? *)" \
    --state ENABLED \
    --description "Daily brief email — 10:00 AM PT, after all data + recovery refresh" \
    --region $REGION \
    --no-cli-pager

echo "✅ Daily brief moved to 10:00 AM PT"
echo ""

# ── Step 6: Also update cache warmer to 9:00 AM PT ───────────────────────────
echo "🔧 Step 6: Moving cache warmer to 9:00 AM PT (before brief)..."

# 9:00 AM PT = 17:00 UTC
aws events put-rule \
    --name "life-platform-nightly-warmer" \
    --schedule-expression "cron(0 17 * * ? *)" \
    --state ENABLED \
    --description "Morning 9am PT cache warmer for life-platform MCP (after initial ingestion)" \
    --region $REGION \
    --no-cli-pager

echo "✅ Cache warmer moved to 9:00 AM PT"
echo ""

# ── Summary ───────────────────────────────────────────────────────────────────
echo "═══════════════════════════════════════════════════════"
echo "  ✅ Session 1 Complete — New Schedule (PT)"
echo "═══════════════════════════════════════════════════════"
echo ""
echo "  6:00 AM   Whoop, Garmin, Notion ingestion"
echo "  6:15 AM   Withings, Habitify ingestion"
echo "  6:30 AM   Strava, Journal Enrichment"
echo "  6:45 AM   Todoist"
echo "  7:00 AM   Eight Sleep"
echo "  7:30 AM   Activity Enrichment"
echo "  8:00 AM   MacroFactor ingestion"
echo "  ─── NEW WINDOW ───"
echo "  9:00 AM   Cache warmer (moved from 8:00)"
echo "  9:30 AM   Whoop recovery refresh (NEW — today's data)"
echo "  9:45 AM   Freshness check (moved from 8:15)"
echo "  10:00 AM  Daily Brief email (moved from 8:15)"
echo ""
echo "  Profile v2.0 seeded with:"
echo "    • Wake target 4:30 AM / Bedtime 9:00 PM"
echo "    • 1800 cal / P190 F60 C125"
echo "    • 9 MVP habits for streak tracking"
echo "    • Day grade weights v1.0"
echo "    • Board of Directors coaching context"
echo "    • Quarterly reminders set"
echo ""
echo "  Next: Session 2 — Rewrite daily brief Lambda with"
echo "  day grade, scorecard, streaks, expanded data, BoD insight"
echo ""
