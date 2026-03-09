#!/bin/bash
# Feature #21 — Insight Email Parser
# SES inbound → S3 → Lambda → DynamoDB insights partition
# Allows replying to any Life Platform email to save insights
# v2.37.0

set -euo pipefail
REGION="us-west-2"
ACCOUNT_ID="205930651321"
LAMBDA_DIR="$HOME/Documents/Claude/life-platform/lambdas"
FUNCTION_NAME="insight-email-parser"
IAM_ROLE_NAME="lambda-insight-email-parser-role"
S3_BUCKET="matthew-life-platform"
S3_PREFIX="raw/inbound_email/"
DOMAIN="mattsusername.com"
RULE_SET_NAME="life-platform-inbound"
RECEIPT_RULE_NAME="insight-reply-rule"
REPLY_ADDRESS="insights@${DOMAIN}"

echo "═══════════════════════════════════════════════════════════"
echo "Feature #21 — Insight Email Parser"
echo "SES inbound → S3 → Lambda → DynamoDB insights"
echo "═══════════════════════════════════════════════════════════"

# ══════════════════════════════════════════════════════════════════════════════
# Step 1: Write the Lambda function
# ══════════════════════════════════════════════════════════════════════════════
echo ""
echo "Step 1: Writing insight_email_parser_lambda.py..."

cat > "$LAMBDA_DIR/insight_email_parser_lambda.py" << 'LAMBDA_EOF'
"""
Insight Email Parser Lambda — v1.0.0

Triggered by SES inbound email → S3 → Lambda.

When Matthew replies to any Life Platform email, this Lambda:
1. Reads the raw email from S3
2. Extracts the reply text (strips quoted original + signatures)
3. Saves the reply as a coaching insight in DynamoDB
4. Sends a confirmation email back

DynamoDB record:
  pk: USER#matthew#SOURCE#insights
  sk: INSIGHT#<ISO-timestamp>

Trigger: SES Receipt Rule → S3 → S3 Event Notification → this Lambda
"""

import json
import email
import re
import boto3
from datetime import datetime, timezone
from decimal import Decimal
from email import policy

dynamodb = boto3.resource("dynamodb", region_name="us-west-2")
table    = dynamodb.Table("life-platform")
s3       = boto3.client("s3", region_name="us-west-2")
ses      = boto3.client("sesv2", region_name="us-west-2")

S3_BUCKET = "matthew-life-platform"
SENDER    = "awsdev@mattsusername.com"
RECIPIENT = "awsdev@mattsusername.com"

# Allowed sender addresses (security: only process Matthew's emails)
ALLOWED_SENDERS = {
    "awsdev@mattsusername.com",
    # Add personal email addresses here
}


def extract_reply_text(email_body):
    """
    Extract just the reply text, removing quoted original, signatures, etc.
    Handles common email client patterns:
      - "On <date>, <sender> wrote:" (Gmail, Apple Mail)
      - "From: <sender>" (Outlook)
      - "-----Original Message-----"
      - ">" quoted lines
      - Signature delimiters ("--", "Sent from my iPhone")
    """
    if not email_body:
        return ""

    lines = email_body.strip().split("\n")
    reply_lines = []

    for line in lines:
        stripped = line.strip()

        # Stop at quoted original markers
        if re.match(r'^On .+ wrote:$', stripped):
            break
        if stripped.startswith("From:") and "@" in stripped:
            break
        if stripped == "-----Original Message-----":
            break
        if stripped.startswith(">"):
            break

        # Stop at signature markers
        if stripped == "--":
            break
        if stripped.startswith("Sent from my"):
            break
        if stripped.startswith("Get Outlook"):
            break

        reply_lines.append(line)

    text = "\n".join(reply_lines).strip()

    # Remove any "track this" / "save this" command prefix (case-insensitive)
    text = re.sub(r'^(track this|save this|insight|note)[:\s]*', '', text, flags=re.IGNORECASE).strip()

    return text


