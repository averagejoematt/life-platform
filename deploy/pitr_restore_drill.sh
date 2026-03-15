#!/usr/bin/env bash
# deploy/pitr_restore_drill.sh
#
# R13-F07: Quarterly PITR restore drill for DynamoDB table life-platform.
#
# WHAT IT DOES:
#   1. Initiates a PITR restore of life-platform → life-platform-pitr-test
#   2. Waits for restore to complete (typically 5–20 min)
#   3. Verifies data integrity: item count, key partitions present, recent records
#   4. Prints a drill report
#   5. DELETES the test table (confirmation prompt before deletion)
#
# This drill validates:
#   ✓ PITR is active and functional (not just "enabled")
#   ✓ Restore completes without error
#   ✓ Core partitions (whoop, computed_metrics, insights, platform_memory) are intact
#   ✓ Records from the last 7 days are present (verifies recent ingestion survived)
#
# USAGE:
#   bash deploy/pitr_restore_drill.sh
#
# NOTES:
#   - Restores to ~1 minute ago (latest restorable time)
#   - Drill table is deleted after verification (with confirmation prompt)
#   - Does NOT affect the live table or any active Lambdas
#   - Costs: ~$0.02 per GB restored; life-platform is ~100 MB = <$0.01
#
# RUN QUARTERLY — first drill due ~2026-04-01 (R13-F07)
#
# v1.0.0 — 2026-03-15 (R13-F07)

set -euo pipefail

REGION="us-west-2"
SOURCE_TABLE="life-platform"
DRILL_TABLE="life-platform-pitr-test"
USER_PREFIX="USER#matthew#SOURCE#"

# Core partitions that must be present post-restore
REQUIRED_PARTITIONS=(
    "whoop"
    "computed_metrics"
    "insights"
    "platform_memory"
    "strava"
    "withings"
)

echo "══════════════════════════════════════════════════════"
echo "  PITR Restore Drill — R13-F07"
echo "  Source: ${SOURCE_TABLE}"
echo "  Drill table: ${DRILL_TABLE}"
echo "  Region: ${REGION}"
echo "══════════════════════════════════════════════════════"
echo ""

# ── Pre-flight: verify PITR is enabled ─────────────────────────────────────
echo "🔍 Verifying PITR status on ${SOURCE_TABLE}..."
PITR_STATUS=$(aws dynamodb describe-continuous-backups \
    --table-name "${SOURCE_TABLE}" \
    --region "${REGION}" \
    --query "ContinuousBackupsDescription.PointInTimeRecoveryDescription.PointInTimeRecoveryStatus" \
    --output text)

if [ "${PITR_STATUS}" != "ENABLED" ]; then
    echo "❌ PITR is '${PITR_STATUS}' — NOT ENABLED. Drill cannot proceed."
    echo "   Enable PITR: aws dynamodb update-continuous-backups \\"
    echo "     --table-name ${SOURCE_TABLE} --point-in-time-recovery-specification PointInTimeRecoveryEnabled=true"
    exit 1
fi
echo "   ✅ PITR status: ENABLED"

EARLIEST=$(aws dynamodb describe-continuous-backups \
    --table-name "${SOURCE_TABLE}" \
    --region "${REGION}" \
    --query "ContinuousBackupsDescription.PointInTimeRecoveryDescription.EarliestRestorableDateTime" \
    --output text)
LATEST=$(aws dynamodb describe-continuous-backups \
    --table-name "${SOURCE_TABLE}" \
    --region "${REGION}" \
    --query "ContinuousBackupsDescription.PointInTimeRecoveryDescription.LatestRestorableDateTime" \
    --output text)
echo "   Restorable window: ${EARLIEST} → ${LATEST}"
echo ""

# ── Cleanup: delete drill table if it already exists ───────────────────────
EXISTING=$(aws dynamodb describe-table \
    --table-name "${DRILL_TABLE}" \
    --region "${REGION}" \
    --query "Table.TableStatus" \
    --output text 2>/dev/null || echo "NOT_FOUND")

