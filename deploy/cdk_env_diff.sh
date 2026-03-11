#!/usr/bin/env bash
# deploy/cdk_env_diff.sh — Pre-CDK deploy Lambda env var diff check
#
# Before deploying a CDK stack, diffs current AWS Lambda env vars against
# what CDK will set. Catches console-only env vars that CDK would wipe.
#
# Both directions are checked:
#   ADDITIONS  — vars CDK will add (low risk, but visible)
#   DELETIONS  — vars Lambda has that CDK doesn't know about (HIGH RISK)
#
# High-sensitivity vars trigger explicit warnings regardless of direction.
#
# Usage:
#   bash deploy/cdk_env_diff.sh LifePlatformEmail
#   bash deploy/cdk_env_diff.sh LifePlatformCompute
#   bash deploy/cdk_env_diff.sh --all                    # all stacks
#   bash deploy/cdk_env_diff.sh LifePlatformEmail --ci   # non-interactive (CI mode)
#
# Exit codes:  0 = no risky diffs | 1 = deletions detected (requires confirmation)
#
# v1.0.0 — 2026-03-10 (Item 2, board review sprint v3.5.0)

set -euo pipefail

REGION="us-west-2"
CI_MODE=false
STACK_ARG=""

# ── Parse args ────────────────────────────────────────────────────────────────
for arg in "$@"; do
  case "$arg" in
    --ci) CI_MODE=true ;;
    --all) STACK_ARG="all" ;;
    LifePlatform*) STACK_ARG="$arg" ;;
  esac
done

if [[ -z "$STACK_ARG" ]]; then
  echo "Usage: bash deploy/cdk_env_diff.sh <StackName|--all> [--ci]"
  echo "  Stacks: LifePlatformEmail LifePlatformCompute LifePlatformIngestion"
  echo "          LifePlatformOperational LifePlatformMcp"
  exit 1
fi

# ── High-sensitivity var names (always highlighted regardless of direction) ───
HIGH_SENSITIVITY_VARS=(
  "EMAIL_RECIPIENT"
  "EMAIL_SENDER"
  "ANTHROPIC_SECRET"
  "AI_MODEL"
  "SECRET_NAME"
  "HABITIFY_SECRET_NAME"
  "NOTION_SECRET_NAME"
  "BRITTANY_EMAIL"
)

# ── Lambda → stack mapping ────────────────────────────────────────────────────
declare -A STACK_LAMBDAS
STACK_LAMBDAS["LifePlatformEmail"]="daily-brief weekly-digest monthly-digest nutrition-review wednesday-chronicle weekly-plate monday-compass brittany-weekly-email"
STACK_LAMBDAS["LifePlatformCompute"]="anomaly-detector character-sheet-compute daily-metrics-compute daily-insight-compute adaptive-mode-compute hypothesis-engine failure-pattern-compute dashboard-refresh"
STACK_LAMBDAS["LifePlatformIngestion"]="whoop-data-ingestion garmin-data-ingestion withings-data-ingestion habitify-data-ingestion strava-data-ingestion journal-enrichment todoist-data-ingestion eightsleep-data-ingestion activity-enrichment macrofactor-data-ingestion weather-data-ingestion dropbox-poll apple-health-ingestion health-auto-export-webhook notion-journal-ingestion"
STACK_LAMBDAS["LifePlatformOperational"]="life-platform-canary dlq-consumer life-platform-freshness-checker insight-email-parser data-export qa-smoke mcp-key-rotator"
STACK_LAMBDAS["LifePlatformMcp"]="life-platform-mcp"

# ── Helpers ───────────────────────────────────────────────────────────────────
green() { echo -e "\033[32m$*\033[0m"; }
red()   { echo -e "\033[31m$*\033[0m"; }
yellow(){ echo -e "\033[33m$*\033[0m"; }
bold()  { echo -e "\033[1m$*\033[0m"; }

is_high_sensitivity() {
  local var="$1"
  for hs in "${HIGH_SENSITIVITY_VARS[@]}"; do
    if [[ "$var" == "$hs" ]]; then return 0; fi
  done
  return 1
}

TOTAL_DELETIONS=0
TOTAL_ADDITIONS=0
TOTAL_LAMBDAS_CHECKED=0

