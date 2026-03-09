#!/usr/bin/env bash
# deploy/deploy_p3_lambdas.sh
# Deploy all P3 new Lambdas: data-reconciliation + pip-audit
# Also redeploys strava + macrofactor to pick up REL-3 safe_put_item changes.
#
# Usage: bash deploy/deploy_p3_lambdas.sh
# NOTE: Run from project root. Requires AWS CLI + sufficient IAM permissions.
set -euo pipefail

REGION="us-west-2"
ACCOUNT="205930651321"
ROLE_ARN_RECON="arn:aws:iam::${ACCOUNT}:role/lambda-data-reconciliation-role"
ROLE_ARN_AUDIT="arn:aws:iam::${ACCOUNT}:role/lambda-pip-audit-role"
BUCKET="matthew-life-platform"
LAMBDAS_DIR="lambdas"
DEPLOY_DIR="deploy/zips"
mkdir -p "$DEPLOY_DIR"

# ── Shared modules bundled into every zip ────────────────────────────────────
SHARED_MODULES=(
  "platform_logger.py"
  "ingestion_validator.py"
  "ai_output_validator.py"
  "item_size_guard.py"
  "board_loader.py"
  "retry_utils.py"
)

# ── Helper: build zip for a Lambda ──────────────────────────────────────────
build_zip() {
  local handler_file="$1"     # e.g. data_reconciliation_lambda.py
  local zip_name="$2"         # e.g. data-reconciliation.zip
  local extra_files=("${@:3}") # optional extra modules

  echo "→ Building $zip_name from $handler_file"
  local tmp_dir
  tmp_dir=$(mktemp -d)

  # Copy handler
  cp "$LAMBDAS_DIR/$handler_file" "$tmp_dir/"

  # Copy shared modules
  for mod in "${SHARED_MODULES[@]}"; do
    if [ -f "$LAMBDAS_DIR/$mod" ]; then
      cp "$LAMBDAS_DIR/$mod" "$tmp_dir/"
    fi
  done

  # Copy any extra files (guard against empty array with -u nounset)
  for extra in "${extra_files[@]+"${extra_files[@]}"}" ; do
    if [ -f "$LAMBDAS_DIR/$extra" ]; then
      cp "$LAMBDAS_DIR/$extra" "$tmp_dir/"
    fi
  done

  # Build zip
  (cd "$tmp_dir" && zip -qr "$OLDPWD/$DEPLOY_DIR/$zip_name" .)
  rm -rf "$tmp_dir"
  echo "  ✓ $DEPLOY_DIR/$zip_name ($(du -sh "$DEPLOY_DIR/$zip_name" | cut -f1))"
}

# ── Helper: create or update Lambda function ────────────────────────────────
deploy_lambda() {
  local function_name="$1"
  local zip_file="$2"
  local handler="$3"           # e.g. data_reconciliation_lambda.lambda_handler
  local description="$4"
  local role_arn="$5"          # dedicated IAM role ARN
  local timeout="${6:-60}"
  local memory="${7:-256}"

  echo ""
  echo "── Deploying $function_name ────────────────────────────────────────"

  # Check if function exists
  if aws lambda get-function --function-name "$function_name" --region "$REGION" &>/dev/null; then
    echo "  Updating existing Lambda..."
    aws lambda update-function-code \
      --function-name "$function_name" \
      --zip-file "fileb://$DEPLOY_DIR/$zip_file" \
      --region "$REGION" \
      --output text \
      --query 'CodeSize' | xargs -I{} echo "  Code size: {} bytes"

    sleep 5  # avoid ResourceConflictException on rapid sequential updates

    aws lambda update-function-configuration \
      --function-name "$function_name" \
      --handler "$handler" \
      --description "$description" \
      --timeout "$timeout" \
      --memory-size "$memory" \
      --region "$REGION" \
      --output text \
      --query 'FunctionName' | xargs -I{} echo "  Config updated: {}"
  else
    echo "  Creating new Lambda..."
    aws lambda create-function \
      --function-name "$function_name" \
      --runtime python3.12 \
      --role "${role_arn}" \
      --handler "$handler" \
      --description "$description" \
      --timeout "$timeout" \
      --memory-size "$memory" \
      --zip-file "fileb://$DEPLOY_DIR/$zip_file" \
      --region "$REGION" \
      --environment "Variables={TABLE_NAME=life-platform,S3_BUCKET=matthew-life-platform,USER_ID=matthew,EMAIL_RECIPIENT=awsdev@mattsusername.com,EMAIL_SENDER=awsdev@mattsusername.com,AWS_REGION_OVERRIDE=us-west-2}" \
      --output text \
      --query 'FunctionName' | xargs -I{} echo "  Created: {}"
  fi

  echo "  ✓ $function_name deployed"
}

echo "════════════════════════════════════════════════════════════"
echo "  Life Platform P3 Lambda Deploy"
echo "════════════════════════════════════════════════════════════"
echo ""

# ── 1. data-reconciliation (DATA-3) ─────────────────────────────────────────
build_zip "data_reconciliation_lambda.py" "data-reconciliation.zip"
deploy_lambda \
  "life-platform-data-reconciliation" \
  "data-reconciliation.zip" \
  "data_reconciliation_lambda.lambda_handler" \
  "DATA-3: Weekly source coverage reconciliation. Checks 19 sources x 7 days. Emails gap report." \
  "$ROLE_ARN_RECON" \
  120 256

# ── 2. pip-audit (SEC-5) ─────────────────────────────────────────────────────
build_zip "pip_audit_lambda.py" "pip-audit.zip"
deploy_lambda \
  "life-platform-pip-audit" \
  "pip-audit.zip" \
  "pip_audit_lambda.lambda_handler" \
  "SEC-5: Monthly pip-audit dependency vulnerability scan. Installs pip-audit at runtime." \
  "$ROLE_ARN_AUDIT" \
  300 512

# ── 3. strava (REL-3: safe_put_item now called) ──────────────────────────────
echo ""
echo "── Redeploying strava (REL-3 safe_put_item) ────────────────────────────"
build_zip "strava_lambda.py" "strava-rel3.zip"
aws lambda update-function-code \
  --function-name "strava-data-ingestion" \
  --zip-file "fileb://$DEPLOY_DIR/strava-rel3.zip" \
  --region "$REGION" \
  --output text --query 'CodeSize' | xargs -I{} echo "  Code size: {} bytes"
echo "  ✓ strava-data-ingestion redeployed"

sleep 5

# ── 4. macrofactor (REL-3: safe_put_item now called) ─────────────────────────
echo ""
echo "── Redeploying macrofactor (REL-3 safe_put_item) ──────────────────────"
build_zip "macrofactor_lambda.py" "macrofactor-rel3.zip"
aws lambda update-function-code \
  --function-name "macrofactor-data-ingestion" \
  --zip-file "fileb://$DEPLOY_DIR/macrofactor-rel3.zip" \
  --region "$REGION" \
  --output text --query 'CodeSize' | xargs -I{} echo "  Code size: {} bytes"
echo "  ✓ macrofactor-data-ingestion redeployed"

echo ""
echo "════════════════════════════════════════════════════════════"
echo "  All P3 Lambdas deployed. Next: set up EventBridge schedules."
echo "  Run: bash deploy/setup_p3_schedules.sh"
echo "════════════════════════════════════════════════════════════"
