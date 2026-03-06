#!/bin/bash
# ============================================================
# SMOKE TEST TEMPLATE — Life Platform
# Per PIR-2026-02-28 Process Improvement A
#
# Copy this block into every deploy script AFTER the
# aws lambda update-function-code / update-function-configuration
# calls. Customize FUNCTION_NAME and BACKUP_ZIP.
#
# Usage: source this file, or copy the smoke_test() function
#        into your deploy script.
# ============================================================

# --- Configure these per deploy script ---
# FUNCTION_NAME="strava-data-ingestion"
# BACKUP_ZIP="lambdas/strava_backup.zip"
# REGION="us-west-2"

smoke_test() {
    local fn="${1:?Usage: smoke_test FUNCTION_NAME [BACKUP_ZIP]}"
    local backup_zip="${2:-}"
    local region="${REGION:-us-west-2}"
    local test_output="/tmp/${fn}_smoke_test.json"

    echo ""
    echo "🔍 Smoke testing ${fn}..."
    echo "-------------------------------------------"

    # Wait for any pending update to complete
    echo "  Waiting for function update to complete..."
    aws lambda wait function-updated \
        --function-name "$fn" \
        --region "$region" 2>/dev/null

    # Invoke the function
    local log_output
    log_output=$(aws lambda invoke \
        --function-name "$fn" \
        --region "$region" \
        --log-type Tail \
        --payload '{}' \
        "$test_output" \
        --query 'LogResult' \
        --output text 2>&1)

    local invoke_exit=$?

    if [ $invoke_exit -ne 0 ]; then
        echo "  ❌ INVOKE FAILED (exit code $invoke_exit)"
        echo "  $log_output"
        attempt_rollback "$fn" "$backup_zip" "$region"
        return 1
    fi

    # Decode and display last 20 lines of logs
    echo "  📋 Last 20 log lines:"
    echo "$log_output" | base64 -d 2>/dev/null | tail -20 | sed 's/^/     /'

    # Check for errors in logs
    local decoded_logs
    decoded_logs=$(echo "$log_output" | base64 -d 2>/dev/null)

    if echo "$decoded_logs" | grep -qiE "ERROR|ImportModule|ModuleNotFoundError|Runtime.ImportModuleError|Task timed out"; then
        echo ""
        echo "  ❌ SMOKE TEST FAILED — errors detected in logs"
        attempt_rollback "$fn" "$backup_zip" "$region"
        return 1
    fi

    # Check for errors in response payload
    if [ -f "$test_output" ]; then
        if grep -qiE '"errorMessage"|"errorType"|"stackTrace"' "$test_output" 2>/dev/null; then
            echo ""
            echo "  ❌ SMOKE TEST FAILED — error in response payload:"
            cat "$test_output" | head -5 | sed 's/^/     /'
            attempt_rollback "$fn" "$backup_zip" "$region"
            return 1
        fi
    fi

    echo ""
    echo "  ✅ Smoke test PASSED for ${fn}"
    echo "-------------------------------------------"
    rm -f "$test_output"
    return 0
}

attempt_rollback() {
    local fn="$1"
    local backup_zip="$2"
    local region="$3"

    if [ -n "$backup_zip" ] && [ -f "$backup_zip" ]; then
        echo ""
        echo "  🔄 Rolling back ${fn} to ${backup_zip}..."
        aws lambda update-function-code \
            --function-name "$fn" \
            --zip-file "fileb://${backup_zip}" \
            --region "$region" > /dev/null 2>&1

        if [ $? -eq 0 ]; then
            echo "  ✅ Rollback successful"
        else
            echo "  ⚠️  Rollback FAILED — manual intervention required"
        fi
    else
        echo "  ⚠️  No backup zip provided — manual rollback required"
        echo "     Verify the function and fix before next scheduled invocation"
    fi
}

# --- Handler consistency check (PIR item B) ---
check_handler_match() {
    local fn="${1:?Usage: check_handler_match FUNCTION_NAME ZIP_FILE}"
    local zip_file="${2:?}"
    local region="${REGION:-us-west-2}"

    local handler
    handler=$(aws lambda get-function-configuration \
        --function-name "$fn" \
        --region "$region" \
        --query 'Handler' --output text 2>/dev/null)

    local expected_file="${handler%%.*}.py"

    if ! zipinfo -1 "$zip_file" 2>/dev/null | grep -q "^${expected_file}$"; then
        # Also check without path prefix (for nested zips)
        if ! zipinfo -1 "$zip_file" 2>/dev/null | grep -q "${expected_file}"; then
            echo "  ❌ HANDLER MISMATCH: Lambda expects '${expected_file}' but zip doesn't contain it!"
            echo "     Handler config: ${handler}"
            echo "     Zip contents:"
            zipinfo -1 "$zip_file" | head -10 | sed 's/^/       /'
            echo "     Fix: update handler or rename file in zip"
            return 1
        fi
    fi

    echo "  ✅ Handler check passed: ${handler} → ${expected_file} found in zip"
    return 0
}

# ============================================================
# EXAMPLE USAGE IN A DEPLOY SCRIPT:
# ============================================================
#
# #!/bin/bash
# set -euo pipefail
# FUNCTION_NAME="strava-data-ingestion"
# BACKUP_ZIP="lambdas/strava_backup.zip"
# REGION="us-west-2"
# source deploy/SMOKE_TEST_TEMPLATE.sh
#
# # ... build zip, backup current, deploy ...
#
# # Pre-deploy: verify handler matches
# check_handler_match "$FUNCTION_NAME" "$NEW_ZIP" || exit 1
#
# # Deploy
# aws lambda update-function-code \
#     --function-name "$FUNCTION_NAME" \
#     --zip-file "fileb://$NEW_ZIP" \
#     --region "$REGION"
#
# # Post-deploy: smoke test with auto-rollback
# smoke_test "$FUNCTION_NAME" "$BACKUP_ZIP" || exit 1
#
# echo "🎉 Deploy complete"
# ============================================================
