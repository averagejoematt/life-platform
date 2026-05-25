#!/usr/bin/env bash
# run_chronicle_workflow_2026_05_03.sh
# ====================================
# Single-entry-point wrapper for the Sunday-evening chronicle workflow.
# Walks through: review markdown -> cleanup gap -> publish special edition -> pause Wednesdays.
# Each step shows the dry-run output, then asks before --apply.
#
# Usage:
#   bash deploy/run_chronicle_workflow_2026_05_03.sh

set -e
set -u
set -o pipefail

PROJECT_ROOT="${HOME}/Documents/Claude/life-platform"
cd "${PROJECT_ROOT}"

CHRONICLE_MD="${PROJECT_ROOT}/docs/elena_special_edition_chronicle_2026_05_03.md"
CLEANUP="${PROJECT_ROOT}/deploy/cleanup_gap_chronicles_2026_05_03.py"
PUBLISH="${PROJECT_ROOT}/deploy/publish_special_edition_chronicle_2026_05_03.py"
PAUSE="${PROJECT_ROOT}/deploy/pause_wednesday_chronicle_2026_05_03.py"

ask() {
  local prompt="$1"
  local reply
  while true; do
    printf "\n%s [y/n/q]: " "${prompt}"
    read -r reply
    case "${reply}" in
      [Yy]*) return 0 ;;
      [Nn]*) return 1 ;;
      [Qq]*) echo "Aborting workflow."; exit 0 ;;
      *) echo "Please answer y, n, or q." ;;
    esac
  done
}

banner() {
  echo ""
  echo "============================================================"
  echo "  $1"
  echo "============================================================"
}

banner "Step 1 of 4 — Review the chronicle markdown"
echo "Path: ${CHRONICLE_MD}"
if [[ ! -f "${CHRONICLE_MD}" ]]; then
  echo "ERROR: Chronicle markdown not found. Aborting."
  exit 1
fi

if ask "Open the chronicle in your default editor for review?"; then
  open "${CHRONICLE_MD}"
  echo ""
  echo "Chronicle opened. Take your time. Edit if needed — the publish script reads from this file at runtime."
  ask "Ready to continue with the workflow?" || { echo "Stopping. Re-run when ready."; exit 0; }
else
  echo "Skipping editor open."
fi

banner "Step 2 of 4 — Cleanup gap-window chronicles (DRY-RUN first)"
python3 "${CLEANUP}"
if ask "Apply cleanup (delete gap-window chronicle records)?"; then
  python3 "${CLEANUP}" --apply
else
  echo "Skipping cleanup. Cannot proceed with publish (would conflict with stale drafts). Aborting."
  exit 0
fi

banner "Step 3 of 4 — Publish the special edition (DRY-RUN first)"
python3 "${PUBLISH}"
if ask "Publish 'The Architecture of Absence' to the live site?"; then
  python3 "${PUBLISH}" --apply
else
  echo "Skipping publish. The cleanup already ran, so the site is in a clean state. You can re-run this script later."
  exit 0
fi

banner "Step 4 of 4 — Pause the Wednesday chronicle EventBridge rule"
python3 "${PAUSE}"
if ask "Disable the Wednesday chronicle schedule?"; then
  python3 "${PAUSE}" --apply
else
  echo "Skipping pause. The Wednesday Lambda will fire as normal on May 6 unless you disable it manually."
fi

banner "DONE"
echo ""
echo "Verify at:"
echo "  https://averagejoematt.com/blog/week-05.html"
echo "  https://averagejoematt.com/blog/"
echo "  https://averagejoematt.com/journal/posts/week-05/"
echo ""
