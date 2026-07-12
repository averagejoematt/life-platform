#!/bin/bash
# ============================================================
# Laptop-asset backup — the ONLY two laptop-only assets (#1026,
# stolen-laptop epic #1024; docs/CONTINUITY.md §4):
#
#   1. Claude Code file memory  → s3://…/claude-memory-backup/
#   2. datadrops/ originals     → s3://…/datadrops-archive/
#
# Runs daily via launchd (com.matthewwalker.claude-memory-backup);
# the /wrap-step memory sync stays as belt-and-suspenders.
#
# INSTALL LAYOUT (macOS TCC): launchd agents cannot execute or read
# anything under ~/Documents without a Full Disk Access grant — the
# repo copy of this script is the SOURCE; install.sh copies it to
# ~/.local/bin/ (outside TCC scope) and launchd runs THAT copy. The
# memory dir lives in ~/.claude (unprotected → always works); the
# datadrops sync reads ~/Documents and will fail TCC-blocked until
# /bin/bash is granted Full Disk Access (System Settings → Privacy &
# Security) — the run logs exactly that instead of dying silently.
#
# NB: datadrops lands under the top-level `datadrops-archive/` prefix,
# NOT `uploads/` as the original issue sketched — uploads/ carries a
# 30-day lifecycle EXPIRATION (deploy/apply_s3_lifecycle.sh) that would
# silently delete the archive. datadrops-archive/ is delete-protected
# (deploy/bucket_policy.json) with only noncurrent-version expiry.
# ============================================================
set -uo pipefail

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

# 2. datadrops originals (genome, physicals, HAE exports, backfills)
if [ -r "$REPO/datadrops" ] && ls "$REPO/datadrops" > /dev/null 2>&1; then
    "$AWS" s3 sync "$REPO/datadrops/" "s3://$BUCKET/datadrops-archive/" \
        --region "$REGION" --exclude "logs/*" --exclude "*.DS_Store" || rc=1
else
    echo "WARN: datadrops unreadable from launchd — macOS TCC blocks ~/Documents."
    echo "      Grant /bin/bash Full Disk Access (System Settings → Privacy & Security)"
    echo "      to enable the datadrops leg (also fixes the life-platform-ingest watcher)."
    rc=1
fi

echo "=== done rc=$rc $(date -u +%FT%TZ) ==="
exit $rc
