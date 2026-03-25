#!/bin/bash
# deploy_habits_overhaul.sh — Habits page Phase A/B/C overhaul
# Run from project root: bash deploy/deploy_habits_overhaul.sh

set -euo pipefail

echo "═══ Habits Page Overhaul — Phase A/B/C ═══"
echo ""

# 1. Backup current page
echo "📦 Backing up current habits page..."
cp site/habits/index.html site/habits/index.html.bak.$(date +%Y%m%d)
echo "   → Backup saved"

# 2. Copy new page (assumes you've already copied the file from Claude's output)
# If the file is at ~/Downloads/habits_index.html:
# cp ~/Downloads/habits_index.html site/habits/index.html
echo ""
echo "⚠️  Copy the new habits page to site/habits/index.html"
echo "   From Claude output or ~/Downloads/habits_index.html"
echo ""

# 3. Deploy to S3
echo "🚀 Deploying to S3..."
aws s3 sync site/ s3://matthew-life-platform/site/ --delete
echo "   → S3 sync complete"

# 4. Invalidate CloudFront
echo "🔄 Invalidating CloudFront cache..."
aws cloudfront create-invalidation \
  --distribution-id E3S424OXQZ8NBE \
  --paths "/habits/*"
echo "   → Invalidation submitted"

echo ""
echo "✅ Habits page overhaul deployed!"
echo "   → https://averagejoematt.com/habits/"
echo ""
echo "Changes:"
echo "  • Renamed: 'Habit Observatory' → 'The Operating System'"
echo "  • Three-zone architecture: Foundation → System → Horizon"
echo "  • 21 supplement habits removed (live on /supplements/)"
echo "  • 7 hygiene habits removed (maintenance, not transformation)"
echo "  • Purpose-grouped Tier 1 with collapsible accordions"
echo "  • Faded/locked Tier 2 horizon cards"
echo "  • SVG progress rings on T0 habit cards"
echo "  • Sparklines on every T0 card"
echo "  • Science rationale + evidence badges per habit"
echo "  • Daily pipeline visualization"
echo "  • Intelligence layer (heatmap, correlations, DOW, fatigue)"
echo "  • Vice Discipline Gates with streak cards"
echo "  • No new API endpoints needed — uses existing /api/habits + /api/vice_streaks"
