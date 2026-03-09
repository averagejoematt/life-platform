#!/bin/bash
# deploy_character_sheet_phase1.sh — v2.58.0
# Phase 1: Scoring engine + MCP tools + S3 config
#
# Deploys:
#   1. config/character_sheet.json → S3
#   2. MCP server Lambda — adds tools_character.py + character_engine.py
#
# Does NOT deploy Daily Brief (Phase 2) — character_engine.py will be
# bundled into Daily Brief in the next phase.
#
# Usage:
#   cd ~/Documents/Claude/life-platform
#   bash deploy/deploy_character_sheet_phase1.sh           # deploy all
#   bash deploy/deploy_character_sheet_phase1.sh --dry-run # preview only
set -euo pipefail

REGION="us-west-2"
BUCKET="matthew-life-platform"
PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
LAMBDAS_DIR="$PROJECT_DIR/lambdas"
MCP_DIR="$PROJECT_DIR/mcp"
CONFIG_DIR="$PROJECT_DIR/config"
TMP_DIR="/tmp/character_sheet_deploy"

DRY_RUN=false
if [ "${1:-}" = "--dry-run" ]; then
    DRY_RUN=true
    echo "*** DRY RUN — no changes will be made ***"
    echo ""
fi

echo "═══════════════════════════════════════════════════"
echo "  Character Sheet Phase 1 Deploy — v2.58.0"
echo "  Config + MCP tools + character_engine"
echo "═══════════════════════════════════════════════════"
echo ""

# ── Verify files exist ──
echo "▸ Checking required files..."
REQUIRED_FILES=(
    "$CONFIG_DIR/character_sheet.json"
    "$MCP_DIR/tools_character.py"
    "$LAMBDAS_DIR/character_engine.py"
    "$MCP_DIR/registry.py"
    "$PROJECT_DIR/mcp_server.py"
    "$PROJECT_DIR/mcp_bridge.py"
)
for f in "${REQUIRED_FILES[@]}"; do
    if [ ! -f "$f" ]; then
        echo "  ❌ MISSING: $f"
        exit 1
    fi
    echo "  ✓ $(basename "$f")"
done
echo ""

# ── Step 1: Upload config to S3 ──
echo "▸ [1/2] Uploading character_sheet.json to S3..."
echo "  s3://$BUCKET/config/character_sheet.json"
if [ "$DRY_RUN" = true ]; then
    echo "  [DRY RUN] Would upload config"
else
    aws s3 cp "$CONFIG_DIR/character_sheet.json" \
        "s3://$BUCKET/config/character_sheet.json" \
        --region "$REGION" \
        --content-type "application/json" \
        --no-cli-pager
    echo "  ✓ Config uploaded"
fi
echo ""

# ── Step 2: Deploy MCP Lambda ──
echo "▸ [2/2] Packaging MCP Lambda with character tools..."
rm -rf "$TMP_DIR" && mkdir -p "$TMP_DIR"

# Copy all MCP server files
cp "$PROJECT_DIR/mcp_server.py" "$TMP_DIR/"
cp "$PROJECT_DIR/mcp_bridge.py" "$TMP_DIR/"
cp -r "$MCP_DIR" "$TMP_DIR/mcp"

# Bundle character_engine.py (importable utility, same as board_loader.py)
cp "$LAMBDAS_DIR/character_engine.py" "$TMP_DIR/"
# Also copy board_loader.py (already bundled in MCP Lambda)
if [ -f "$LAMBDAS_DIR/board_loader.py" ]; then
    cp "$LAMBDAS_DIR/board_loader.py" "$TMP_DIR/"
fi

# Create zip
cd "$TMP_DIR"
ZIP_FILE="$TMP_DIR/mcp-server.zip"
zip -qr "$ZIP_FILE" . -x "__pycache__/*" "*.pyc"
cd "$PROJECT_DIR"

ZIP_SIZE=$(du -h "$ZIP_FILE" | cut -f1)
FILE_COUNT=$(unzip -l "$ZIP_FILE" | tail -1 | awk '{print $2}')
echo "  Zip: $ZIP_SIZE ($FILE_COUNT files)"
echo "  Contents:"
unzip -l "$ZIP_FILE" | grep -E "tools_character|character_engine|registry" | awk '{print "    " $4}'

if [ "$DRY_RUN" = true ]; then
    echo "  [DRY RUN] Would deploy life-platform-mcp"
else
    aws lambda update-function-code \
        --function-name "life-platform-mcp" \
        --zip-file "fileb://$ZIP_FILE" \
        --region "$REGION" \
        --output text \
        --query 'FunctionName' \
        --no-cli-pager
    echo "  ✓ MCP Lambda deployed"

    # Wait for propagation
    echo "  Waiting for function update..."
    aws lambda wait function-updated \
        --function-name "life-platform-mcp" \
        --region "$REGION" 2>/dev/null || true
    echo "  ✓ Function ready"
fi

# Cleanup
rm -rf "$TMP_DIR"

echo ""
echo "═══════════════════════════════════════════════════"
if [ "$DRY_RUN" = true ]; then
    echo "  DRY RUN complete"
else
    echo "  ✅ Phase 1 deployed!"
    echo ""
    echo "  Config: s3://$BUCKET/config/character_sheet.json"
    echo "  MCP: life-platform-mcp (102 → 105 tools)"
fi
echo "═══════════════════════════════════════════════════"
echo ""
echo "Next steps:"
echo "  1. Run backfill (dry run first):"
echo "     cd ~/Documents/Claude/life-platform"
echo "     python3 backfill/retrocompute_character_sheet.py --stats"
echo "     python3 backfill/retrocompute_character_sheet.py"
echo "     python3 backfill/retrocompute_character_sheet.py --write"
echo ""
echo "  2. Verify MCP tools:"
echo "     Ask Claude: 'show me my character sheet'"
echo ""
echo "  3. Warm cache (or wait for 9 AM PT nightly run):"
echo "     aws lambda invoke --function-name life-platform-mcp \\"
echo "       --payload '{\"type\":\"cache_warmup\"}' \\"
echo "       --cli-binary-format raw-in-base64-out \\"
echo "       --region $REGION /tmp/warm.json"
