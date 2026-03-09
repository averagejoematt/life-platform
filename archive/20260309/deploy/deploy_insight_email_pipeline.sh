#!/bin/bash
# deploy_insight_email_pipeline.sh — Complete SES inbound email pipeline for insight-email-parser
# Version: v2.39.2
# 
# Uses subdomain aws.mattsusername.com to avoid conflicting with SimpleLogin on root domain.
#
# What this does:
#   0. Verifies aws.mattsusername.com subdomain in SES
#   1. Creates SES receipt rule set
#   2. Creates receipt rule: insight@aws.mattsusername.com -> S3 raw/inbound_email/
#   3. Sets it as active rule set
#   4. Adds Lambda invoke permission for S3
#   5. Updates S3 notification config (preserving existing MacroFactor trigger)
#
# BEFORE running this script, add this DNS record in Cloudflare for mattsusername.com:
#   Type: MX    | Name: aws | Value: inbound-smtp.us-west-2.amazonaws.com | Priority: 10 | Proxy: DNS only
#
# After running, the script will output DKIM CNAME records to also add if subdomain needs separate verification.

set -euo pipefail
REGION="us-west-2"
ACCOUNT_ID="205930651321"
BUCKET="matthew-life-platform"
LAMBDA_NAME="insight-email-parser"
RULE_SET_NAME="life-platform-inbound"
RULE_NAME="insight-capture"
S3_PREFIX="raw/inbound_email/"
SUBDOMAIN="aws.mattsusername.com"
RECIPIENT="insight@${SUBDOMAIN}"

echo "=== Step 0: Verify subdomain in SES ==="
echo "Checking if ${SUBDOMAIN} is already verified..."
VERIFIED=$(aws ses get-identity-verification-attributes \
  --identities "$SUBDOMAIN" \
  --region "$REGION" \
  --query "VerificationAttributes.\"${SUBDOMAIN}\".VerificationStatus" \
  --output text 2>/dev/null || echo "NotFound")

if [ "$VERIFIED" = "Success" ]; then
  echo "${SUBDOMAIN} already verified in SES"
else
  echo "Verifying ${SUBDOMAIN} in SES..."
  VERIFY_TOKEN=$(aws ses verify-domain-identity \
    --domain "$SUBDOMAIN" \
    --region "$REGION" \
    --query "VerificationToken" \
    --output text)
  echo ""
  echo ">>> ADD THIS DNS RECORD in Cloudflare (then re-run or wait for propagation):"
  echo "  Type: TXT"
  echo "  Name: _amazonses.aws"
  echo "  Value: ${VERIFY_TOKEN}"
  echo ""
  echo "Also set up DKIM for the subdomain:"
  DKIM_TOKENS=$(aws ses verify-domain-dkim \
    --domain "$SUBDOMAIN" \
    --region "$REGION" \
    --query "DkimTokens" \
    --output text)
  for TOKEN in $DKIM_TOKENS; do
    echo "  Type: CNAME | Name: ${TOKEN}._domainkey.aws | Value: ${TOKEN}.dkim.amazonses.com"
  done
  echo ""
  echo "Waiting 10s then checking verification status..."
  sleep 10
  RECHECK=$(aws ses get-identity-verification-attributes \
    --identities "$SUBDOMAIN" \
    --region "$REGION" \
    --query "VerificationAttributes.\"${SUBDOMAIN}\".VerificationStatus" \
    --output text 2>/dev/null || echo "Pending")
  echo "Verification status: ${RECHECK}"
  if [ "$RECHECK" != "Success" ]; then
    echo ">>> Domain not yet verified. Add the TXT record above, wait for DNS propagation, then re-run."
    echo "    (Script will continue -- SES rules can be created before verification completes)"
  fi
fi

echo ""
echo "=== Step 1: Create SES receipt rule set ==="
aws ses create-receipt-rule-set \
  --rule-set-name "$RULE_SET_NAME" \
  --region "$REGION" 2>/dev/null && echo "Created rule set: $RULE_SET_NAME" || echo "Rule set already exists"

