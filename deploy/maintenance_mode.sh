#!/usr/bin/env bash
# maintenance_mode.sh — R8-ST3: Disable/enable non-essential Lambdas for vacation/absence.
#
# Usage:
#   bash deploy/maintenance_mode.sh enable    # disable non-essential rules → maintenance mode ON
#   bash deploy/maintenance_mode.sh disable   # re-enable all rules → back to normal
#   bash deploy/maintenance_mode.sh status    # show current state of all rules
#
# Strategy: disable EventBridge rules (not Lambda concurrency — account limit=10 prevents that).
# Core ingestion + MCP + canary + freshness keep running.
# Cosmetic/email Lambdas are suspended.
#
# NON-ESSENTIAL (suspended in maintenance mode):
#   monday-compass, wednesday-chronicle, weekly-plate, nutrition-review,
#   weekly-digest, monthly-digest, hypothesis-engine
#
# ALWAYS KEPT RUNNING (core):
#   All ingestion Lambdas (19 sources), daily-brief, daily-metrics-compute,
#   daily-insight-compute, character-sheet-compute, adaptive-mode-compute,
#   anomaly-detector, freshness-checker, canary, MCP warmer, DLQ consumer

set -euo pipefail

REGION="us-west-2"
ACTION="${1:-status}"

NON_ESSENTIAL_RULES=(
    "monday-compass"
    "wednesday-chronicle"
    "weekly-plate-schedule"
    "nutrition-review-schedule"
    "weekly-digest-sunday"
    "monthly-digest-schedule"
    "hypothesis-engine-weekly"
)

usage() {
    echo "Usage: bash deploy/maintenance_mode.sh [enable|disable|status]"
    echo ""
    echo "  enable   — disable non-essential EventBridge rules (maintenance mode ON)"
    echo "  disable  — re-enable all rules (maintenance mode OFF)"
    echo "  status   — show current state of all non-essential rules"
    exit 1
}

check_rule_state() {
    local rule="$1"
    aws events describe-rule \
        --name "$rule" \
        --region "$REGION" \
        --query 'State' \
        --output text 2>/dev/null || echo "NOT_FOUND"
}

case "$ACTION" in
enable)
    echo "=== Enabling maintenance mode ==="
    echo "Disabling non-essential EventBridge rules..."
    echo ""
    FAILED=0
    for rule in "${NON_ESSENTIAL_RULES[@]}"; do
        STATE=$(check_rule_state "$rule")
        if [ "$STATE" = "NOT_FOUND" ]; then
            echo "  ⚠️  $rule — not found (skipping)"
        elif [ "$STATE" = "DISABLED" ]; then
            echo "  ℹ️  $rule — already DISABLED"
        else
            if aws events disable-rule --name "$rule" --region "$REGION" 2>/dev/null; then
                echo "  ✅ $rule — DISABLED"
            else
                echo "  ❌ $rule — FAILED to disable"
                FAILED=$((FAILED + 1))
            fi
        fi
    done
    echo ""
    if [ "$FAILED" -gt 0 ]; then
        echo "❌ $FAILED rule(s) failed to disable."
        exit 1
    fi
    echo "✅ Maintenance mode ON."
    echo "   Core ingestion, daily brief, compute, and monitoring continue running."
    echo "   Weekly/monthly emails suspended."
    echo ""
    echo "To return to normal: bash deploy/maintenance_mode.sh disable"
    ;;

disable)
    echo "=== Disabling maintenance mode ==="
    echo "Re-enabling non-essential EventBridge rules..."
    echo ""
    FAILED=0
    for rule in "${NON_ESSENTIAL_RULES[@]}"; do
        STATE=$(check_rule_state "$rule")
        if [ "$STATE" = "NOT_FOUND" ]; then
            echo "  ⚠️  $rule — not found (skipping)"
        elif [ "$STATE" = "ENABLED" ]; then
            echo "  ℹ️  $rule — already ENABLED"
        else
            if aws events enable-rule --name "$rule" --region "$REGION" 2>/dev/null; then
                echo "  ✅ $rule — ENABLED"
            else
                echo "  ❌ $rule — FAILED to enable"
                FAILED=$((FAILED + 1))
            fi
        fi
    done
    echo ""
    if [ "$FAILED" -gt 0 ]; then
        echo "❌ $FAILED rule(s) failed to enable."
        exit 1
    fi
    echo "✅ Maintenance mode OFF. All rules re-enabled."
    ;;

status)
    echo "=== Non-essential rule states ==="
    echo ""
    ALL_ENABLED=true
    ANY_DISABLED=false
    for rule in "${NON_ESSENTIAL_RULES[@]}"; do
        STATE=$(check_rule_state "$rule")
        if [ "$STATE" = "ENABLED" ]; then
            echo "  ✅ ENABLED   $rule"
        elif [ "$STATE" = "DISABLED" ]; then
            echo "  🔴 DISABLED  $rule"
            ALL_ENABLED=false
            ANY_DISABLED=true
        else
            echo "  ⚠️  $STATE    $rule"
        fi
    done
    echo ""
    if [ "$ANY_DISABLED" = "true" ]; then
        echo "⚠️  MAINTENANCE MODE IS ACTIVE — some rules are disabled."
        echo "   Run 'bash deploy/maintenance_mode.sh disable' to restore normal operation."
    else
        echo "✅ Normal operation — all non-essential rules enabled."
    fi
    ;;

*)
    usage
    ;;
esac