def save_insight(text, source_email_subject=""):
    """Save the insight to DynamoDB insights partition."""
    now = datetime.now(timezone.utc)
    insight_id = now.isoformat()
    date_saved = now.strftime("%Y-%m-%d")

    # Auto-detect tags from subject line
    tags = []
    if "anomaly" in source_email_subject.lower():
        tags.append("anomaly")
    if "daily brief" in source_email_subject.lower():
        tags.append("daily_brief")
    if "weekly" in source_email_subject.lower():
        tags.append("weekly_digest")
    if "monthly" in source_email_subject.lower():
        tags.append("monthly_digest")

    item = {
        "pk": "USER#matthew#SOURCE#insights",
        "sk": f"INSIGHT#{insight_id}",
        "insight_id": insight_id,
        "text": text,
        "date_saved": date_saved,
        "source": "email",
        "status": "open",
        "outcome_notes": "",
        "tags": tags,
        "email_subject": source_email_subject[:200] if source_email_subject else "",
    }

    item = json.loads(json.dumps(item), parse_float=Decimal)
    table.put_item(Item=item)

    return insight_id, date_saved


def send_confirmation(insight_text, insight_id):
    """Send a brief confirmation email."""
    preview = insight_text[:80] + ("..." if len(insight_text) > 80 else "")

    html = f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="margin:0;padding:0;background:#f4f4f8;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;">
  <div style="max-width:480px;margin:24px auto;background:#fff;border-radius:14px;overflow:hidden;box-shadow:0 2px 12px rgba(0,0,0,0.08);">
    <div style="background:#1a1a2e;padding:16px 24px;">
      <p style="color:#8892b0;font-size:11px;margin:0 0 2px;text-transform:uppercase;letter-spacing:1px;">Life Platform</p>
      <h1 style="color:#fff;font-size:15px;font-weight:700;margin:0;">✅ Insight Saved</h1>
    </div>
    <div style="padding:16px 24px;">
      <p style="font-size:13px;color:#374151;line-height:1.6;margin:0;background:#f8f8fc;padding:12px 14px;border-radius:8px;border-left:3px solid #10b981;">
        {preview}
      </p>
      <p style="font-size:11px;color:#9ca3af;margin:12px 0 0;">
        Status: open · Review via Claude Desktop → <code>get_insights</code>
      </p>
    </div>
  </div>
