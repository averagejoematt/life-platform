#!/bin/bash
# install_gap_fill.sh — Copy gap-fill lambda files into place, then deploy
# Run this AFTER downloading the gap-fill-lambdas folder from Claude outputs
#
# Usage: bash ~/Documents/Claude/life-platform/deploy/install_gap_fill.sh

set -euo pipefail

LAMBDAS_DIR="$HOME/Documents/Claude/life-platform/lambdas"
# Update this path to wherever you downloaded the files:
SOURCE_DIR="$HOME/Downloads/gap-fill-lambdas"

echo "Copying gap-fill lambda files..."
for f in whoop_lambda.py eightsleep_lambda.py strava_lambda.py withings_lambda.py habitify_lambda.py; do
  if [ -f "$SOURCE_DIR/$f" ]; then
    cp "$SOURCE_DIR/$f" "$LAMBDAS_DIR/$f"
    echo "  ✅ $f"
  else
    echo "  ⚠️  $f not found in $SOURCE_DIR"
  fi
done

echo ""
echo "Now deploying..."
bash "$HOME/Documents/Claude/life-platform/deploy/deploy_gap_fill.sh"