echo ""
echo "=== Step 2: Add S3 bucket policy for SES write access ==="
# SES needs permission to write to S3
cat > /tmp/ses_bucket_policy_addition.json << 'POLICY'
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "AllowSESPuts",
      "Effect": "Allow",
      "Principal": {
        "Service": "ses.amazonaws.com"
      },
      "Action": "s3:PutObject",
      "Resource": "arn:aws:s3:::matthew-life-platform/raw/inbound_email/*",
      "Condition": {
        "StringEquals": {
          "AWS:SourceAccount": "205930651321"
        }
      }
    }
  ]
}
POLICY

# Get existing bucket policy and merge
echo "Fetching existing bucket policy..."
EXISTING_POLICY=$(aws s3api get-bucket-policy --bucket "$BUCKET" --region "$REGION" --query Policy --output text 2>/dev/null || echo "")

if [ -z "$EXISTING_POLICY" ]; then
  echo "No existing bucket policy -- setting SES policy directly"
  aws s3api put-bucket-policy \
    --bucket "$BUCKET" \
    --policy file:///tmp/ses_bucket_policy_addition.json \
    --region "$REGION"
else
  echo "Existing policy found -- merging SES statement"
  python3 -c "
import json, sys
existing = json.loads('''$EXISTING_POLICY''')
ses_stmt = {
    'Sid': 'AllowSESPuts',
    'Effect': 'Allow',
    'Principal': {'Service': 'ses.amazonaws.com'},
    'Action': 's3:PutObject',
    'Resource': 'arn:aws:s3:::matthew-life-platform/raw/inbound_email/*',
    'Condition': {'StringEquals': {'AWS:SourceAccount': '205930651321'}}
}
# Remove any existing SES statement to avoid duplicates
existing['Statement'] = [s for s in existing['Statement'] if s.get('Sid') != 'AllowSESPuts']
existing['Statement'].append(ses_stmt)
with open('/tmp/merged_bucket_policy.json', 'w') as f:
    json.dump(existing, f)
print('Merged policy written')
"
  aws s3api put-bucket-policy \
    --bucket "$BUCKET" \
    --policy file:///tmp/merged_bucket_policy.json \
    --region "$REGION"
fi
echo "Bucket policy updated"

echo ""
echo "=== Step 3: Create receipt rule ==="
aws ses create-receipt-rule \
  --rule-set-name "$RULE_SET_NAME" \
  --region "$REGION" \
  --rule '{
    "Name": "'"$RULE_NAME"'",
    "Enabled": true,
    "TlsPolicy": "Optional",
    "Recipients": ["'"$RECIPIENT"'"],
    "Actions": [
      {
        "S3Action": {
          "BucketName": "'"$BUCKET"'",
          "ObjectKeyPrefix": "'"$S3_PREFIX"'"
        }
      }
    ],
    "ScanEnabled": true
  }' 2>/dev/null && echo "Created receipt rule: $RULE_NAME" || echo "Receipt rule already exists"

echo ""
echo "=== Step 4: Set as active receipt rule set ==="
aws ses set-active-receipt-rule-set \
  --rule-set-name "$RULE_SET_NAME" \
  --region "$REGION"
echo "Active rule set: $RULE_SET_NAME"

echo ""
echo "=== Step 5: Add Lambda invoke permission for S3 ==="
aws lambda add-permission \
  --function-name "$LAMBDA_NAME" \
  --statement-id "s3-inbound-email-trigger" \
  --action "lambda:InvokeFunction" \
  --principal "s3.amazonaws.com" \
  --source-arn "arn:aws:s3:::$BUCKET" \
  --source-account "$ACCOUNT_ID" \
  --region "$REGION" 2>/dev/null && echo "Lambda permission added" || echo "Permission already exists"

