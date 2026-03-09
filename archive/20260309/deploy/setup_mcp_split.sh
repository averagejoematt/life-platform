#!/usr/bin/env bash
# setup_mcp_split.sh — Extract MCP package split and prepare for deployment
#
# Prerequisites:
#   1. Download mcp_package_delivery.tar.gz from Claude
#   2. Move/copy it to the project root: ~/Documents/Claude/life-platform/
#   3. Run this script: ./deploy/setup_mcp_split.sh
#
# What this does:
#   1. Backs up the original monolith to mcp_server_monolith.py.bak
#   2. Extracts the mcp/ package (21 modules)
#   3. Replaces mcp_server.py with thin entry point
#   4. Copies deploy scripts
#   5. Runs syntax check on all modules
#   6. Tells you what to do next
#
# Rollback:
#   cp mcp_server_monolith.py.bak mcp_server.py && rm -rf mcp/
#   Then run: ./deploy/deploy_mcp.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
TAR_FILE="$PROJECT_DIR/mcp_package_delivery.tar.gz"

info()  { echo "[INFO]  $*"; }
warn()  { echo "[WARN]  $*"; }
error() { echo "[ERROR] $*" >&2; exit 1; }

cd "$PROJECT_DIR"

# ── 0. Verify tar exists ─────────────────────────────────────────────────────
[ -f "$TAR_FILE" ] || error "mcp_package_delivery.tar.gz not found in $PROJECT_DIR. Download it from Claude first."

# ── 1. Backup the monolith ───────────────────────────────────────────────────
if [ -f "mcp_server.py" ]; then
    LINE_COUNT=$(wc -l < mcp_server.py | tr -d ' ')
    if [ "$LINE_COUNT" -gt 100 ]; then
        info "Backing up monolith mcp_server.py ($LINE_COUNT lines) → mcp_server_monolith.py.bak"
        cp mcp_server.py mcp_server_monolith.py.bak
    else
        info "mcp_server.py is already small ($LINE_COUNT lines) — skipping backup"
    fi
fi

# ── 2. Extract the package ───────────────────────────────────────────────────
info "Extracting mcp_package_delivery.tar.gz..."
tar xzf "$TAR_FILE"

# ── 3. Verify extraction ─────────────────────────────────────────────────────
MODULE_COUNT=$(find mcp -name "*.py" | wc -l | tr -d ' ')
[ "$MODULE_COUNT" -ge 20 ] || error "Expected 21+ modules in mcp/, found $MODULE_COUNT"
[ -f "mcp/__init__.py" ]    || error "mcp/__init__.py missing"
[ -f "mcp/registry.py" ]    || error "mcp/registry.py missing"
[ -f "mcp/handler.py" ]     || error "mcp/handler.py missing"
info "Extracted $MODULE_COUNT modules to mcp/"

# ── 4. Verify entry point ────────────────────────────────────────────────────
ENTRY_LINES=$(wc -l < mcp_server.py | tr -d ' ')
if [ "$ENTRY_LINES" -gt 50 ]; then
    error "mcp_server.py has $ENTRY_LINES lines — extraction may have failed"
fi
info "Entry point: $ENTRY_LINES lines ✓"

# ── 5. Syntax check ──────────────────────────────────────────────────────────
info "Syntax checking all modules..."
ERRORS=0
for f in mcp_server.py mcp/*.py; do
    if ! python3 -c "import py_compile; py_compile.compile('$f', doraise=True)" 2>/dev/null; then
        echo "  ❌ $f"
        ERRORS=$((ERRORS + 1))
    fi
done
if [ "$ERRORS" -gt 0 ]; then
    error "$ERRORS file(s) failed syntax check!"
fi
info "All $MODULE_COUNT modules compile clean ✓"

# ── 6. Make deploy scripts executable ────────────────────────────────────────
chmod +x deploy/deploy_mcp_split.sh 2>/dev/null || true
chmod +x deploy/deploy_unified.sh 2>/dev/null || true

# ── 7. Summary ───────────────────────────────────────────────────────────────
echo ""
info "═══════════════════════════════════════════════════════════════"
info "MCP split extraction complete!"
info ""
info "  Files:"
info "    mcp_server.py           — thin entry point ($ENTRY_LINES lines)"
info "    mcp/                    — package with $MODULE_COUNT modules"
info "    mcp_server_monolith.py.bak — original backup (rollback target)"
info ""
info "  Next steps:"
info "    1. Deploy:  ./deploy/deploy_mcp_split.sh"
info "    2. Restart Claude Desktop (new code needs fresh Lambda instance)"
info "    3. Test a few MCP tools to verify"
info ""
info "  Rollback:"
info "    cp mcp_server_monolith.py.bak mcp_server.py && rm -rf mcp/"
info "    ./deploy/deploy_mcp.sh"
info "═══════════════════════════════════════════════════════════════"
