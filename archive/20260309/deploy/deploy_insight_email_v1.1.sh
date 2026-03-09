#!/bin/bash
# deploy_insight_email_v1.1.sh — Deploy updated Lambdas for insight email pipeline
# Version: v2.39.2
#
# Updates:
#   1. insight-email-parser Lambda v1.1.0 (subdomain routing, dynamic reply-to-sender, env-based ALLOWED_SENDERS)
#   2. daily-brief Lambda (adds Reply-To: insight@aws.mattsusername.com so replies route to SES)
#
# Run AFTER deploy_insight_email_pipeline.sh has set up SES rules + DNS

set -euo pipefail
REGION="us-west-2"
LAMBDA_DIR="$HOME/Documents/Claude/life-platform/lambdas"
INSIGHT_LAMBDA="insight-email-parser"
DAILY_BRIEF_LAMBDA="life-platform-daily-brief"
REPLY_TO_ADDRESS="insight@aws.mattsusername.com"

echo "=== Part 1: Deploy insight-email-parser v1.1.0 ==="

# Package insight email parser
cd "$LAMBDA_DIR"
cp insight_email_parser_lambda.py lambda_function.py
zip -j insight_email_parser_lambda.zip lambda_function.py
rm lambda_function.py

# Deploy
aws lambda update-function-code \
  --function-name "$INSIGHT_LAMBDA" \
  --zip-file fileb://insight_email_parser_lambda.zip \
  --region "$REGION" \
  --query '{FunctionName: FunctionName, CodeSize: CodeSize, LastModified: LastModified}' \
  --output table

echo ""
echo "Setting ALLOWED_SENDERS env var..."

aws lambda update-function-configuration \
  --function-name "$INSIGHT_LAMBDA" \
  --environment "Variables={ALLOWED_SENDERS=awsdev@mattsusername.com}" \
  --region "$REGION" \
  --query '{FunctionName: FunctionName, Environment: Environment}' \
  --output table

echo "ALLOWED_SENDERS set to awsdev@mattsusername.com"

echo ""
echo "=== Part 2: Patch daily-brief with Reply-To header ==="
sleep 10

# Patch the Daily Brief to add ReplyToAddresses
# This is a targeted edit: add ReplyToAddresses to the ses.send_email call
echo "Downloading current daily-brief Lambda code..."
aws lambda get-function \
  --function-name "$DAILY_BRIEF_LAMBDA" \
  --region "$REGION" \
  --query 'Code.Location' \
  --output text > /tmp/daily_brief_url.txt

curl -s -o /tmp/daily_brief_current.zip "$(cat /tmp/daily_brief_url.txt)"
mkdir -p /tmp/daily_brief_extract
cd /tmp/daily_brief_extract
rm -rf *
unzip -o /tmp/daily_brief_current.zip

# Patch: add ReplyToAddresses to send_email call
# The current call looks like:
#   ses.send_email(
#       FromEmailAddress=SENDER,
#       Destination={"ToAddresses": [RECIPIENT]},
#       Content={...}
#   )
# We add:
#       ReplyToAddresses=["insight@aws.mattsusername.com"],

if grep -q "ReplyToAddresses" lambda_function.py; then
  echo "Reply-To already present in daily-brief — skipping patch"
else
  python3 -c "
import re

with open('lambda_function.py', 'r') as f:
    code = f.read()

# Find the send_email call and add ReplyToAddresses after FromEmailAddress
old = 'FromEmailAddress=SENDER,'
new = '''FromEmailAddress=SENDER,
        ReplyToAddresses=[\"$REPLY_TO_ADDRESS\"],'''

if old in code:
    code = code.replace(old, new, 1)  # Only replace first occurrence (main send, not demo)
    with open('lambda_function.py', 'w') as f:
        f.write(code)
    print('Patched: added ReplyToAddresses to daily-brief send_email')
else:
    print('WARNING: Could not find FromEmailAddress=SENDER, — manual patch needed')
"
fi

# Re-zip and deploy
zip -r /tmp/daily_brief_patched.zip .
aws lambda update-function-code \
  --function-name "$DAILY_BRIEF_LAMBDA" \
  --zip-file fileb:///tmp/daily_brief_patched.zip \
  --region "$REGION" \
  --query '{FunctionName: FunctionName, CodeSize: CodeSize, LastModified: LastModified}' \
  --output table

# Cleanup
rm -rf /tmp/daily_brief_extract /tmp/daily_brief_current.zip /tmp/daily_brief_url.txt /tmp/daily_brief_patched.zip

echo ""
echo "=== Verify ==="
echo ""
echo "insight-email-parser:"
aws lambda get-function-configuration \
  --function-name "$INSIGHT_LAMBDA" \
  --region "$REGION" \
  --query '{Runtime: Runtime, MemorySize: MemorySize, Timeout: Timeout, LastModified: LastModified, Env: Environment.Variables}' \
  --output table

echo ""
echo "daily-brief Reply-To check:"
aws lambda get-function \
  --function-name "$DAILY_BRIEF_LAMBDA" \
  --region "$REGION" \
  --query 'Code.Location' \
  --output text > /tmp/db_check_url.txt
curl -s -o /tmp/db_check.zip "$(cat /tmp/db_check_url.txt)"
mkdir -p /tmp/db_check && cd /tmp/db_check && unzip -o /tmp/db_check.zip > /dev/null
grep -n "ReplyToAddresses" lambda_function.py && echo "Reply-To CONFIRMED" || echo "WARNING: Reply-To NOT found"
rm -rf /tmp/db_check /tmp/db_check.zip /tmp/db_check_url.txt

echo ""
echo "=========================================="
echo "DEPLOYMENT COMPLETE"
echo "=========================================="
echo ""
echo "NEXT STEPS:"
echo "  1. Run deploy_insight_email_pipeline.sh (SES rules + S3 notifications)"
echo "  2. Add DNS records in Cloudflare (MX, TXT, CNAME for aws.mattsusername.com)"
echo "  3. Wait for DNS propagation (~5-15 min)"
echo "  4. Test: send email to ${REPLY_TO_ADDRESS}"
