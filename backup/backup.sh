#!/bin/bash
# ============================================================
# Laptop-asset backup — the ONLY two laptop-only assets (#1026,
# stolen-laptop epic #1024; docs/CONTINUITY.md §4):
#
#   1. Claude Code file memory  → s3://…/claude-memory-backup/   (AUTOMATED)
#   2. datadrops/ originals     → s3://…/datadrops-archive/      (MANUAL)
#
# TCC POSTURE (decided 2026-07-13): we deliberately do NOT grant Full
# Disk Access to /bin/bash — that would hand FDA to every shell script
# on the machine. Consequence, by design:
#
#   • The MEMORY leg reads ~/.claude (never a TCC-protected folder), so
#     the daily launchd agent (com.matthewwalker.claude-memory-backup)
#     runs it FDA-free. This is the critical, high-churn leg. install.sh
#     stages this script to ~/.local/bin/ (outside TCC) so launchd can
#     execute it. The /wrap-step memory sync stays as belt-and-suspenders.
#
#   • The DATADROPS leg reads ~/Documents (TCC-protected) and is LOW-churn
#     (genome, physicals, health exports — historical). Rather than a
#     standing FDA grant, it runs ONLY when invoked MANUALLY from an
#     interactive Terminal (which already has disk access via your login
#     session): `BACKUP_DATADROPS=1 bash ~/.local/bin/claude-memory-backup.sh`.
#     Run it whenever you add a new drop. The daily launchd job skips it
#     silently (no perpetual TCC warning). See docs/NEW_MACHINE_BOOTSTRAP §3c.
#
# NB: datadrops lands under the top-level `datadrops-archive/` prefix,
# NOT `uploads/` as the original issue sketched — uploads/ carries a
# 30-day lifecycle EXPIRATION (deploy/apply_s3_lifecycle.sh) that would
# silently delete the archive. datadrops-archive/ is delete-protected
# (deploy/bucket_policy.json) with only noncurrent-version expiry.
# ============================================================
set -uo pipefail

# datadrops leg is opt-in (manual Terminal run) — off in the daily launchd job.
BACKUP_DATADROPS="${BACKUP_DATADROPS:-0}"

AWS="/opt/homebrew/bin/aws"
BUCKET="matthew-life-platform"
REGION="us-west-2"
REPO="$HOME/Documents/Claude/life-platform"
MEMORY_DIR="$HOME/.claude/projects/-Users-matthewwalker-Documents-Claude-life-platform/memory"
LOG_DIR="$HOME/Library/Logs/claude-backup"
LOG="$LOG_DIR/backup-$(date +%Y%m%d).log"

mkdir -p "$LOG_DIR"
exec >> "$LOG" 2>&1
echo "=== backup run $(date -u +%FT%TZ) ==="

rc=0

# 1. Claude Code file memory (CONTINUITY §4) — ~/.claude, never TCC-blocked
if [ -d "$MEMORY_DIR" ]; then
    "$AWS" s3 sync "$MEMORY_DIR/" "s3://$BUCKET/claude-memory-backup/" --region "$REGION" || rc=1
else
    echo "WARN: memory dir missing: $MEMORY_DIR"
    rc=1
fi

# 2. datadrops originals (genome, physicals, HAE exports, backfills) — MANUAL.
#    Opt-in only, because reading ~/Documents needs disk access we grant via an
#    interactive Terminal login, NOT a standing FDA grant on bash (see header).
if [ "$BACKUP_DATADROPS" = "1" ]; then
    if [ -r "$REPO/datadrops" ] && ls "$REPO/datadrops" > /dev/null 2>&1; then
        "$AWS" s3 sync "$REPO/datadrops/" "s3://$BUCKET/datadrops-archive/" \
            --region "$REGION" --exclude "logs/*" --exclude "*.DS_Store" || rc=1
    else
        echo "WARN: BACKUP_DATADROPS=1 but datadrops unreadable — run this from an"
        echo "      interactive Terminal (Finder-launched Terminal.app has disk access),"
        echo "      not from the launchd agent. Path: $REPO/datadrops"
        rc=1
    fi
else
    echo "INFO: datadrops leg skipped (manual push only — BACKUP_DATADROPS=1 from a Terminal)."
fi

echo "=== done rc=$rc $(date -u +%FT%TZ) ==="
exit $rc
