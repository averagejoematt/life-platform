#!/usr/bin/env bash
# scripts/update_architecture_header.sh — Auto-update ARCHITECTURE.md header counts
#
# Counts Lambda functions and MCP tools from source of truth (CDK stacks + mcp/)
# and rewrites the ARCHITECTURE.md header line.
#
# Triggered:
#   - Manually: bash scripts/update_architecture_header.sh
#   - Automatically: .git/hooks/pre-commit (install with scripts/install_hooks.sh)
#
# New Lambdas since last commit are listed in the output (git history signal).
#
# v1.0.0 — 2026-03-10 (Item 3, board review sprint v3.5.0)

set -euo pipefail

PROJ_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CDK_DIR="$PROJ_ROOT/cdk/stacks"
MCP_DIR="$PROJ_ROOT/mcp"
ARCH_FILE="$PROJ_ROOT/docs/ARCHITECTURE.md"

if [[ ! -f "$ARCH_FILE" ]]; then
  echo "[ERROR] ARCHITECTURE.md not found at $ARCH_FILE"
  exit 1
fi

# ── Count Lambdas from CDK stacks ─────────────────────────────────────────────
# Count unique `function_name=` entries across all stack files (source of truth)
LAMBDA_COUNT=$(grep -rh 'function_name=' "$CDK_DIR"/*.py 2>/dev/null | \
  grep -v '^\s*#' | \
  sed 's/.*function_name="\([^"]*\)".*/\1/' | \
  sort -u | wc -l | tr -d ' ')

# Fallback: count create_platform_lambda calls if function_name= grep is thin
if [[ "$LAMBDA_COUNT" -lt 5 ]]; then
  LAMBDA_COUNT=$(grep -rh 'create_platform_lambda\|aws_lambda.Function(' "$CDK_DIR"/*.py 2>/dev/null | \
    grep -v '^\s*#' | wc -l | tr -d ' ')
fi

# ── Count MCP tools from mcp/ modules ─────────────────────────────────────────
# Each tool is defined as a dict entry with "name": key
MCP_TOOL_COUNT=$(grep -rh '"name":\s*"' "$MCP_DIR"/*.py 2>/dev/null | \
  grep -v '^\s*#' | \
  sed 's/.*"name":\s*"\([^"]*\)".*/\1/' | \
  sort -u | wc -l | tr -d ' ')

# Fallback: count TOOL definitions if dict parsing is thin
if [[ "$MCP_TOOL_COUNT" -lt 10 ]]; then
  MCP_TOOL_COUNT=$(grep -rh '"name":\s*"get_\|"name":\s*"log_\|"name":\s*"list_\|"name":\s*"update_\|"name":\s*"create_\|"name":\s*"delete_\|"name":\s*"search_\|"name":\s*"set_\|"name":\s*"remove_\|"name":\s*"query_' \
    "$MCP_DIR"/*.py 2>/dev/null | wc -l | tr -d ' ')
fi

# ── Count data sources from ARCHITECTURE.md (manual reference count) ──────────
# Data sources are listed in the header — extract current value to preserve it
CURRENT_HEADER=$(grep "^Last updated:" "$ARCH_FILE" | head -1 || echo "")
CURRENT_SOURCES=$(echo "$CURRENT_HEADER" | grep -o '[0-9]* data sources' | grep -o '[0-9]*' || echo "19")

TODAY=$(date +%Y-%m-%d)
VERSION=$(cd "$PROJ_ROOT" && git describe --tags --abbrev=0 2>/dev/null || \
          grep -m1 "^## v" "$PROJ_ROOT/docs/CHANGELOG.md" 2>/dev/null | grep -o 'v[0-9.]*' | head -1 || \
          echo "v3.5.x")
VERSION="${VERSION#v}"

NEW_HEADER="Last updated: ${TODAY} (v${VERSION} — ${MCP_TOOL_COUNT} tools, 31-module MCP package, ${CURRENT_SOURCES} data sources, ${LAMBDA_COUNT} Lambdas, 8 secrets, 42 alarms, 8 CDK stacks deployed)"

# ── Detect new Lambdas since last commit ─────────────────────────────────────
if command -v git &>/dev/null && git -C "$PROJ_ROOT" rev-parse HEAD &>/dev/null 2>&1; then
  PREV_LAMBDA_COUNT=$(git -C "$PROJ_ROOT" show HEAD:docs/ARCHITECTURE.md 2>/dev/null | \
    grep "^Last updated:" | grep -o '[0-9]* Lambdas' | grep -o '[0-9]*' || echo "")
  if [[ -n "$PREV_LAMBDA_COUNT" ]] && [[ "$LAMBDA_COUNT" -gt "$PREV_LAMBDA_COUNT" ]]; then
    NEW_LAMBDAS=$((LAMBDA_COUNT - PREV_LAMBDA_COUNT))
    echo "  📦 +${NEW_LAMBDAS} Lambda(s) since last commit (${PREV_LAMBDA_COUNT} → ${LAMBDA_COUNT})"
  fi
fi

# ── Rewrite header line ───────────────────────────────────────────────────────
CURRENT_LINE=$(grep "^Last updated:" "$ARCH_FILE" | head -1 || echo "")
if [[ "$CURRENT_LINE" == "$NEW_HEADER" ]]; then
  echo "  ✓ ARCHITECTURE.md header already current (${LAMBDA_COUNT} Lambdas, ${MCP_TOOL_COUNT} tools)"
  exit 0
fi

# Platform-agnostic sed in-place
if sed --version &>/dev/null 2>&1; then
  # GNU sed
  sed -i "s|^Last updated:.*|${NEW_HEADER}|" "$ARCH_FILE"
else
  # macOS BSD sed
  sed -i '' "s|^Last updated:.*|${NEW_HEADER}|" "$ARCH_FILE"
fi

echo "  ✅ ARCHITECTURE.md header updated:"
echo "     ${NEW_HEADER}"
