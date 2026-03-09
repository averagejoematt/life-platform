#!/bin/bash
# test_dashboard_local.sh — Open dashboard locally for visual verification
# Run from: ~/Documents/Claude/life-platform/
# Uses Python's built-in HTTP server to serve the dashboard files

set -euo pipefail

echo "Starting local dashboard server..."
echo "Open http://localhost:8899 in your browser"
echo "Press Ctrl+C to stop"
echo ""

cd lambdas/dashboard
python3 -m http.server 8899
