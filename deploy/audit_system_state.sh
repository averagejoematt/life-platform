#!/bin/bash
set -euo pipefail

# audit_system_state.sh — Run before architecture reviews to verify doc accuracy.
# Reports actual AWS state vs documented counts in ARCHITECTURE.md, RUNBOOK.md, SCHEMA.md.

echo "=== Life Platform System State Audit ==="
echo "Date: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo ""

# Lambda counts
WEST_COUNT=$(aws lambda list-functions --region us-west-2 --query 'Functions[].FunctionName' --output text --no-cli-pager | tr '\t' '\n' | grep -v '^serverlessrepo' | grep -c . || echo 0)
EAST_COUNT=$(aws lambda list-functions --region us-east-1 --query 'Functions[].FunctionName' --output text --no-cli-pager | tr '\t' '\n' | grep -c . || echo 0)
TOTAL_LAMBDAS=$((WEST_COUNT + EAST_COUNT))
echo "Lambdas:      $TOTAL_LAMBDAS ($WEST_COUNT us-west-2 + $EAST_COUNT us-east-1)"

# MCP tool count
TOOL_COUNT=$(grep -c '"name":' mcp/registry.py 2>/dev/null || echo "?")
echo "MCP tools:    $TOOL_COUNT"

# MCP module count
MODULE_COUNT=$(ls mcp/tools_*.py 2>/dev/null | wc -l | tr -d ' ')
echo "MCP modules:  $MODULE_COUNT"

# Site pages
PAGE_COUNT=$(find site/ -name 'index.html' 2>/dev/null | wc -l | tr -d ' ')
echo "Site pages:   $PAGE_COUNT"

# Data sources (from SCHEMA.md)
SOURCE_COUNT=$(grep -c "SOURCE#" docs/SCHEMA.md 2>/dev/null || echo "?")
echo "Data sources: $SOURCE_COUNT (from SCHEMA.md)"

# CDK stacks
if [ -d "cdk" ]; then
  STACK_COUNT=$(cd cdk && npx cdk list 2>/dev/null | wc -l | tr -d ' '; cd ..)
  echo "CDK stacks:   $STACK_COUNT"
fi

echo ""
echo "=== Doc Header Comparison ==="

# Check each doc
for DOC in docs/ARCHITECTURE.md docs/RUNBOOK.md docs/SCHEMA.md CLAUDE.md; do
  if [ -f "$DOC" ]; then
    HEADER=$(head -5 "$DOC" | grep -i "updated\|tools\|lambda" | head -1 || echo "(no header)")
    echo "$DOC:"
    echo "  $HEADER"
  fi
done

echo ""
echo "=== Audit complete ==="
