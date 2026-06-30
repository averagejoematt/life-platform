#!/usr/bin/env bash
#
# deploy_reading_gsis.sh — additively add the two reading GSIs to the `life-platform`
# DynamoDB table (ADR-097, Mind pillar Phase A). RUN THIS YOURSELF; Claude does not
# execute deploy scripts.
#
# WHY a CLI script and not CDK: the `life-platform` table is NOT CDK-managed — CDK
# only holds a read-only `from_table_name` lookup (core_stack.py). GSIs therefore
# cannot be added through a CDK construct; they are added with `update-table`.
#
# Additive + migration-safe: adding a GSI never drops data and runs as an online
# backfill (the table stays readable/writable throughout). DynamoDB allows only ONE
# GSI add per UpdateTable, so this does GSI1 then GSI2, each waiting for ACTIVE.
#
#   GSI1 — recall due (SPARSE): GSI1PK="RECALL_DUE", GSI1SK=<nextDue iso>. Only active
#          RECALL# items carry these attrs, so the index stays tiny. Sweep: GSI1SK<=now.
#   GSI2 — reading state/time:  GSI2PK="READING_STATUS#<status>" | "READING_SESSION",
#          GSI2SK=<iso>. Serves current-reading, queue, and history-by-date.
#
# Idempotent: an already-present index is skipped. Safe to re-run.
set -euo pipefail

REGION="${AWS_REGION:-us-west-2}"
TABLE="${TABLE_NAME:-life-platform}"

echo "▶ reading GSIs on table=$TABLE region=$REGION"

# On-demand vs provisioned — GSIs must match. Detect so the update is correct.
BILLING=$(aws dynamodb describe-table --table-name "$TABLE" --region "$REGION" \
  --query 'Table.BillingModeSummary.BillingMode' --output text 2>/dev/null || echo "PROVISIONED")
echo "  billing mode: $BILLING"

index_exists() {
  aws dynamodb describe-table --table-name "$TABLE" --region "$REGION" \
    --query "Table.GlobalSecondaryIndexes[?IndexName=='$1'] | [0].IndexName" --output text 2>/dev/null | grep -qx "$1"
}

wait_active() {
  echo "  ⏳ waiting for table + index '$1' to be ACTIVE (online backfill)…"
  while true; do
    TBL=$(aws dynamodb describe-table --table-name "$TABLE" --region "$REGION" --query 'Table.TableStatus' --output text)
    IDX=$(aws dynamodb describe-table --table-name "$TABLE" --region "$REGION" \
      --query "Table.GlobalSecondaryIndexes[?IndexName=='$1'] | [0].IndexStatus" --output text 2>/dev/null || echo "MISSING")
    echo "    table=$TBL index=$IDX"
    [ "$TBL" = "ACTIVE" ] && [ "$IDX" = "ACTIVE" ] && break
    sleep 15
  done
  echo "  ✓ '$1' ACTIVE"
}

add_gsi() {
  local NAME="$1" PK="$2" SK="$3"
  if index_exists "$NAME"; then
    echo "  ✓ $NAME already exists — skipping"
    return 0
  fi
  echo "  + creating $NAME ($PK / $SK, projection ALL)…"
  local ATTRS GSI_JSON
  ATTRS="[{\"AttributeName\":\"$PK\",\"AttributeType\":\"S\"},{\"AttributeName\":\"$SK\",\"AttributeType\":\"S\"}]"
  if [ "$BILLING" = "PAY_PER_REQUEST" ]; then
    GSI_JSON="[{\"Create\":{\"IndexName\":\"$NAME\",\"KeySchema\":[{\"AttributeName\":\"$PK\",\"KeyType\":\"HASH\"},{\"AttributeName\":\"$SK\",\"KeyType\":\"RANGE\"}],\"Projection\":{\"ProjectionType\":\"ALL\"}}}]"
  else
    GSI_JSON="[{\"Create\":{\"IndexName\":\"$NAME\",\"KeySchema\":[{\"AttributeName\":\"$PK\",\"KeyType\":\"HASH\"},{\"AttributeName\":\"$SK\",\"KeyType\":\"RANGE\"}],\"Projection\":{\"ProjectionType\":\"ALL\"},\"ProvisionedThroughput\":{\"ReadCapacityUnits\":5,\"WriteCapacityUnits\":5}}}]"
  fi
  aws dynamodb update-table --table-name "$TABLE" --region "$REGION" \
    --attribute-definitions "$ATTRS" \
    --global-secondary-index-updates "$GSI_JSON"
  wait_active "$NAME"
}

add_gsi "GSI1" "GSI1PK" "GSI1SK"
add_gsi "GSI2" "GSI2PK" "GSI2SK"

echo "✅ reading GSIs ready. Verify:"
echo "   aws dynamodb describe-table --table-name $TABLE --region $REGION --query 'Table.GlobalSecondaryIndexes[].{Name:IndexName,Status:IndexStatus}'"
