#!/bin/bash
set -euo pipefail

# ══════════════════════════════════════════════════════════════════════════════
# Notion Journal Phase 3 — MCP Tools Deploy
#
# 1. Patch MCP server with 5 journal tools
# 2. Deploy updated MCP Lambda
#
# Usage: bash deploy_journal_mcp_tools.sh
# ══════════════════════════════════════════════════════════════════════════════

cd ~/Documents/Claude/life-platform

echo "═══════════════════════════════════════════════════"
echo "  Journal MCP Tools (Phase 3) — Deploy"
echo "═══════════════════════════════════════════════════"
echo ""

# ── Step 1: Patch MCP server ─────────────────────────────────────────────────
echo "Step 1: Patching MCP server with journal tools..."
echo "──────────────────────────────────────────────────"
python3 patch_mcp_journal_tools.py
echo ""

# ── Step 2: Deploy MCP Lambda ────────────────────────────────────────────────
echo "Step 2: Deploying MCP Lambda..."
echo "───────────────────────────────"
bash deploy_mcp.sh
echo ""

echo "═══════════════════════════════════════════════════"
echo "  ✓ Journal MCP Tools (Phase 3) deployed!"
echo "═══════════════════════════════════════════════════"
echo ""
echo "  New tools (5):"
echo "    - get_journal_entries      : retrieve entries by date/template"
echo "    - search_journal           : full-text search across all entries"
echo "    - get_mood_trend           : mood/energy/stress over time + 7d avg"
echo "    - get_journal_insights     : cross-entry pattern analysis"
echo "    - get_journal_correlations : journal vs wearable data correlations"
echo ""
echo "  MCP Server: v2.16.0 (57 tools)"
echo ""
echo "  Next: Phase 4 (daily brief + weekly digest integration)"
echo ""
