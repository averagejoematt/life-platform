#!/bin/bash
# deploy_meal_grouping.sh — Session-2 prep + deploy SEQUENCE for the derived meal layer.
#
# This script runs ONLY the safe, local prep (offline tests, format check, layer build).
# It then PRINTS the exact deploy commands for you to run — it does NOT touch AWS.
# Matthew runs all deploys + the live backfill himself.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo "════════════════════════════════════════════════════════════════"
echo "  Meal grouping — Session 2 local prep (no AWS)"
echo "════════════════════════════════════════════════════════════════"

echo "▸ 1/4  Offline tests (grouper + projection + MCP registry + wiring)"
python3 -m pytest tests/test_meal_grouper.py tests/test_meal_projection.py \
                  tests/test_mcp_registry.py tests/test_wiring_coverage.py -q

echo "▸ 2/4  Format + lint gate"
black --check --line-length 140 \
    lambdas/meal_grouper.py lambdas/meal_templates_seed.py lambdas/meal_projection.py \
    mcp/tools_meals.py tests/test_meal_grouper.py tests/test_meal_projection.py
flake8 lambdas/meal_grouper.py lambdas/meal_templates_seed.py lambdas/meal_projection.py \
       mcp/tools_meals.py deploy/backfill_meals.py

echo "▸ 3/4  Build the shared layer (adds meal_grouper/templates/projection + vocab)"
bash deploy/build_layer.sh

echo "▸ 4/4  Syntax-check the Lambdas this touches"
python3 -m py_compile lambdas/emails/freshness_checker_lambda.py mcp/tools_labs.py mcp/registry.py

CUR_LAYER=$(aws lambda list-layer-versions --layer-name life-platform-shared-utils \
            --query 'LayerVersions[0].Version' --output text 2>/dev/null || echo "?")

cat <<EOF

════════════════════════════════════════════════════════════════
  ✅ Local prep done. Now run THESE commands yourself (in order):
════════════════════════════════════════════════════════════════

# ── A. Publish the new shared layer (carries meal_grouper + seed + projection + vocab) ──
#    build_layer.sh already staged cdk/layer-build/. LifePlatformCore publishes it.
cd cdk && npx cdk deploy LifePlatformCore --require-approval never
#    Read the NEW version it printed (current live layer is v${CUR_LAYER}):
aws lambda list-layer-versions --layer-name life-platform-shared-utils \\
    --query 'LayerVersions[0].Version' --output text
#    Bump SHARED_LAYER_VERSION in cdk/stacks/constants.py to that number, then:

# ── B. Deploy the MCP Lambda (new layer + tools_meals.py + registry; SCOPED DeleteItem) ──
#    Use CDK (NOT deploy_lambda.sh — it rejects life-platform-mcp). CDK restages mcp/,
#    attaches the new layer, and applies the role_policies grant. The DeleteItem grant is
#    a real IAM change on the LLM-facing role, so REVIEW it and let CDK GATE on it —
#    NO --require-approval never here; approve the security diff explicitly.
cd cdk && npx cdk diff LifePlatformMcp     # inspect the IAM change set (expect ONE scoped
#                                            DynamoDBMealPrune statement: DeleteItem on the
#                                            table, conditioned to LeadingKeys =
#                                            USER#matthew#SOURCE#macrofactor_meals — and NO
#                                            table-wide DeleteItem).
cd cdk && npx cdk deploy LifePlatformMcp   # CDK pauses for explicit approval on the IAM change
#    (Code-only push is NOT enough for this first deploy — the layer bump + the scoped
#     DeleteItem grant both require the CDK deploy above. After they're live, future
#     code-only pushes can use: aws lambda update-function-code --function-name
#     life-platform-mcp --zip-file fileb://<zip built from mcp_server.py + mcp/>.)

# ── C. Deploy the freshness checker (re-enabled macrofactor + format-drift guard) ──
#    No new layer/IAM needed — plain handler redeploy. deploy_lambda.sh needs the
#    function name AND the source file.
bash deploy/deploy_lambda.sh life-platform-freshness-checker lambdas/emails/freshness_checker_lambda.py

# ── D. Backfill the projection — DRY-RUN FIRST, eyeball a week or two, THEN apply ──
S3_BUCKET=matthew-life-platform USER_ID=matthew python3 deploy/backfill_meals.py --limit 14
S3_BUCKET=matthew-life-platform USER_ID=matthew python3 deploy/backfill_meals.py            # full dry-run
S3_BUCKET=matthew-life-platform USER_ID=matthew python3 deploy/backfill_meals.py --apply     # WRITE

# ── E. Verify ──
#  • CloudWatch: /aws/lambda/life-platform-mcp + life-platform-freshness-checker (no errors)
#  • Spot-check:  manage_meals get_day  for a few real dates
#  • most_eaten:  manage_meals most_eaten over the backfilled window
#  • Watch the UNCATEGORIZED rate over the next 2–3 weeks — legit staple variants
#    landing in uncategorized = the signal to widen a template or tune CONF_MIN.
════════════════════════════════════════════════════════════════
EOF
