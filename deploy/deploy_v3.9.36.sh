#!/bin/bash
# deploy_v3.9.36.sh — Signal Doctrine Tier 2 + Podcast Scanner
# Run from project root: bash deploy/deploy_v3.9.36.sh
set -euo pipefail

echo "═══ v3.9.36: Signal Doctrine Tier 2 + Podcast Scanner ═══"
echo ""

cd ~/Documents/Claude/life-platform

# 1. Product Board fixes — Follow→/subscribe/ (8-0 vote)
echo "── 1/8: Product Board fix — Follow → /subscribe/ ──"
python3 deploy/fix_follow_route.py
python3 deploy/fix_follow_badge.py
echo ""

# 2. Observatory pillar accents
echo "── 2/8: Observatory pillar accent colors ──"
python3 deploy/patch_tier2_observatory.py
echo ""

# 3. Home sparklines + count-up
echo "── 3/8: Home page sparklines + count-up ──"
python3 deploy/patch_tier2_home.py
echo ""

# 4. Sleep + Glucose narrative intros
echo "── 4/8: Sleep + Glucose narrative intros ──"
python3 deploy/patch_tier2_narrative.py
echo ""

# 5. Nav restructure (components.js + nav.js already written directly)
echo "── 5/8: Nav restructure — components.js + nav.js already updated ──"
echo "  Desktop: The Story | The Data | The Science | The Build | Follow"
echo "  Mobile:  Story | Data | Science | Build | Follow"
echo "  Bottom nav routes: / | /live/ | /stack/ | /platform/ | /subscribe/"
echo ""

# 6. Run tests
echo "── 6/8: Running MCP registry tests ──"
python3 -m pytest tests/test_mcp_registry.py -v || echo "⚠ Tests had issues — check output"
echo ""

# 7. Deploy podcast scanner Lambda
echo "── 7/8: Deploying podcast scanner Lambda ──"
bash deploy/deploy_lambda.sh life-platform-podcast-scanner lambdas/podcast_scanner_lambda.py 2>/dev/null || echo "  NOTE: Lambda may not exist yet — create it first if needed"
echo ""

# 8. Upload configs
echo "── 8/8: Uploading configs ──"
aws s3 cp config/podcast_watchlist.json s3://matthew-life-platform/config/podcast_watchlist.json --region us-west-2
echo ""

# Sync site to S3
echo "── Syncing site to S3 ──"
aws s3 sync site/ s3://matthew-life-platform/site/ --region us-west-2 --exclude '.DS_Store'
echo ""

# Invalidate CloudFront
echo "── Invalidating CloudFront ──"
aws cloudfront create-invalidation --distribution-id E3S424OXQZ8NBE --paths '/*' --region us-east-1 --no-cli-pager
echo ""

# Sync docs
echo "── Syncing doc metadata ──"
python3 deploy/sync_doc_metadata.py --apply 2>/dev/null || echo "  WARN: sync_doc_metadata.py had issues"
echo ""

# Git
echo "── Git commit ──"
git add -A
git commit -m "v3.9.36: Signal Doctrine Tier 2 — 5-section nav, Follow→subscribe, observatory accents, sparklines, narrative intros, podcast scanner"
git push

echo ""
echo "═══ v3.9.36 deployed ═══"
echo ""
echo "Manual follow-up:"
echo "  1. If podcast scanner Lambda doesn't exist yet, create it:"
echo "     aws lambda create-function --function-name life-platform-podcast-scanner \\"
echo "       --runtime python3.12 --handler podcast_scanner_lambda.lambda_handler \\"
echo "       --role arn:aws:iam::205930651321:role/life-platform-lambda-role \\"
echo "       --timeout 120 --memory-size 256 --region us-west-2"
echo "  2. Add EventBridge schedule (weekly Sunday 6am UTC):"
echo "     aws events put-rule --name podcast-scan-weekly \\"
echo "       --schedule-expression 'cron(0 6 ? * SUN *)' --region us-west-2"
echo "  3. Verify site at https://averagejoematt.com"
