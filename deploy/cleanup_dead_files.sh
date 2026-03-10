#!/usr/bin/env bash
# cleanup_dead_files.sh — Remove dead/stale files identified in Architecture Review #4
# Run once from project root, then delete this script.
# v3.4.2 — 2026-03-10

set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

echo "Deleting dead files..."

# weather_lambda.py.archived — replaced by weather_handler.py + weather_lambda.py (active)
rm -f "$ROOT/lambdas/weather_lambda.py.archived"
echo "  ✓ Deleted lambdas/weather_lambda.py.archived"

# freshness_checker.py — dead stub; active Lambda is freshness_checker_lambda.py
rm -f "$ROOT/lambdas/freshness_checker.py"
echo "  ✓ Deleted lambdas/freshness_checker.py"

# Self-destruct after use
rm -f "$0"
echo "  ✓ Self-removed cleanup_dead_files.sh"

echo "Done."
