#!/usr/bin/env bash
# deploy_v3.9.35.sh — Master deploy for v3.9.35 session
# 
# Runs all deploy steps in order:
#   1. Design Brief Tier 1 (body-signal, breadcrumbs, reading paths, animations.js)
#   2. Character page pillar ring chart
#   3. Add 6 new experiments to library
#   4. Lifecycle gaps (MCP + site-api + achievements)
#   5. Upload podcast watchlist config
#   6. Sync site to S3 + invalidate CloudFront
#
# Usage: bash deploy/deploy_v3.9.35.sh
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_ROOT"

BUCKET="matthew-life-platform"
REGION="us-west-2"
DIST_ID="E3S424OXQZ8NBE"

echo ""
echo "═══════════════════════════════════════════════════"
echo "  Life Platform v3.9.35 — Full Deploy"
echo "═══════════════════════════════════════════════════"
echo ""

# ── Step 1: Design Brief Tier 1 ──────────────────────────────
echo "[1/7] Applying Design Brief (body-signal + breadcrumbs + reading paths + animations.js)..."
python3 deploy/apply_design_brief.py
echo ""

# ── Step 2: Character pillar ring chart ───────────────────────
echo "[2/7] Patching Character page pillar ring chart..."
python3 deploy/patch_character_ring.py
echo ""

# ── Step 3: Add 6 new experiments ─────────────────────────────
echo "[3/7] Adding 6 new experiments to library..."
python3 deploy/add_experiments.py
echo ""

# ── Step 4: MCP registry test ────────────────────────────────
echo "[4/7] Running MCP registry test..."
python3 -m pytest tests/test_mcp_registry.py -v
echo ""

# ── Step 5: Deploy lifecycle gaps (MCP + site-api + achievements) ──
echo "[5/7] Deploying lifecycle gaps..."
bash deploy/deploy_lifecycle_gaps.sh
echo ""

# ── Step 6: Upload experiment library + podcast watchlist ─────
echo "[6/7] Uploading experiment library + podcast watchlist..."
aws s3 cp config/experiment_library.json "s3://$BUCKET/config/experiment_library.json" --region "$REGION" --no-cli-pager
aws s3 cp config/experiment_library.json "s3://$BUCKET/site/config/experiment_library.json" --region "$REGION" --no-cli-pager
aws s3 cp config/podcast_watchlist.json "s3://$BUCKET/config/podcast_watchlist.json" --region "$REGION" --no-cli-pager
echo "  Done"
echo ""

# ── Step 7: Full site sync + CloudFront invalidation ─────────
echo "[7/7] Syncing full site to S3 + invalidating CloudFront..."
aws s3 sync site/ "s3://$BUCKET/site/" --region "$REGION" --no-cli-pager --exclude ".DS_Store" --exclude "*.swp"
aws cloudfront create-invalidation --distribution-id "$DIST_ID" --paths "/*" --region us-east-1 --no-cli-pager
echo "  Done"
echo ""

echo "═══════════════════════════════════════════════════"
echo "  v3.9.35 Deploy Complete"
echo "═══════════════════════════════════════════════════"
echo ""
echo "Verify:"
echo "  https://averagejoematt.com/sleep/        (body-signal + breadcrumb + reading path)"
echo "  https://averagejoematt.com/character/     (pillar ring chart)"
echo "  https://averagejoematt.com/challenges/    (vote buttons)"
echo "  https://averagejoematt.com/achievements/  (challenge badges)"
echo "  https://averagejoematt.com/experiments/   (6 new backlog experiments)"
echo ""
