#!/usr/bin/env bash
# deploy/bump_ci_actions.sh — Bump GitHub Actions to Node 24 versions
# Node 20 actions deprecate June 2026. This brings ci-cd.yml fully current.
#
# Bumps:
#   actions/checkout    v4 → v6  (Node 24, released Dec 2025)
#   actions/setup-python v5 → v6 (Node 24, released Nov 2025)
#   aws-actions/configure-aws-credentials@v4 — stays (no v5 released yet)
#
# Usage: bash deploy/bump_ci_actions.sh
# Idempotent — safe to re-run.

set -e
WORKFLOW=".github/workflows/ci-cd.yml"

echo "=== CI Actions Node 24 bump ==="
echo ""

BEFORE_CO=$(grep -c "actions/checkout@v4"    "$WORKFLOW" 2>/dev/null || echo 0)
BEFORE_PY=$(grep -c "actions/setup-python@v5" "$WORKFLOW" 2>/dev/null || echo 0)

# macOS BSD sed requires empty string for -i
sed -i '' 's|actions/checkout@v4|actions/checkout@v6|g'     "$WORKFLOW"
sed -i '' 's|actions/setup-python@v5|actions/setup-python@v6|g' "$WORKFLOW"

AFTER_CO=$(grep -c "actions/checkout@v6"    "$WORKFLOW" 2>/dev/null || echo 0)
AFTER_PY=$(grep -c "actions/setup-python@v6" "$WORKFLOW" 2>/dev/null || echo 0)

echo "actions/checkout:     $BEFORE_CO occurrences → now @v6 ($AFTER_CO)"
echo "actions/setup-python: $BEFORE_PY occurrences → now @v6 ($AFTER_PY)"
echo ""

# Confirm configure-aws-credentials stays
CREDS=$(grep -c "configure-aws-credentials@v4" "$WORKFLOW" 2>/dev/null || echo 0)
echo "configure-aws-credentials: $CREDS occurrences at @v4 (latest — no action needed)"
echo ""

echo "=== Verify — all action versions now in CI ==="
grep -n "actions/checkout\|setup-python\|configure-aws-credentials" "$WORKFLOW"
echo ""
echo "✅ Done. Commit with:"
echo "   git add .github/workflows/ci-cd.yml && git commit -m 'ci: bump actions to Node 24 (checkout@v6, setup-python@v6)'"
