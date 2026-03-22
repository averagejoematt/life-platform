#!/usr/bin/env bash
# deploy_d10_phase1.sh — Deploy D10 + Phase 1 Task 20
#
# D10:  site_writer.py + daily_brief_lambda.py now pass baseline to public_stats.json.
#       The compare card Day 1 column is now fully dynamic — no hardcoded HTML values.
# T20:  Reading path CTAs injected into 7 pages (story → live → character →
#       habits → experiments → discoveries → intelligence → ask).
#
# Run from repo root:
#   bash deploy/deploy_d10_phase1.sh
#
set -e
REPO="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO"

echo ""
echo "════════════════════════════════════════════════"
echo " D10 + Phase 1 Task 20 Deploy"
echo "════════════════════════════════════════════════"
echo ""

# ── Step 1: Inject reading path CTAs into 7 pages ────────────────────────────
echo "[1/5] Injecting reading path CTAs..."
python3 deploy/add_reading_path_ctas.py

# ── Step 2: Refresh public_stats.json with baseline right now ─────────────────
echo ""
echo "[2/5] Refreshing public_stats.json with baseline data..."
python3 deploy/fix_public_stats.py --write

# ── Step 3: Deploy daily-brief Lambda (picks up site_writer.py baseline fix) ──
echo ""
echo "[3/5] Deploying daily-brief Lambda..."
bash deploy/deploy_lambda.sh daily-brief lambdas/daily_brief_lambda.py \
    --extra-files lambdas/html_builder.py lambdas/ai_calls.py lambdas/output_writers.py \
                  lambdas/board_loader.py lambdas/site_writer.py

# ── Step 4: Sync site/ to S3 ──────────────────────────────────────────────────
echo ""
echo "[4/5] Syncing site/ to S3..."
aws s3 sync site/ s3://matthew-life-platform/site/ --delete --quiet
echo "  ✅ S3 sync complete"

# ── Step 5: CloudFront invalidation ───────────────────────────────────────────
echo ""
echo "[5/5] Invalidating CloudFront..."
INV_ID=$(aws cloudfront create-invalidation \
  --distribution-id E3S424OXQZ8NBE \
  --paths "/*" \
  --no-cli-pager \
  --output text --query 'Invalidation.Id')
echo "  ✅ Invalidation: $INV_ID (~30s to propagate)"

echo ""
echo "════════════════════════════════════════════════"
echo " Deploy complete!"
echo ""
echo " What changed:"
echo "  D10: baseline{} now in daily_brief → site_writer → public_stats.json"
echo "  D10: compare card Day 1 column no longer hardcoded in HTML"
echo "  T20: Reading path CTAs on 7 pages"
echo ""
echo " Verify:"
echo "  curl -s 'https://averagejoematt.com/public_stats.json?t=\$(date +%s)' | python3 -m json.tool | grep -A6 '\"baseline\"'"
echo "  Open /story/ — should see 'Continue the story' → /live/ at bottom"
echo "════════════════════════════════════════════════"
echo ""
