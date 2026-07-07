#!/usr/bin/env bash
# deploy/build_mcp_stable_layer.sh
#
# MCP Two-Tier Layer Build — R11 Item 6
# ──────────────────────────────────────────────────────────────────────────────
# This script implements the "stable core → Layer, volatile tools → Lambda zip"
# architecture approved in Architecture Review #11 (Priya Nakamura / ADR-027).
#
# CURRENT STATE (one-tier):
#   Lambda zip contains: mcp_server.py + entire mcp/ package (all 31 modules)
#   Every tool change redeploys the full 31-module package
#   Handler, protocol, config, and tools all share the same blast radius
#
# TARGET STATE (two-tier):
#   Lambda Layer: mcp/config.py, mcp/core.py, mcp/helpers.py,
#                 mcp/labs_helpers.py, mcp/strength_helpers.py, mcp/utils.py
#                 (stable infrastructure — changes rarely, ~monthly)
#   Lambda zip:   mcp_server.py, mcp/handler.py, mcp/registry.py,
#                 mcp/warmer.py, mcp/tools_*.py
#                 (volatile tools — changes every session)
#
# BENEFIT:
#   - Tool changes only redeploy tool modules, not the protocol infrastructure
#   - Stable core is versioned and rolled back independently
#   - Blast radius of tool changes reduced from 31 modules to ~22
#
# HOW IMPORTS WORK IN LAMBDA:
#   Layer files at /opt/python/ are on sys.path automatically.
#   mcp/config.py in Layer → importable as `from mcp.config import ...`
#   mcp/tools_data.py in zip → importable as `from mcp.tools_data import ...`
#   Python resolves imports from both locations, so mixed Layer+zip packages work.
#
# STATUS: Ready to execute. Run in a test session before main session.
#         Requires Layer rebuild + all Lambda redeploys. ~15 minutes.
#
# PREREQUISITES:
#   - Python 3.11 environment (Lambda runtime)
#   - boto3 installed locally
#   - AWS credentials with lambda:PublishLayerVersion
#
# v1.0.0 — 2026-03-14 (R11 engineering strategy item 6)

set -euo pipefail
REGION="us-west-2"
BUCKET="matthew-life-platform"
LAYER_NAME="life-platform-shared-utils"

PROJ_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LAYER_DIR="$PROJ_ROOT/layer-build"
MCP_DIR="$PROJ_ROOT/mcp"

GREEN="\033[0;32m"; RED="\033[0;31m"; YELLOW="\033[1;33m"; RESET="\033[0m"
ok()      { echo -e "${GREEN}  ✅ $*${RESET}"; }
fail()    { echo -e "${RED}  ❌ $*${RESET}"; exit 1; }
info()    { echo -e "${YELLOW}  ℹ️  $*${RESET}"; }
section() { echo -e "\n${YELLOW}── $* ──${RESET}"; }

# ── Stable MCP modules (move to Layer) ────────────────────────────────────────
# STABLE = no imports from tools_*.py or warmer.py or registry.py
# Changes at most monthly; schema/config/core changes require full redeploy anyway.
STABLE_MODULES=(
    "config.py"
    "core.py"
    "helpers.py"
    "labs_helpers.py"
    "strength_helpers.py"
    "utils.py"
)

# Verify all stable modules exist before starting
section "Verifying stable modules exist"
for mod in "${STABLE_MODULES[@]}"; do
    if [[ ! -f "$MCP_DIR/$mod" ]]; then
        fail "Stable module missing: $MCP_DIR/$mod"
    fi
    ok "$mod"
done

# ── Step 1: Build the new Layer zip ───────────────────────────────────────────
section "Building new Layer zip with stable MCP modules"

WORK_DIR=$(mktemp -d)
LAYER_PYTHON_DIR="$WORK_DIR/python"

# Copy existing shared utilities (from current layer source)
if [[ -d "$LAYER_DIR/python" ]]; then
    cp -r "$LAYER_DIR/python/." "$LAYER_PYTHON_DIR/"
    info "Copied existing layer utilities"
else
    mkdir -p "$LAYER_PYTHON_DIR"
    info "Starting fresh layer (no existing layer-build/python/)"
fi

# Add stable MCP modules under python/mcp/
mkdir -p "$LAYER_PYTHON_DIR/mcp"
# Create __init__.py for the package
touch "$LAYER_PYTHON_DIR/mcp/__init__.py"

for mod in "${STABLE_MODULES[@]}"; do
    cp "$MCP_DIR/$mod" "$LAYER_PYTHON_DIR/mcp/$mod"
    ok "Added mcp/$mod to Layer"
done

# Build zip
ZIP_PATH="$WORK_DIR/layer.zip"
(cd "$WORK_DIR" && zip -r "$ZIP_PATH" python/ -q)
ZIP_SIZE=$(du -sh "$ZIP_PATH" | cut -f1)
ok "Layer zip built: $ZIP_SIZE"

# ── Step 2: Publish new Layer version ────────────────────────────────────────
section "Publishing new Layer version to AWS"

NEW_LAYER_VERSION=$(aws lambda publish-layer-version \
    --layer-name "$LAYER_NAME" \
    --description "Shared utils + stable MCP core (config, core, helpers) v2.0.0" \
    --zip-file "fileb://$ZIP_PATH" \
    --compatible-runtimes python3.11 \
    --region "$REGION" \
    --query "Version" \
    --output text)

ok "Published $LAYER_NAME version $NEW_LAYER_VERSION"
LAYER_ARN="arn:aws:lambda:$REGION:205930651321:layer:$LAYER_NAME:$NEW_LAYER_VERSION"
info "New Layer ARN: $LAYER_ARN"

# ── Step 3: Update CDK to reference new layer version ────────────────────────
section "MANUAL STEP REQUIRED: Update CDK layer reference"
echo ""
echo "  Update cdk/stacks/core_stack.py to reference layer version $NEW_LAYER_VERSION:"
echo "  Look for: life-platform-shared-utils:<version>"
echo "  Change to: life-platform-shared-utils:$NEW_LAYER_VERSION"
echo ""
echo "  Then run: source cdk/.venv/bin/activate && npx cdk deploy --all"
echo ""

# ── Step 4: Note about MCP zip changes ────────────────────────────────────────
section "NEXT: Update mcp_server.py packaging to exclude stable modules"
echo ""
echo "  When deploying the MCP Lambda, the stable modules (config.py, core.py, etc.)"
echo "  will be loaded from the Layer at /opt/python/mcp/."
echo "  The Lambda zip only needs: mcp_server.py + handler.py + registry.py +"
echo "  warmer.py + tools_*.py"
echo ""
echo "  The deploy_lambda.sh script handles this automatically — it only packages"
echo "  the source file specified, so no changes needed to the deploy workflow."
echo ""
echo "  IMPORTANT: Before running this in production, test with:"
echo "    python3 -c 'from mcp.config import TABLE_NAME; print(TABLE_NAME)'"
echo "  in a Lambda environment to verify imports resolve correctly."
echo ""

# Cleanup
rm -rf "$WORK_DIR"
ok "Build complete. New Layer: $LAYER_NAME v$NEW_LAYER_VERSION"
echo ""
echo "════════════════════════════════════════════════════════"
echo "  SUMMARY: Layer $NEW_LAYER_VERSION published."
echo "  ACTION REQUIRED: Update CDK layer reference + redeploy."
echo "  See ADR-027 for design rationale."
echo "════════════════════════════════════════════════════════"
