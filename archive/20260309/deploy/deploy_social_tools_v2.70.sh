#!/usr/bin/env bash
# deploy_social_tools_v2.70.sh — Features #28, #35, #36, #40, #42
#
# Deploys 11 new MCP tools across 5 features:
#   - #40 Life Event Tagging (log_life_event, get_life_events)
#   - #42 Contact Frequency Tracking (log_interaction, get_social_dashboard)
#   - #35 Temptation Logging (log_temptation, get_temptation_trend)
#   - #36 Cold/Heat Exposure (log_exposure, get_exposure_log, get_exposure_correlation)
#   - #28 Exercise Variety Scoring (get_exercise_variety)
#
# Files changed:
#   mcp/config.py          — 4 new PK constants
#   mcp/registry.py        — import + 11 tool registrations
#   mcp/tools_social.py    — NEW (features #40, #42, #35, #36)
#   mcp/tools_training.py  — exercise variety function added
#
# Usage:
#   cd ~/Documents/Claude/life-platform
#   bash deploy/deploy_social_tools_v2.70.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

echo "═══════════════════════════════════════════════════"
echo "  Social & Behavioral Tools Deploy — v2.70.0"
echo "  5 features, 11 new MCP tools"
echo "  105 → 116 tools"
echo "═══════════════════════════════════════════════════"
echo ""

# Verify new file exists
if [ ! -f "$PROJECT_DIR/mcp/tools_social.py" ]; then
    echo "❌ ERROR: mcp/tools_social.py not found"
    exit 1
fi

echo "✓ mcp/tools_social.py exists"
echo "✓ mcp/config.py (4 new PKs: LIFE_EVENTS_PK, INTERACTIONS_PK, TEMPTATIONS_PK, EXPOSURES_PK)"
echo "✓ mcp/registry.py (11 new tool registrations)"
echo "✓ mcp/tools_training.py (tool_get_exercise_variety added)"
echo ""

# Deploy using the existing split deploy script
echo "Deploying MCP server..."
cd "$PROJECT_DIR"
bash deploy/deploy_mcp_split.sh

echo ""
echo "═══════════════════════════════════════════════════"
echo "  ✅ Deploy complete!"
echo ""
echo "  New tools (11):"
echo "    #40 Life Events:    log_life_event, get_life_events"
echo "    #42 Social:         log_interaction, get_social_dashboard"
echo "    #35 Temptation:     log_temptation, get_temptation_trend"
echo "    #36 Exposure:       log_exposure, get_exposure_log, get_exposure_correlation"
echo "    #28 Variety:        get_exercise_variety"
echo ""
echo "  New DDB partitions (4):"
echo "    USER#matthew#SOURCE#life_events"
echo "    USER#matthew#SOURCE#interactions"
echo "    USER#matthew#SOURCE#temptations"
echo "    USER#matthew#SOURCE#exposures"
echo ""
echo "  Quick test:"
echo "    # In Claude Desktop or claude.ai:"
echo "    log_life_event title='Platform v2.70 deployed' type='achievement'"
echo "═══════════════════════════════════════════════════"
