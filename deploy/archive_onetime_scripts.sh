#!/bin/bash
# archive_onetime_scripts.sh — Archive completed one-time deploy scripts
# Run from project root: bash deploy/archive_onetime_scripts.sh
# Updated: v3.7.12 — 2026-03-14

set -e

# ── Batch 1: v3.6.0 — 2026-03-11 ──
ARCHIVE_1="deploy/archive/20260311"
mkdir -p "$ARCHIVE_1"

BATCH_1=(
    "deploy/deploy_ic19.sh"                     # IC-19 one-time feature deploy
    "deploy/deploy_obs1_ai3_apikeys.sh"         # OBS-1/AI-3/api-keys one-time deploy
    "deploy/finish_cost_a.sh"                   # COST-A completion script
    "deploy/migrate_ingestion_keys.sh"          # One-time ingestion key migration
    "deploy/maint3_archive_deploy.sh"           # MAINT-3 one-time archive task
    "deploy/post_hygiene_v344.sh"               # v3.4.4 one-time hygiene
    "deploy/setup_ingestion_keys.sh"            # One-time ingestion key setup
    "deploy/delete_old_ingestion_secrets.sh"    # One-time secret deletion
    "deploy/delete_orphan_alarms.sh"            # One-time orphan alarm cleanup
    "deploy/p3_build_garmin_layer.sh"           # One-time garmin layer build
    "deploy/p3_build_shared_utils_layer.sh"     # Superseded by build_layer.sh
    "deploy/p3_attach_shared_utils_layer.sh"    # One-time layer attachment
)

# ── Batch 2: v3.7.12 — 2026-03-14 ──
ARCHIVE_2="deploy/archive/20260314"
mkdir -p "$ARCHIVE_2"

BATCH_2=(
    "deploy/deploy_tb7_apikeys_fixes.sh"        # TB7 api-keys one-time fixes
    "deploy/deploy_tb7_reconcile.sh"            # TB7 CDK reconcile one-time deploy
    "deploy/fix_p0_alarm_bugs.sh"              # P0 alarm storm one-time fix
    "deploy/fix_p0_daily_insight_deploy.sh"    # P0 daily-insight one-time fix
    "deploy/attach_mcp_waf.sh"                 # WAF attempt (N/A — not supported for Lambda URLs)
    "deploy/archive_changelog_v341.sh"         # One-time changelog archive task
    "deploy/check_eb_scheduler_orphans.sh"     # TB7-5 one-time EB orphan check (done)
    "deploy/cdk_env_diff.sh"                   # One-time CDK env diff
    "deploy/triage_alarms.sh"                  # One-time alarm triage
    "deploy/verify_dlq_alarm_periods.sh"       # One-time DLQ alarm period verification
    "deploy/create_ai_cost_alarm.sh"           # One-time alarm creation
    "deploy/audit_alarms.sh"                   # One-time alarm audit
    "deploy/generate_review_bundle.sh"         # Superseded by generate_review_bundle.py
)

echo "=== Batch 1: archiving to $ARCHIVE_1 ==="
for script in "${BATCH_1[@]}"; do
    if [ -f "$script" ]; then
        mv "$script" "$ARCHIVE_1/"
        echo "  ✅ Archived: $script"
    else
        echo "  ⚠️  Not found (already archived?): $script"
    fi
done

echo ""
echo "=== Batch 2: archiving to $ARCHIVE_2 ==="
for script in "${BATCH_2[@]}"; do
    if [ -f "$script" ]; then
        mv "$script" "$ARCHIVE_2/"
        echo "  ✅ Archived: $script"
    else
        echo "  ⚠️  Not found (already archived?): $script"
    fi
done

echo ""
echo "=== Active scripts remaining in deploy/ ==="
ls deploy/*.sh deploy/*.py deploy/*.json 2>/dev/null | grep -v archive | sort

echo ""
TOTAL=$(ls deploy/archive/20260311/ deploy/archive/20260314/ 2>/dev/null | wc -l | tr -d ' ')
echo "Done. ~$TOTAL scripts total in archive."
