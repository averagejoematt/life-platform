#!/bin/bash
# deploy/attach_mcp_waf.sh — Associate WAF WebACL with MCP Lambda Function URL
#
# Run ONCE after deploying LifePlatformMcp stack. Safe to re-run (idempotent).
# CfnWebACLAssociation does not support Lambda Function URLs in CloudFormation,
# so this association is managed outside CDK — same pattern as the Function URL itself.
#
# Usage:
#   bash deploy/attach_mcp_waf.sh
#
# Verify association:
#   aws wafv2 get-web-acl-for-resource \
#     --resource-arn arn:aws:lambda:us-west-2:205930651321:function:life-platform-mcp \
#     --region us-west-2

set -euo pipefail

REGION="us-west-2"
FUNCTION_ARN="arn:aws:lambda:${REGION}:205930651321:function:life-platform-mcp"
STACK_NAME="LifePlatformMcp"

echo "🔍 Fetching WAF WebACL ARN from CloudFormation stack output..."
WAF_ACL_ARN=$(aws cloudformation describe-stacks \
  --stack-name "$STACK_NAME" \
  --region "$REGION" \
  --query "Stacks[0].Outputs[?OutputKey=='McpWafAclArn'].OutputValue" \
  --output text 2>/dev/null)

if [ -z "$WAF_ACL_ARN" ] || [ "$WAF_ACL_ARN" = "None" ]; then
  echo "❌ Could not find McpWafAclArn output in stack $STACK_NAME"
  echo "   Has the stack been deployed? Run: npx cdk deploy LifePlatformMcp"
  exit 1
fi

echo "   WebACL ARN: $WAF_ACL_ARN"
echo "   Function ARN: $FUNCTION_ARN"

# Check if already associated
echo ""
echo "🔍 Checking existing WAF association..."
EXISTING=$(aws wafv2 get-web-acl-for-resource \
  --resource-arn "$FUNCTION_ARN" \
  --region "$REGION" \
  --query "WebACL.ARN" \
  --output text 2>/dev/null || echo "NONE")

if [ "$EXISTING" = "$WAF_ACL_ARN" ]; then
  echo "✅ WAF already associated — nothing to do"
  echo "   $WAF_ACL_ARN → $FUNCTION_ARN"
  exit 0
fi

if [ "$EXISTING" != "NONE" ] && [ -n "$EXISTING" ]; then
  echo "⚠️  Function is associated with a DIFFERENT WebACL: $EXISTING"
  echo "   This script will replace it with the CDK-managed ACL."
  echo ""
fi

# Associate
echo "🔗 Associating WebACL with MCP Lambda Function URL..."
aws wafv2 associate-web-acl \
  --web-acl-arn "$WAF_ACL_ARN" \
  --resource-arn "$FUNCTION_ARN" \
  --region "$REGION"

echo ""
echo "✅ WAF WebACL associated with life-platform-mcp"

# Verify
VERIFY=$(aws wafv2 get-web-acl-for-resource \
  --resource-arn "$FUNCTION_ARN" \
  --region "$REGION" \
  --query "WebACL.Name" \
  --output text 2>/dev/null || echo "ERROR")

if [ "$VERIFY" = "life-platform-mcp-rate-limit" ]; then
  echo "✅ Verified: life-platform-mcp-rate-limit is active on MCP Function URL"
else
  echo "⚠️  Verification inconclusive — check manually:"
  echo "   aws wafv2 get-web-acl-for-resource --resource-arn $FUNCTION_ARN --region $REGION"
fi
