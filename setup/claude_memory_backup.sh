#!/bin/bash
# ============================================================
# Laptop-asset backup — the ONLY two laptop-only assets (#1026,
# stolen-laptop epic #1024; docs/CONTINUITY.md §4):
#
#   1. Claude Code file memory  → s3://…/claude-memory-backup/
#   2. datadrops/ originals     → s3://…/datadrops-archive/
#
# Runs daily via launchd (com.matthewwalker.claude-memory-backup,
# 09:15 + RunAtLoad); the /wrap-step memory sync stays as
# belt-and-suspenders. BOTH legs run on every invocation — there is
# no flag, no env switch, and no "manual push" mode.
#
# INSTALL LAYOUT (2026-08-31): launchd runs THIS file, in the repo,
# directly. There is no staged copy and no install.sh.
#
#   The previous layout staged a copy into ~/.local/bin/ because
#   macOS TCC blocks launchd from reading ~/Documents, where the repo
#   used to live. That constraint died on 2026-08-30 when the repo
#   moved to ~/dev, which TCC does not protect (it covers
#   Documents/Desktop/Downloads/iCloud only) — verified: launchd
#   executes ~/dev/life-platform/ingest/process_all_drops.sh and exits 0.
#
#   The staging is not merely unnecessary, it is what broke this
#   script. The repo copy this header used to claim was "the SOURCE"
#   never existed, and neither did the install.sh said to stage it —
#   so the only copy was an untracked file in ~/.local/bin carrying a
#   hard-coded ~/Documents path. When the repo moved, that path went
#   stale, the datadrops leg failed on every run from 2026-07-11 to
#   2026-08-30, and it reported a TCC error that was no longer the
#   cause. One copy, in git, reviewed by the same gates as everything
#   else, is the whole point of this layout.
#
#   tests/test_backup_agent_path_contract.py asserts the LaunchAgent's
#   ProgramArguments still names this file. It cannot drift silently again.
#
# PATHS ARE DERIVED, NOT TYPED. REPO comes from this script's own
# location and MEMORY_DIR from REPO, so moving the checkout moves both
# — the failure above was a hard-coded path outliving a migration.
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

# This file lives at <repo>/setup/, so the checkout is one level up. Resolved from
# $0 rather than typed, so a future relocation carries both legs with it.
REPO="$(cd "$(dirname "$0")/.." && pwd)"

# Claude Code keys its per-project memory dir by the checkout's absolute path with
# every "/" replaced by "-". Deriving it from REPO means the move that re-keys the
# memory dir also re-points this backup, in one step instead of two.
MEMORY_DIR="$HOME/.claude/projects/${REPO//\//-}/memory"

LOG_DIR="$HOME/Library/Logs/claude-backup"
LOG="$LOG_DIR/backup-$(date +%Y%m%d).log"

mkdir -p "$LOG_DIR"
exec >> "$LOG" 2>&1
echo "=== backup run $(date -u +%FT%TZ) ==="
echo "    repo:   $REPO"
echo "    memory: $MEMORY_DIR"

rc=0

# 1. Claude Code file memory (CONTINUITY §4) — ~/.claude, never TCC-blocked
if [ -d "$MEMORY_DIR" ]; then
    "$AWS" s3 sync "$MEMORY_DIR/" "s3://$BUCKET/claude-memory-backup/" --region "$REGION" || rc=1
else
    echo "WARN: memory dir missing: $MEMORY_DIR"
    echo "      Derived from REPO ($REPO) using Claude Code's path-to-key encoding."
    echo "      If the checkout moved, this is expected on the FIRST run only — Claude Code"
    echo "      creates the new key on its next session. If it persists, the encoding changed."
    rc=1
fi

# 2. datadrops originals (genome, physicals, HAE exports, backfills)
if [ -r "$REPO/datadrops" ] && ls "$REPO/datadrops" > /dev/null 2>&1; then
    "$AWS" s3 sync "$REPO/datadrops/" "s3://$BUCKET/datadrops-archive/" \
        --region "$REGION" --exclude "logs/*" --exclude "*.DS_Store" || rc=1
else
    echo "WARN: $REPO/datadrops is missing or unreadable — the datadrops leg did NOT run."
    echo "      datadrops/ is gitignored, so a fresh clone has none: restore it from"
    echo "      s3://$BUCKET/datadrops-archive/ (docs/NEW_MACHINE_BOOTSTRAP.md §4b)."
    echo "      This is NOT the old TCC failure — ~/dev is not a TCC-protected location."
    rc=1
fi

echo "=== done rc=$rc $(date -u +%FT%TZ) ==="
exit $rc