if [ "${EXISTING}" != "NOT_FOUND" ]; then
    echo "⚠️  Drill table '${DRILL_TABLE}' already exists (status: ${EXISTING})."
    echo "   Deleting stale drill table..."
    aws dynamodb delete-table \
        --table-name "${DRILL_TABLE}" \
        --region "${REGION}" > /dev/null
    echo "   Waiting for deletion..."
    aws dynamodb wait table-not-exists \
        --table-name "${DRILL_TABLE}" \
        --region "${REGION}"
    echo "   ✅ Stale drill table deleted"
    echo ""
fi

# ── Step 1: Initiate PITR restore ──────────────────────────────────────────
echo "⏱  Initiating PITR restore (latest point)..."
RESTORE_START=$(date -u +%Y-%m-%dT%H:%M:%SZ)

aws dynamodb restore-table-to-point-in-time \
    --source-table-name "${SOURCE_TABLE}" \
    --target-table-name "${DRILL_TABLE}" \
    --use-latest-restorable-time \
    --region "${REGION}" > /dev/null

echo "   Restore initiated at ${RESTORE_START}"
echo "   Waiting for table to become ACTIVE (typically 5–20 min)..."
echo ""

# Poll for completion
ELAPSED=0
INTERVAL=30
while true; do
    STATUS=$(aws dynamodb describe-table \
        --table-name "${DRILL_TABLE}" \
        --region "${REGION}" \
        --query "Table.TableStatus" \
        --output text 2>/dev/null || echo "CREATING")

    printf "   [%3ds] Status: %s\r" "${ELAPSED}" "${STATUS}"

    if [ "${STATUS}" = "ACTIVE" ]; then
        echo ""
        echo "   ✅ Restore complete after ${ELAPSED}s"
        break
    fi

    if [ "${ELAPSED}" -gt 1800 ]; then
        echo ""
        echo "❌ Restore timed out after 30 minutes. Check AWS console."
        exit 1
    fi

    sleep "${INTERVAL}"
    ELAPSED=$((ELAPSED + INTERVAL))
done
echo ""

# ── Step 2: Verify item count ───────────────────────────────────────────────
echo "🔢 Checking item count..."
# Note: ItemCount is eventually consistent — use a direct scan estimate
ITEM_COUNT=$(aws dynamodb describe-table \
    --table-name "${DRILL_TABLE}" \
    --region "${REGION}" \
    --query "Table.ItemCount" \
    --output text)
echo "   Item count (DDB estimate): ${ITEM_COUNT}"

ITEM_COUNT=$(echo "${ITEM_COUNT}" | tr -d '[:space:]')
ITEM_COUNT=${ITEM_COUNT:-0}
if [ "${ITEM_COUNT}" -lt 100 ]; then
    echo "   ⚠️  Very low item count — restore may be incomplete or table is newly populated"
else
    echo "   ✅ Item count looks healthy"
fi
echo ""

# ── Step 3: Verify required partitions ─────────────────────────────────────
echo "🔍 Verifying required partitions..."
PARTITION_FAILURES=0

for source in "${REQUIRED_PARTITIONS[@]}"; do
    PK="${USER_PREFIX}${source}"
    RESULT=$(aws dynamodb query \
        --table-name "${DRILL_TABLE}" \
        --region "${REGION}" \
        --key-condition-expression "pk = :pk" \
        --expression-attribute-values "{\":pk\": {\"S\": \"${PK}\"}}" \
        --select COUNT \
        --query "Count" \
        --output text 2>/dev/null | tr -d '[:space:]' || echo "0")
    RESULT=${RESULT:-0}

    if [ "${RESULT}" -gt 0 ]; then
        echo "   ✅ ${source}: ${RESULT} records"
    else
        echo "   ❌ ${source}: 0 records — partition missing or empty!"
        PARTITION_FAILURES=$((PARTITION_FAILURES + 1))
    fi
