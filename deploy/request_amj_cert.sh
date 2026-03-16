#!/usr/bin/env bash
# request_amj_cert.sh — Request ACM certificate for averagejoematt.com
#
# MUST run in us-east-1 (CloudFront requires ACM certs from us-east-1 only).
# After running:
#   1. Go to AWS Console → Certificate Manager → us-east-1
#   2. Click the pending cert → add the CNAME records to Route 53 (or use --validation-method EMAIL)
#   3. Wait ~2 min for DNS validation to complete
#   4. Copy the ARN from the output
#   5. Update CERT_ARN_AMJ in cdk/stacks/web_stack.py
#   6. Run: bash deploy/deploy_web_stack.sh
#
# Cost: ACM certificates are free.
# ─────────────────────────────────────────────────────────────────────────────

set -euo pipefail

echo "Requesting ACM certificate for averagejoematt.com in us-east-1..."

CERT_ARN=$(aws acm request-certificate \
  --domain-name averagejoematt.com \
  --subject-alternative-names "www.averagejoematt.com" \
  --validation-method DNS \
  --region us-east-1 \
  --query CertificateArn \
  --output text)

echo ""
echo "✅ Certificate requested: $CERT_ARN"
echo ""
echo "Next steps:"
echo "  1. aws acm describe-certificate --certificate-arn $CERT_ARN --region us-east-1"
echo "     → Find the CNAME name + value under DomainValidationOptions"
echo ""
echo "  2. Add those CNAME records to Route 53 (or run the auto-add below):"
echo ""
echo "     HOSTED_ZONE_ID=<your-zone-id>  # find with: aws route53 list-hosted-zones"
echo "     # Then run deploy/validate_amj_cert.sh with those values"
echo ""
echo "  3. Wait ~2 min for Status to become ISSUED:"
echo "     watch -n 10 'aws acm describe-certificate --certificate-arn $CERT_ARN --region us-east-1 --query Certificate.Status --output text'"
echo ""
echo "  4. Update CERT_ARN_AMJ in cdk/stacks/web_stack.py:"
echo "     Old: CERT_ARN_AMJ = \"arn:aws:acm:us-east-1:205930651321:certificate/PLACEHOLDER-request-cert-first\""
echo "     New: CERT_ARN_AMJ = \"$CERT_ARN\""
echo ""
echo "  5. Then run: bash deploy/deploy_web_stack.sh"
