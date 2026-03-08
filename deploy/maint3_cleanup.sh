#!/usr/bin/env bash
# MAINT-3: Archive stale files from lambdas/ and deploy/
# Creates an archive directory rather than deleting, so nothing is lost.
# Run from project root: bash deploy/maint3_cleanup.sh

set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ARCHIVE="$ROOT/archive/$(date +%Y%m%d)"
mkdir -p "$ARCHIVE/lambdas" "$ARCHIVE/deploy"

echo "=== MAINT-3: Archiving stale files to $ARCHIVE ==="

# ─── lambdas/ ─────────────────────────────────────────────────────────────────

LAMBDAS="$ROOT/lambdas"

# .backup and .broken files
for f in \
  "daily_brief_lambda.py.backup-20260301-083034" \
  "daily_brief_lambda.py.backup-20260301-123650" \
  "daily_brief_lambda.py.backup-20260301-123926" \
  "daily_brief_lambda.py.broken"; do
  if [ -f "$LAMBDAS/$f" ]; then
    mv "$LAMBDAS/$f" "$ARCHIVE/lambdas/"
    echo "  archived lambdas/$f"
  fi
done

# Stale zip files (regenerated at deploy time)
for f in \
  "daily_brief_lambda.zip" \
  "freshness_checker.zip" \
  "notion-journal-ingestion.zip" \
  "mcp_server.zip"; do
  if [ -f "$LAMBDAS/$f" ]; then
    mv "$LAMBDAS/$f" "$ARCHIVE/lambdas/"
    echo "  archived lambdas/$f"
  fi
done

# Superseded lambda versions
for f in "weekly_digest_v2_lambda.py"; do
  if [ -f "$LAMBDAS/$f" ]; then
    mv "$LAMBDAS/$f" "$ARCHIVE/lambdas/"
    echo "  archived lambdas/$f"
  fi
done

# Old backup directories
for d in "backup_20260227_182129" "backup_20260227_183354"; do
  if [ -d "$LAMBDAS/$d" ]; then
    mv "$LAMBDAS/$d" "$ARCHIVE/lambdas/"
    echo "  archived lambdas/$d/"
  fi
done

# ─── deploy/ ──────────────────────────────────────────────────────────────────

DEPLOY="$ROOT/deploy"

# Non-script files that don't belong in deploy/
for f in \
  "daily_brief_lambda.py" \
  "daily_brief_lambda.zip" \
  "daily_brief_v2.77.0.zip" \
  "freshness_checker.zip" \
  "wednesday_chronicle.zip" \
  "withings_lambda.zip" \
  "scoring_engine.py" \
  "patch_daily_brief_hardening.py" \
  "patch_mcp_features_12_25.py"; do
  if [ -f "$DEPLOY/$f" ]; then
    mv "$DEPLOY/$f" "$ARCHIVE/deploy/"
    echo "  archived deploy/$f"
  fi
done

# Move one-off seed/generator script to seeds/ where it belongs
SEEDS="$ROOT/seeds"
mkdir -p "$SEEDS"
if [ -f "$DEPLOY/generate_habit_registry.py" ]; then
  mv "$DEPLOY/generate_habit_registry.py" "$SEEDS/"
  echo "  moved deploy/generate_habit_registry.py → seeds/"
fi

# Versioned daily_brief deploy scripts (keep deploy_daily_brief.sh as canonical)
for f in \
  "deploy_daily_brief_v2.sh" \
  "deploy_daily_brief_v21.sh" \
  "deploy_daily_brief_v22.sh" \
  "deploy_daily_brief_v221.sh" \
  "deploy_daily_brief_v222.sh" \
  "deploy_daily_brief_v223.sh" \
  "deploy_daily_brief_v23.sh" \
  "deploy_daily_brief_v247.sh" \
  "deploy_daily_brief_v259.sh" \
  "deploy_daily_brief_v2.76.0.sh" \
  "deploy_daily_brief_v2.77.0.sh" \
  "deploy_daily_brief_v2_timing.sh" \
  "deploy_daily_brief_v2_timing_step2.sh"; do
  if [ -f "$DEPLOY/$f" ]; then
    mv "$DEPLOY/$f" "$ARCHIVE/deploy/"
    echo "  archived deploy/$f"
  fi
done

# Versioned weekly_digest deploy scripts (keep deploy_weekly_digest.sh)
for f in "deploy_weekly_digest_v2.sh"; do
  if [ -f "$DEPLOY/$f" ]; then
    mv "$DEPLOY/$f" "$ARCHIVE/deploy/"
    echo "  archived deploy/$f"
  fi
done

# Hotfix scripts older than v5 (keep v5, v6, v7 which are most recent)
for f in \
  "hotfix_daily_brief_indent.sh" \
  "hotfix_daily_brief_v2.sh" \
  "hotfix_daily_brief_v3.sh" \
  "hotfix_daily_brief_v4.sh"; do
  if [ -f "$DEPLOY/$f" ]; then
    mv "$DEPLOY/$f" "$ARCHIVE/deploy/"
    echo "  archived deploy/$f"
  fi
done

echo ""
echo "=== Done. Archive at: $ARCHIVE ==="
echo "Verify nothing critical was moved before committing."
echo "To undo: mv $ARCHIVE/lambdas/* $LAMBDAS/ && mv $ARCHIVE/deploy/* $DEPLOY/"
