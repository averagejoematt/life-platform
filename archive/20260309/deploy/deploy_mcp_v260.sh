#!/bin/bash
# Copy updated mcp_server.py v2.6.0 into place, then deploy
# Run from ~/Documents/Claude/life-platform/

set -e

# mcp_server.py must already be updated in this directory.
# If applying from a downloaded file, copy it first:
#   cp ~/Downloads/mcp_server_v260.py mcp_server.py

echo "=== Deploying MCP server v2.6.0 ==="
./deploy_mcp.sh

echo ""
echo "=== Done. Verify in Claude Desktop: ==="
echo "  get_garmin_summary          (new tool — Garmin biometrics)"
echo "  get_device_agreement        (new tool — Whoop vs Garmin validation)"
echo "  get_readiness_score         (updated — 5 components + device_agreement)"