echo ""
echo "=== Step 6: Update S3 notification configuration ==="
# CRITICAL: Must include ALL existing notifications or they get deleted
cat > /tmp/s3_notification_config.json << 'NOTIF'
{
  "LambdaFunctionConfigurations": [
    {
      "Id": "MacroFactorCSVIngest",
      "LambdaFunctionArn": "arn:aws:lambda:us-west-2:205930651321:function:macrofactor-data-ingestion",
      "Events": ["s3:ObjectCreated:*"],
      "Filter": {
        "Key": {
          "FilterRules": [
            {"Name": "Prefix", "Value": "uploads/macrofactor/"},
            {"Name": "Suffix", "Value": ".csv"}
          ]
        }
      }
    },
    {
      "Id": "InboundEmailInsightParser",
      "LambdaFunctionArn": "arn:aws:lambda:us-west-2:205930651321:function:insight-email-parser",
      "Events": ["s3:ObjectCreated:*"],
      "Filter": {
        "Key": {
          "FilterRules": [
            {"Name": "Prefix", "Value": "raw/inbound_email/"}
          ]
        }
      }
    }
  ]
}
NOTIF

aws s3api put-bucket-notification-configuration \
  --bucket "$BUCKET" \
  --notification-configuration file:///tmp/s3_notification_config.json \
  --region "$REGION"
echo "S3 notifications updated (preserved MacroFactor + added inbound email)"

echo ""
echo "=== Step 7: Verify ==="
echo "Receipt rule sets:"
aws ses list-receipt-rule-sets --region "$REGION" --query "RuleSets[].Name" --output text
echo ""
echo "Active rule set:"
aws ses describe-active-receipt-rule-set --region "$REGION" --query "Metadata.Name" --output text
echo ""
echo "Receipt rules:"
aws ses describe-receipt-rule-set --rule-set-name "$RULE_SET_NAME" --region "$REGION" --query "Rules[].{Name:Name,Enabled:Enabled,Recipients:Recipients}" --output table
echo ""
echo "S3 notifications:"
aws s3api get-bucket-notification-configuration --bucket "$BUCKET" --region "$REGION" --query "LambdaFunctionConfigurations[].{Id:Id,Prefix:Filter.Key.FilterRules[0].Value}" --output table
echo ""
echo "Lambda permissions:"
aws lambda get-policy --function-name "$LAMBDA_NAME" --region "$REGION" --query "Policy" --output text 2>/dev/null | python3 -c "import sys,json; p=json.loads(sys.stdin.read()); [print(f'  {s[\"Sid\"]}: {s[\"Principal\"][\"Service\"] if isinstance(s[\"Principal\"],dict) else s[\"Principal\"]}') for s in p['Statement']]" || echo "  No resource policy"

echo ""
echo "=========================================="
echo "AWS-SIDE SETUP COMPLETE"
echo "=========================================="
echo ""
echo "DNS RECORDS NEEDED in Cloudflare (if not already added):"
echo ""
echo "  1. MX Record (routes email to SES):"
echo "     Type: MX  |  Name: aws  |  Value: inbound-smtp.us-west-2.amazonaws.com  |  Priority: 10  |  Proxy: DNS only"
echo ""
echo "  2. TXT Record (SES domain verification) -- see Step 0 output above if needed"
echo "  3. CNAME Records (DKIM) -- see Step 0 output above if needed"
echo ""
echo "Your SimpleLogin setup on the root domain is NOT affected."
echo "Only ${RECIPIENT} routes to SES."
echo ""
echo "Test after DNS propagation:"
echo "  Send an email to ${RECIPIENT} with some test content"
echo "  Check Lambda logs: aws logs tail /aws/lambda/insight-email-parser --region us-west-2 --since 5m"
echo "  Check S3: aws s3 ls s3://matthew-life-platform/raw/inbound_email/ --region us-west-2"
echo "  Check DynamoDB: aws dynamodb query --table-name life-platform --key-condition-expression 'pk = :pk' --expression-attribute-values '{\":pk\":{\"S\":\"USER#matthew#SOURCE#insights\"}}' --region us-west-2 --query 'Items[0].text'"