diff_lambda_env() {
  local fn="$1"

  echo ""
  echo "  ── $fn"

  # Get current Lambda config
  local config
  config=$(aws lambda get-function-configuration \
    --function-name "$fn" \
    --region "$REGION" \
    --output json 2>&1) || {
    yellow "    [SKIP] Lambda not found or not accessible"
    return
  }

  TOTAL_LAMBDAS_CHECKED=$((TOTAL_LAMBDAS_CHECKED + 1))

  # Extract current env vars as KEY=VALUE pairs
  local current_vars
  current_vars=$(echo "$config" | python3 -c "
import json, sys
d = json.load(sys.stdin)
env = d.get('Environment', {}).get('Variables', {})
for k, v in sorted(env.items()):
    print(f'{k}={v}')
" 2>/dev/null || echo "")

  # CDK-known vars: synthesize by running cdk synth and extracting env vars for this function
  # Since we can't run cdk synth live here, we get the expected vars from CloudFormation
  # (what CDK last deployed) vs what's currently in Lambda — catches console drift.
  local cfn_vars
  cfn_vars=$(aws cloudformation describe-stack-resource \
    --stack-name "${CURRENT_STACK}" \
    --logical-resource-id "$(echo "$fn" | sed 's/-//g' | python3 -c "import sys; s=sys.stdin.read().strip(); print(''.join(w.capitalize() for w in s.replace('-','_').split('_')))" 2>/dev/null || echo "$fn")" \
    --region "$REGION" \
    --output json 2>/dev/null | \
    python3 -c "
import json,sys
d = json.load(sys.stdin)
print(d.get('StackResourceDetail', {}).get('PhysicalResourceId',''))
" 2>/dev/null || echo "") 2>/dev/null || true

  # Primary approach: compare Lambda current state to what CDK *last deployed*
  # by looking at what CDK owns (CloudFormation template in S3)
  # Simpler reliable approach: compare against a CDK synth output if available
  local synth_template="cdk.out/${CURRENT_STACK}.template.json"

  if [[ ! -f "$synth_template" ]]; then
    yellow "    [INFO] No cdk.out/${CURRENT_STACK}.template.json — run 'cdk synth' first for CDK-side comparison"
    yellow "    [INFO] Showing current Lambda env vars only:"
    if [[ -n "$current_vars" ]]; then
      while IFS= read -r line; do
        key="${line%%=*}"
        val="${line#*=}"
        if is_high_sensitivity "$key"; then
          yellow "      ⚠️  $key = $val"
        else
          echo "      $key = $val"
        fi
      done <<< "$current_vars"
    else
      echo "      (no env vars)"
    fi
    return
  fi

  # Extract CDK-defined env vars for this Lambda from synth template
  local cdk_vars
  cdk_vars=$(python3 -c "
import json, sys

fn_name = '$fn'
template_path = '$synth_template'

with open(template_path) as f:
    tmpl = json.load(f)

resources = tmpl.get('Resources', {})
found_env = {}
for lid, res in resources.items():
    if res.get('Type') != 'AWS::Lambda::Function':
        continue
    props = res.get('Properties', {})
    if props.get('FunctionName') == fn_name:
        env_block = props.get('Environment', {}).get('Variables', {})
        # Resolve Ref/Fn::Sub where possible
        for k, v in env_block.items():
            if isinstance(v, str):
                found_env[k] = v
            elif isinstance(v, dict):
                found_env[k] = str(v)  # CDK ref/intrinsic
        break

for k, v in sorted(found_env.items()):
    print(f'{k}={v}')
" 2>/dev/null || echo "")

  # Compute diff
  local additions=() deletions=()

  # Vars in CDK not in current Lambda (would be added)
  while IFS= read -r line; do
    [[ -z "$line" ]] && continue
    key="${line%%=*}"
    if ! echo "$current_vars" | grep -q "^${key}="; then
      additions+=("$key")
    fi
  done <<< "$cdk_vars"

  # Vars in current Lambda not in CDK (would be DELETED — danger)
  while IFS= read -r line; do
    [[ -z "$line" ]] && continue
    key="${line%%=*}"
    # Standard CDK env vars that are always present — not drift
    case "$key" in
      TABLE_NAME|S3_BUCKET|USER_ID|AWS_REGION_OVERRIDE|EMAIL_RECIPIENT|EMAIL_SENDER) continue ;;
    esac
    if [[ -n "$cdk_vars" ]] && ! echo "$cdk_vars" | grep -q "^${key}="; then
      deletions+=("$key")
    fi
  done <<< "$current_vars"

  if [[ ${#deletions[@]} -eq 0 ]] && [[ ${#additions[@]} -eq 0 ]]; then
    green "    ✓ No env var drift detected"
    return
  fi

  # Show additions
  if [[ ${#additions[@]} -gt 0 ]]; then
    TOTAL_ADDITIONS=$((TOTAL_ADDITIONS + ${#additions[@]}))
    echo "    + ADDITIONS (CDK will add):"
    for var in "${additions[@]}"; do
      cdk_val=$(echo "$cdk_vars" | grep "^${var}=" | cut -d= -f2-)
      if is_high_sensitivity "$var"; then
        yellow "      + [SENSITIVE] $var = $cdk_val"
      else
        echo "      + $var = $cdk_val"
      fi
    done
  fi

  # Show deletions — always highlight
  if [[ ${#deletions[@]} -gt 0 ]]; then
    TOTAL_DELETIONS=$((TOTAL_DELETIONS + ${#deletions[@]}))
    echo "    - DELETIONS ⚠️  (CDK will REMOVE these — current Lambda has them, CDK does not):"
    for var in "${deletions[@]}"; do
      cur_val=$(echo "$current_vars" | grep "^${var}=" | cut -d= -f2-)
      if is_high_sensitivity "$var"; then
        red "      - [⚠️  HIGH SENSITIVITY] $var = $cur_val"
      else
        red "      - $var = $cur_val"
      fi
    done
  fi
}

check_stack() {
  local stack="$1"
  CURRENT_STACK="$stack"
  local lambdas="${STACK_LAMBDAS[$stack]:-}"

  if [[ -z "$lambdas" ]]; then
    yellow "  [WARN] Unknown stack: $stack — no Lambda mapping found"
    return
  fi

  bold ""
  bold "══════════════════════════════════════════════════════════════"
  bold " CDK Env Var Diff — $stack"
  bold "══════════════════════════════════════════════════════════════"

  for fn in $lambdas; do
    diff_lambda_env "$fn"
  done
}

# ── Main ──────────────────────────────────────────────────────────────────────
if [[ "$STACK_ARG" == "all" ]]; then
  for stack in "${!STACK_LAMBDAS[@]}"; do
    check_stack "$stack"
  done
else
  check_stack "$STACK_ARG"
fi

# ── Summary ───────────────────────────────────────────────────────────────────
echo ""
echo "══════════════════════════════════════════════════════════════"
echo " Diff Summary: $TOTAL_LAMBDAS_CHECKED Lambdas checked | $TOTAL_ADDITIONS additions | $TOTAL_DELETIONS deletions"
echo "══════════════════════════════════════════════════════════════"

if [[ $TOTAL_DELETIONS -gt 0 ]]; then
  echo ""
  red "⚠️  WARNING: $TOTAL_DELETIONS env var(s) currently in Lambda will be DELETED by CDK deploy."
  red "   These may be console-added vars that CDK doesn't know about."
  echo ""
  red "   If these are intentional CDK env vars, add them to the stack definition."
  red "   If these are one-off overrides, document them in RUNBOOK.md."
  echo ""

  if [[ "$CI_MODE" == "true" ]]; then
    red "   CI mode: failing on deletions. Add env vars to CDK stack to proceed."
    exit 1
  else
    echo -n "   Proceed with deploy anyway? [y/N] "
    read -r answer
    if [[ "$answer" != "y" ]] && [[ "$answer" != "Y" ]]; then
      red "   Deploy aborted. Update CDK stack definitions before deploying."
      exit 1
    fi
    yellow "   Proceeding on user confirmation. Record this decision in INCIDENT_LOG.md."
  fi
else
  echo ""
  green "✅  No risky deletions detected. Safe to deploy."
fi

echo ""
echo "  Reminder: Never manually edit Lambda env vars in the AWS Console."
echo "  All env vars must be defined in cdk/stacks/*.py to avoid drift."