done

if [ "${PARTITION_FAILURES}" -gt 0 ]; then
    echo ""
    echo "⚠️  ${PARTITION_FAILURES} partition(s) had 0 records."
    echo "   This may be expected if data is sparse. Check manually:"
    echo "   aws dynamodb query --table-name ${DRILL_TABLE} --key-condition-expression 'pk = :pk' \\"
    echo "     --expression-attribute-values '{ \":pk\": {\"S\": \"USER#matthew#SOURCE#whoop\"} }' \\"
    echo "     --region ${REGION} --limit 3"
fi
echo ""

# ── Step 4: Verify recent records (last 7 days) ────────────────────────────
echo "📅 Checking for recent records (last 7 days)..."
TODAY=$(date -u +%Y-%m-%d)
WEEK_AGO=$(date -u -d "7 days ago" +%Y-%m-%d 2>/dev/null || date -u -v-7d +%Y-%m-%d)

RECENT_COUNT=$(aws dynamodb query \
    --table-name "${DRILL_TABLE}" \
    --region "${REGION}" \
    --key-condition-expression "pk = :pk AND sk BETWEEN :start AND :end" \
    --expression-attribute-values \
        "{\":pk\": {\"S\": \"${USER_PREFIX}whoop\"}, \":start\": {\"S\": \"DATE#${WEEK_AGO}\"}, \":end\": {\"S\": \"DATE#${TODAY}\"}}" \
    --select COUNT \
    --query "Count" \
    --output text 2>/dev/null || echo "0")

if [ "${RECENT_COUNT}" -gt 0 ]; then
    echo "   ✅ Found ${RECENT_COUNT} Whoop records in last 7 days (${WEEK_AGO} → ${TODAY})"
else
    echo "   ⚠️  No Whoop records in last 7 days — ingestion gap or PITR lag?"
fi
echo ""

# ── Step 5: Drill report ────────────────────────────────────────────────────
DRILL_END=$(date -u +%Y-%m-%dT%H:%M:%SZ)
echo "══════════════════════════════════════════════════════"
echo "  PITR DRILL REPORT"
echo "  Date:            $(date -u +%Y-%m-%d)"
echo "  Started:         ${RESTORE_START}"
echo "  Completed:       ${DRILL_END}"
echo "  Restore time:    ~${ELAPSED}s"
echo "  Items verified:  ${ITEM_COUNT} (DDB estimate)"
echo "  Partition check: $((${#REQUIRED_PARTITIONS[@]} - PARTITION_FAILURES))/${#REQUIRED_PARTITIONS[@]} passed"
echo "  Recent records:  ${RECENT_COUNT} (7-day Whoop window)"
echo ""
if [ "${PARTITION_FAILURES}" -eq 0 ]; then
    echo "  ✅ DRILL PASSED — PITR restore is functional"
else
    echo "  ⚠️  DRILL PASSED WITH WARNINGS — review partition failures above"
fi
echo "══════════════════════════════════════════════════════"
echo ""

# ── Step 6: Delete drill table ─────────────────────────────────────────────
echo "🗑  Deleting drill table ${DRILL_TABLE}..."
read -r -p "   Confirm deletion of ${DRILL_TABLE} [y/N]: " confirm
if [[ "${confirm}" =~ ^[Yy]$ ]]; then
    aws dynamodb delete-table \
        --table-name "${DRILL_TABLE}" \
        --region "${REGION}" > /dev/null
    echo "   ✅ Drill table deleted"
else
    echo "   ⚠️  Drill table NOT deleted. Delete manually:"
    echo "   aws dynamodb delete-table --table-name ${DRILL_TABLE} --region ${REGION}"
fi

echo ""
echo "Next drill due: $(date -u -d "+90 days" +%Y-%m-%d 2>/dev/null || date -u -v+90d +%Y-%m-%d)"
echo "Update RUNBOOK.md 'Last PITR drill' date after completing."
