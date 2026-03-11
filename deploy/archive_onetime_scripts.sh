#!/bin/bash
# archive_onetime_scripts.sh — Archive completed one-time deploy scripts
# Run from project root: bash deploy/archive_onetime_scripts.sh
# v3.6.0 hygiene — 2026-03-11

set -e
ARCHIVE_DIR="deploy/archive/20260311"
mkdir -p "$ARCHIVE_DIR"

# One-time feature deploy scripts (task complete, never needed again)
ONE_TIME_SCRIPTS=(
    "deploy/deploy_ic19.sh"           # IC-19 one-time feature deploy
    "deploy/deploy_obs1_ai3_apikeys.sh" # OBS-1/AI-3/api-keys one-time deploy
    "deploy/finish_cost_a.sh"         # COST-A completion script
    "deploy/migrate_ingestion_keys.sh" # One-time ingestion key migration
    "deploy/maint3_archive_deploy.sh" # MAINT-3 one-time archive task
    "deploy/post_hygiene_v344.sh"     # v3.4.4 one-time hygiene
    "deploy/setup_ingestion_keys.sh"  # One-time ingestion key setup
    "deploy/delete_old_ingestion_secrets.sh" # One-time secret deletion
    "deploy/delete_orphan_alarms.sh"  # One-time orphan alarm cleanup
)

# Layer build scripts (superseded by build_layer.sh)
LAYER_SCRIPTS=(
    "deploy/p3_build_garmin_layer.sh"       # One-time garmin layer build
    "deploy/p3_build_shared_utils_layer.sh" # Superseded by build_layer.sh
    "deploy/p3_attach_shared_utils_layer.sh" # One-time layer attachment
)

echo "Archiving one-time scripts to $ARCHIVE_DIR..."
for script in "${ONE_TIME_SCRIPTS[@]}" "${LAYER_SCRIPTS[@]}"; do
    if [ -f "$script" ]; then
        mv "$script" "$ARCHIVE_DIR/"
        echo "  ✅ Archived: $script"
    else
        echo "  ⚠️  Not found (already archived?): $script"
    fi
done

echo ""
echo "Active scripts remaining in deploy/:"
ls deploy/*.sh deploy/*.py 2>/dev/null | grep -v archive | sort

echo ""
echo "Done. $(ls $ARCHIVE_DIR | wc -l) scripts archived to $ARCHIVE_DIR"
