#!/usr/bin/env bash
# deploy/validate_lambda_map.sh — every source file named in ci/lambda_map.json exists (#4885).
#
# Extracted verbatim from the ci-cd.yml `plan` job step "Validate lambda_map.json" so the logic
# is testable (tests/test_validate_lambda_map_4885.py) and the workflow stays small
# (tests/test_workflow_size_ratchet_4885.py). Pure file-existence logic: no secrets, no AWS.
#
# Usage: deploy/validate_lambda_map.sh   (run from the repo root; LAMBDA_MAP overrides the path)
set -u
MAP="${LAMBDA_MAP:-ci/lambda_map.json}"

echo "Validating ci/lambda_map.json..."
MISSING=0

echo "Checking Lambda source files..."
while IFS= read -r src; do
  if [ ! -f "$src" ]; then
    echo "  ❌ MISSING source: $src (in .lambdas — file not found in repo)"
    MISSING=$((MISSING + 1))
  fi
done < <(jq -r '.lambdas | keys[]' "$MAP")

if [ "$MISSING" -gt 0 ]; then
  echo "::error::lambda_map.json references $MISSING missing file(s). Update ci/lambda_map.json to match current repo state."
  exit 1
fi
echo "✅ lambda_map.json valid — all source files present"