</body>
</html>"""

    ses.send_email(
        FromEmailAddress=SENDER,
        Destination={"ToAddresses": [RECIPIENT]},
        Content={"Simple": {
            "Subject": {"Data": f"✅ Insight saved: {preview[:50]}", "Charset": "UTF-8"},
            "Body":    {"Html": {"Data": html, "Charset": "UTF-8"}},
        }},
    )


def lambda_handler(event, context):
    """
    Triggered by S3 event when SES deposits a raw email.
    
    Event can come from:
    1. S3 Event Notification (has 'Records' with s3 info)
    2. SES direct invocation (has 'Records' with ses info)
    """
    print(f"[INFO] Insight Email Parser v1.0 triggered")

    for record in event.get("Records", []):
        # Handle S3 trigger
        s3_info = record.get("s3", {})
        bucket = s3_info.get("bucket", {}).get("name", S3_BUCKET)
        key = s3_info.get("object", {}).get("key", "")

        if not key:
            # Handle SES direct invocation
            ses_info = record.get("ses", {})
            mail = ses_info.get("mail", {})
            message_id = mail.get("messageId", "")
            if message_id:
                key = f"raw/inbound_email/{message_id}"
            else:
                print("[WARN] No S3 key or SES messageId found, skipping")
                continue

        print(f"[INFO] Processing: s3://{bucket}/{key}")

        # Read raw email from S3
        try:
            obj = s3.get_object(Bucket=bucket, Key=key)
            raw_email = obj["Body"].read().decode("utf-8", errors="replace")
        except Exception as e:
            print(f"[ERROR] Failed to read email from S3: {e}")
            continue

        # Parse email
        msg = email.message_from_string(raw_email, policy=policy.default)

        # Security: check sender
        from_addr = msg.get("From", "")
        sender_email = re.search(r'[\w.+-]+@[\w-]+\.[\w.]+', from_addr)
        sender = sender_email.group(0).lower() if sender_email else ""

        if sender not in ALLOWED_SENDERS:
            print(f"[WARN] Unauthorized sender: {sender}. Ignoring.")
            continue

        subject = msg.get("Subject", "")
        print(f"[INFO] From: {sender}, Subject: {subject}")

        # Extract text body
        body_text = ""
        if msg.is_multipart():
            for part in msg.walk():
                if part.get_content_type() == "text/plain":
                    body_text = part.get_content()
                    break
            # Fallback to HTML if no plain text
            if not body_text:
                for part in msg.walk():
                    if part.get_content_type() == "text/html":
                        html_content = part.get_content()
                        # Basic HTML stripping
                        body_text = re.sub(r'<[^>]+>', '', html_content)
                        break
        else:
            body_text = msg.get_content()

        # Extract reply text
        reply_text = extract_reply_text(body_text)

        if not reply_text or len(reply_text) < 5:
            print(f"[WARN] Reply text too short or empty: '{reply_text[:50]}'")
            continue

        print(f"[INFO] Extracted reply ({len(reply_text)} chars): {reply_text[:100]}...")

        # Save as insight
        insight_id, date_saved = save_insight(reply_text, source_email_subject=subject)
        print(f"[INFO] Insight saved: {insight_id}")

        # Send confirmation
        try:
            send_confirmation(reply_text, insight_id)
            print("[INFO] Confirmation email sent")
        except Exception as e:
            print(f"[WARN] Confirmation email failed: {e}")

    return {"statusCode": 200, "body": json.dumps({"status": "ok"})}
LAMBDA_EOF

echo "✅ insight_email_parser_lambda.py written"

# ══════════════════════════════════════════════════════════════════════════════
# Step 2: Create IAM role
# ══════════════════════════════════════════════════════════════════════════════
echo ""
echo "Step 2: Creating IAM role..."

# Check if role exists
if aws iam get-role --role-name "$IAM_ROLE_NAME" --region "$REGION" 2>/dev/null; then
    echo "  Role already exists, skipping creation."
else
    aws iam create-role \
        --role-name "$IAM_ROLE_NAME" \
        --assume-role-policy-document '{
            "Version": "2012-10-17",
            "Statement": [{
                "Effect": "Allow",
                "Principal": {"Service": "lambda.amazonaws.com"},
                "Action": "sts:AssumeRole"
            }]
        }' \
        --query "Role.Arn" --output text

    # Attach policies
    aws iam put-role-policy \
        --role-name "$IAM_ROLE_NAME" \
        --policy-name "insight-email-parser-policy" \
        --policy-document '{
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Effect": "Allow",
                    "Action": ["dynamodb:PutItem"],
                    "Resource": "arn:aws:dynamodb:us-west-2:'"$ACCOUNT_ID"':table/life-platform"
                },
                {
                    "Effect": "Allow",
                    "Action": ["s3:GetObject"],
                    "Resource": "arn:aws:s3:::'"$S3_BUCKET"'/raw/inbound_email/*"
                },
                {
                    "Effect": "Allow",
                    "Action": ["ses:SendEmail"],
                    "Resource": "arn:aws:ses:us-west-2:'"$ACCOUNT_ID"':identity/'"$DOMAIN"'"
                },
                {
                    "Effect": "Allow",
                    "Action": ["logs:CreateLogGroup","logs:CreateLogStream","logs:PutLogEvents"],
                    "Resource": "arn:aws:logs:us-west-2:'"$ACCOUNT_ID"':*"
                }
            ]
        }'

    echo "  Waiting for role propagation..."
    sleep 10
    echo "✅ IAM role created"
fi

ROLE_ARN="arn:aws:iam::${ACCOUNT_ID}:role/${IAM_ROLE_NAME}"

# ══════════════════════════════════════════════════════════════════════════════
# Step 3: Create and deploy Lambda
# ══════════════════════════════════════════════════════════════════════════════
echo ""
echo "Step 3: Packaging and deploying Lambda..."

TMPDIR=$(mktemp -d)
cp "$LAMBDA_DIR/insight_email_parser_lambda.py" "$TMPDIR/lambda_function.py"
cd "$TMPDIR"
zip -r insight_email_parser.zip lambda_function.py
cp insight_email_parser.zip "$LAMBDA_DIR/insight_email_parser_lambda.zip"

# Check if function exists
if aws lambda get-function --function-name "$FUNCTION_NAME" --region "$REGION" 2>/dev/null; then
    echo "  Function exists, updating code..."
    aws lambda update-function-code \
        --function-name "$FUNCTION_NAME" \
        --zip-file "fileb://insight_email_parser.zip" \
        --region "$REGION" \
        --query "[FunctionName,CodeSize]" --output table
else
    echo "  Creating new function..."
    aws lambda create-function \
        --function-name "$FUNCTION_NAME" \
        --runtime python3.12 \
        --handler lambda_function.lambda_handler \
        --role "$ROLE_ARN" \
        --zip-file "fileb://insight_email_parser.zip" \
        --timeout 30 \
        --memory-size 128 \
        --region "$REGION" \
        --dead-letter-config "TargetArn=arn:aws:sqs:us-west-2:${ACCOUNT_ID}:life-platform-ingestion-dlq" \
        --query "[FunctionName,CodeSize]" --output table
fi

echo ""
echo "  Waiting for function to be active..."
aws lambda wait function-active-v2 \
    --function-name "$FUNCTION_NAME" \
    --region "$REGION" 2>/dev/null || sleep 5

echo "✅ Lambda deployed"

# ══════════════════════════════════════════════════════════════════════════════
# Step 4: Add S3 trigger permission
# ══════════════════════════════════════════════════════════════════════════════
echo ""
echo "Step 4: Adding S3 invoke permission..."

aws lambda add-permission \
    --function-name "$FUNCTION_NAME" \
    --statement-id "s3-inbound-email-trigger" \
    --action "lambda:InvokeFunction" \
    --principal "s3.amazonaws.com" \
    --source-arn "arn:aws:s3:::${S3_BUCKET}" \
    --source-account "$ACCOUNT_ID" \
    --region "$REGION" 2>/dev/null || echo "  Permission already exists."

# ══════════════════════════════════════════════════════════════════════════════
# Step 5: Add S3 Event Notification
# ══════════════════════════════════════════════════════════════════════════════
echo ""
echo "Step 5: Setting up S3 event notification..."

LAMBDA_ARN=$(aws lambda get-function --function-name "$FUNCTION_NAME" --region "$REGION" --query "Configuration.FunctionArn" --output text)

# Get existing notification config and add new one
python3 << PYEOF
import json
import subprocess

bucket = "$S3_BUCKET"
region = "$REGION"
lambda_arn = "$LAMBDA_ARN"
prefix = "raw/inbound_email/"

# Get current config
result = subprocess.run(
    ["aws", "s3api", "get-bucket-notification-configuration", "--bucket", bucket, "--region", region],
    capture_output=True, text=True
)

if result.returncode == 0 and result.stdout.strip():
    config = json.loads(result.stdout)
else:
    config = {}

# Check if our notification already exists
lambda_configs = config.get("LambdaFunctionConfigurations", [])
already_exists = any(
    lc.get("LambdaFunctionArn") == lambda_arn and
    any(r.get("Name") == "prefix" and r.get("Value") == prefix
        for r in lc.get("Filter", {}).get("Key", {}).get("FilterRules", []))
    for lc in lambda_configs
)

if already_exists:
    print("  S3 notification already configured.")
else:
    lambda_configs.append({
        "Id": "InboundEmailToInsightParser",
        "LambdaFunctionArn": lambda_arn,
        "Events": ["s3:ObjectCreated:*"],
        "Filter": {
            "Key": {
                "FilterRules": [
                    {"Name": "prefix", "Value": prefix}
                ]
            }
        }
    })
    config["LambdaFunctionConfigurations"] = lambda_configs

    # Write config
    with open("/tmp/s3_notification_config.json", "w") as f:
        json.dump(config, f)

    result = subprocess.run(
        ["aws", "s3api", "put-bucket-notification-configuration",
         "--bucket", bucket, "--notification-configuration", "file:///tmp/s3_notification_config.json",
         "--region", region],
        capture_output=True, text=True
    )
    if result.returncode == 0:
        print("  ✅ S3 event notification configured")
    else:
        print(f"  ⚠️ S3 notification failed: {result.stderr}")
        print("  You may need to configure this manually.")
PYEOF

# ══════════════════════════════════════════════════════════════════════════════
# Step 6: SES Receipt Rule Setup
# ══════════════════════════════════════════════════════════════════════════════
echo ""
echo "Step 6: Setting up SES receipt rule..."
echo ""
echo "⚠️  SES INBOUND EMAIL REQUIRES MANUAL DNS CONFIGURATION"
echo ""
echo "To complete Feature #21, you need to:"
echo ""
echo "1. Add an MX record for ${DOMAIN}:"
echo "   MX 10 inbound-smtp.${REGION}.amazonaws.com"
echo "   (Or for a subdomain like reply.${DOMAIN})"
echo ""
echo "2. Create SES Receipt Rule Set (run once):"
echo "   aws ses create-receipt-rule-set --rule-set-name ${RULE_SET_NAME} --region ${REGION}"
echo "   aws ses set-active-receipt-rule-set --rule-set-name ${RULE_SET_NAME} --region ${REGION}"
echo ""
echo "3. Create Receipt Rule:"
echo "   aws ses create-receipt-rule \\"
echo "     --rule-set-name ${RULE_SET_NAME} \\"
echo "     --rule '{\"Name\":\"${RECEIPT_RULE_NAME}\",\"Enabled\":true,\"Recipients\":[\"${REPLY_ADDRESS}\"],\"Actions\":[{\"S3Action\":{\"BucketName\":\"${S3_BUCKET}\",\"ObjectKeyPrefix\":\"raw/inbound_email/\"}}]}' \\"
echo "     --region ${REGION}"
echo ""
echo "4. Add S3 bucket policy for SES:"
echo "   aws s3api put-bucket-policy --bucket ${S3_BUCKET} --policy '{...SES write...}'"
echo ""
echo "5. Update Daily Brief emails to include reply-to: ${REPLY_ADDRESS}"
echo ""

# ══════════════════════════════════════════════════════════════════════════════
# Step 7: CloudWatch Alarm
# ══════════════════════════════════════════════════════════════════════════════
echo ""
echo "Step 7: Creating CloudWatch alarm..."
aws cloudwatch put-metric-alarm \
    --alarm-name "${FUNCTION_NAME}-errors" \
    --alarm-description "Insight email parser Lambda errors" \
    --namespace "AWS/Lambda" \
    --metric-name "Errors" \
    --dimensions "Name=FunctionName,Value=${FUNCTION_NAME}" \
    --statistic "Sum" \
    --period 86400 \
    --evaluation-periods 1 \
    --threshold 1 \
    --comparison-operator "GreaterThanOrEqualToThreshold" \
    --treat-missing-data "notBreaching" \
    --alarm-actions "arn:aws:sns:${REGION}:${ACCOUNT_ID}:life-platform-alerts" \
    --region "$REGION"

echo "✅ CloudWatch alarm created"

echo ""
echo "═══════════════════════════════════════════════════════════"
echo "✅ Feature #21 — Insight Email Parser deployed!"
echo ""
echo "Lambda: ${FUNCTION_NAME} (128 MB, 30s, Python 3.12)"
echo "S3 trigger: s3://${S3_BUCKET}/raw/inbound_email/ → Lambda"
echo "DynamoDB: USER#matthew#SOURCE#insights (source: 'email')"
echo ""
echo "⚠️  REMAINING: DNS MX record + SES Receipt Rule (see above)"
echo "    Without these, emails won't reach the S3 trigger."
echo "═══════════════════════════════════════════════════════════"

rm -rf "$TMPDIR"
