# R18 Architecture Review Remediation

Read `docs/reviews/REVIEW_2026-03-28_v18.md` for full context. This session remediates all 9 R18 findings plus persisting R17 findings. Work through each phase sequentially, committing after each phase.

## PHASE 1: Documentation Reconciliation (R18-F01, R18-F08)

### 1a. Audit actual system state
Run these commands and capture the output — these are the authoritative numbers:

```bash
# Lambda count
aws lambda list-functions --region us-west-2 --query 'Functions[].FunctionName' --output text | tr '\t' '\n' | grep -c .
aws lambda list-functions --region us-east-1 --query 'Functions[].FunctionName' --output text | tr '\t' '\n' | grep -c .

# List all Lambda names (both regions)
echo "=== us-west-2 ===" && aws lambda list-functions --region us-west-2 --query 'Functions[].FunctionName' --output text | tr '\t' '\n' | sort
echo "=== us-east-1 ===" && aws lambda list-functions --region us-east-1 --query 'Functions[].FunctionName' --output text | tr '\t' '\n' | sort

# MCP tool count
grep -c "\"name\":" mcp/registry.py 2>/dev/null || python3 -c "import mcp_server; print(len([t for t in dir(mcp_server) if 'tool' in t.lower()]))" 2>/dev/null || grep -c "'name'" mcp_server.py

# Site page count
find site/ -name 'index.html' | wc -l

# CDK stack count
cd cdk && npx cdk list 2>/dev/null | wc -l; cd ..

# Data source count
grep -c "SOURCE#" docs/SCHEMA.md 2>/dev/null || echo "check SCHEMA.md manually"
```

### 1b. Update ARCHITECTURE.md header and body
Using the audit numbers from 1a, update the `Last updated` header line in `docs/ARCHITECTURE.md` to reflect accurate counts for: tools, modules, data sources, Lambdas, CDK stacks. Then find and fix every conflicting number in the body:
- The "12 pages" reference in the Web Layer diagram → actual count
- The "95 tools" in the Serve Layer MCP section → actual count
- The "19 sources" in the Overview → actual count
- The "8 stacks" / "7 stacks" discrepancy → actual count
- The "49 alarms" references → verify or update

### 1c. Update INFRASTRUCTURE.md header
Same — fix the `Last updated` header line with accurate Lambda count, tool count, alarm count, secret count.

### 1d. Add honest freeze label to INTELLIGENCE_LAYER.md (R18-F08)
At the very top of `docs/INTELLIGENCE_LAYER.md`, before the existing title, add:

```markdown
> ⚠️ **This document is frozen at v3.7.68 (2026-03-17).** The platform is now at v4.3.0+.
> For IC changes after v3.7.68 — including signal doctrine, challenge system modifiers,
> food delivery integration, and reader engagement signals — see CHANGELOG.md.
> A full refresh is planned for ~May 2026.
```

### 1e. Create audit script (Board Brainstorm idea #1)
Create `deploy/audit_system_state.sh` that runs the commands from 1a, parses the doc headers, and reports discrepancies. This should be run before every future architecture review.

**Commit after Phase 1:** `git add -A && git commit -m "R18-F01/F08: Documentation reconciliation — audit and fix all conflicting counts"`

---

## PHASE 2: lambda_map.json Update (R18-F03)

### 2a. Find orphan Lambda source files
```bash
# List all .py files in lambdas/ that are NOT in lambda_map.json
for f in lambdas/*_lambda.py lambdas/*_handler.py; do
  basename="$f"
  if ! grep -q "\"$basename\"" ci/lambda_map.json; then
    echo "MISSING from lambda_map: $basename"
  fi
done
```

### 2b. Add missing entries
For each missing file found in 2a, add it to `ci/lambda_map.json` in the `"lambdas"` section. Match the pattern of existing entries. For Lambdas you can identify the AWS function name from the filename pattern or by running:
```bash
aws lambda list-functions --region us-west-2 --query 'Functions[].FunctionName' --output text | tr '\t' '\n' | sort
```

At minimum, these are known missing:
- `lambdas/og_image_generator_lambda.py` → `og-image-generator` (or whatever the actual filename/function is)
- `lambdas/email_subscriber_lambda.py` → `email-subscriber`
- Any others found in 2a

Update the `_updated` field to today's date and current version.

### 2c. Add CI lint for orphan files
In `.github/workflows/ci-cd.yml`, add a step in the `lint` job (after flake8) that checks for Lambda source files not present in lambda_map.json:

```yaml
      - name: Check lambda_map coverage
        run: |
          MISSING=0
          for f in lambdas/*_lambda.py lambdas/*_handler.py; do
            [ -f "$f" ] || continue
            if ! grep -q "\"$f\"" ci/lambda_map.json; then
              echo "::warning file=$f::Lambda source file not in lambda_map.json"
              MISSING=$((MISSING + 1))
            fi
          done
          if [ $MISSING -gt 0 ]; then
            echo "::warning::$MISSING Lambda source files missing from lambda_map.json"
          fi
```

**Commit:** `git add -A && git commit -m "R18-F03: Update lambda_map.json — add missing entries + CI orphan lint"`

---

## PHASE 3: New Resource Monitoring (R18-F04)

### 3a. Add CloudWatch alarms for new Lambdas
Create `deploy/setup_r18_alarms.sh`:

```bash
#!/bin/bash
set -euo pipefail

# R18-F04: Add CloudWatch alarms for Lambdas created during the v3.7.82→v4.3.0 sprint
# that don't have alarms yet.

REGION="us-west-2"
SNS_ARN="arn:aws:sns:us-west-2:205930651321:life-platform-alerts"

NEW_LAMBDAS=(
  "og-image-generator"
  "food-delivery-ingestion"
  "challenge-generator"
  "email-subscriber"
)

for LAMBDA in "${NEW_LAMBDAS[@]}"; do
  # Check if Lambda exists
  if ! aws lambda get-function --function-name "$LAMBDA" --region "$REGION" --no-cli-pager > /dev/null 2>&1; then
    echo "⚠️  Lambda $LAMBDA not found in $REGION — skipping"
    continue
  fi

  ALARM_NAME="${LAMBDA}-errors"

  # Check if alarm already exists
  if aws cloudwatch describe-alarms --alarm-names "$ALARM_NAME" --region "$REGION" --query 'MetricAlarms[0].AlarmName' --output text 2>/dev/null | grep -q "$ALARM_NAME"; then
    echo "✓ Alarm $ALARM_NAME already exists — skipping"
    continue
  fi

  echo "Creating alarm: $ALARM_NAME"
  aws cloudwatch put-metric-alarm \
    --alarm-name "$ALARM_NAME" \
    --alarm-description "R18-F04: Error alarm for $LAMBDA" \
    --metric-name Errors \
    --namespace AWS/Lambda \
    --dimensions Name=FunctionName,Value="$LAMBDA" \
    --statistic Sum \
    --period 86400 \
    --evaluation-periods 1 \
    --threshold 1 \
    --comparison-operator GreaterThanOrEqualToThreshold \
    --alarm-actions "$SNS_ARN" \
    --treat-missing-data notBreaching \
    --region "$REGION" \
    --no-cli-pager

  echo "  ✓ Created $ALARM_NAME"
done

echo ""
echo "Done. Verify: aws cloudwatch describe-alarms --region $REGION --query 'MetricAlarms[?starts_with(AlarmName, \`og-\`) || starts_with(AlarmName, \`food-\`) || starts_with(AlarmName, \`challenge-\`) || starts_with(AlarmName, \`email-sub\`)].AlarmName' --output table"
```

### 3b. Add food-delivery to freshness checker
In `lambdas/freshness_checker_lambda.py`, add `food_delivery` to the monitored sources list with an appropriate stale threshold (7 days — since it's manual CSV import, not daily API sync). Look at how other sources are configured and follow the same pattern.

**Commit:** `git add -A && git commit -m "R18-F04: Add CloudWatch alarms for new Lambdas + food-delivery freshness check"`

Then Matthew runs: `bash deploy/setup_r18_alarms.sh`

---

## PHASE 4: WAF Endpoint-Specific Rules (R18-F06)

Create `deploy/setup_waf_endpoint_rules.sh`:

```bash
#!/bin/bash
set -euo pipefail

# R18-F06: Add endpoint-specific WAF rate rules for AI endpoints
# Requires the existing WebACL from TB7-26 (setup_waf.sh)

REGION="us-east-1"
WEBACL_NAME="life-platform-amj-waf"
SCOPE="CLOUDFRONT"

echo "=== R18-F06: WAF endpoint-specific rate rules ==="

# Get current WebACL
echo "[1/3] Fetching current WebACL..."
WEBACL_JSON=$(aws wafv2 get-web-acl \
  --name "$WEBACL_NAME" \
  --scope "$SCOPE" \
  --region "$REGION" \
  --no-cli-pager)

WEBACL_ID=$(echo "$WEBACL_JSON" | python3 -c "import json,sys; print(json.load(sys.stdin)['WebACL']['Id'])")
WEBACL_ARN=$(echo "$WEBACL_JSON" | python3 -c "import json,sys; print(json.load(sys.stdin)['WebACL']['ARN'])")
LOCK_TOKEN=$(echo "$WEBACL_JSON" | python3 -c "import json,sys; print(json.load(sys.stdin)['LockToken'])")
CURRENT_RULES=$(echo "$WEBACL_JSON" | python3 -c "import json,sys; print(json.dumps(json.load(sys.stdin)['WebACL']['Rules']))")

echo "  WebACL: $WEBACL_ARN"
echo "  Current rules: $(echo "$CURRENT_RULES" | python3 -c "import json,sys; print(len(json.load(sys.stdin)))")"

# Check if ask rate rule already exists
if echo "$CURRENT_RULES" | grep -q "AskRateLimit"; then
  echo "  ✓ AskRateLimit rule already exists — skipping"
  exit 0
fi

echo "[2/3] Adding endpoint-specific rate rules..."

# Build new rules list = existing + 2 new rules
NEW_RULES=$(python3 -c "
import json, sys
rules = json.loads('''$CURRENT_RULES''')

# /api/ask — 20 requests per 5 min per IP
rules.append({
    'Name': 'AskRateLimit',
    'Priority': 3,
    'Statement': {
        'RateBasedStatement': {
            'Limit': 100,
            'EvaluationWindowSec': 300,
            'AggregateKeyType': 'IP',
            'ScopeDownStatement': {
                'ByteMatchStatement': {
                    'SearchString': '/api/ask',
                    'FieldToMatch': {'UriPath': {}},
                    'TextTransformations': [{'Priority': 0, 'Type': 'LOWERCASE'}],
                    'PositionalConstraint': 'STARTS_WITH'
                }
            }
        }
    },
    'Action': {'Block': {}},
    'VisibilityConfig': {
        'SampledRequestsEnabled': True,
        'CloudWatchMetricsEnabled': True,
        'MetricName': 'AskRateLimit'
    }
})

# /api/board_ask — 10 requests per 5 min per IP
rules.append({
    'Name': 'BoardAskRateLimit',
    'Priority': 4,
    'Statement': {
        'RateBasedStatement': {
            'Limit': 100,
            'EvaluationWindowSec': 300,
            'AggregateKeyType': 'IP',
            'ScopeDownStatement': {
                'ByteMatchStatement': {
                    'SearchString': '/api/board_ask',
                    'FieldToMatch': {'UriPath': {}},
                    'TextTransformations': [{'Priority': 0, 'Type': 'LOWERCASE'}],
                    'PositionalConstraint': 'STARTS_WITH'
                }
            }
        }
    },
    'Action': {'Block': {}},
    'VisibilityConfig': {
        'SampledRequestsEnabled': True,
        'CloudWatchMetricsEnabled': True,
        'MetricName': 'BoardAskRateLimit'
    }
})

print(json.dumps(rules))
")

# Update WebACL
VISIBILITY_CONFIG=$(echo "$WEBACL_JSON" | python3 -c "import json,sys; print(json.dumps(json.load(sys.stdin)['WebACL']['VisibilityConfig']))")

aws wafv2 update-web-acl \
  --name "$WEBACL_NAME" \
  --scope "$SCOPE" \
  --region "$REGION" \
  --id "$WEBACL_ID" \
  --lock-token "$LOCK_TOKEN" \
  --default-action '{"Allow": {}}' \
  --visibility-config "$VISIBILITY_CONFIG" \
  --rules "$NEW_RULES" \
  --no-cli-pager > /dev/null

echo "  ✓ Added AskRateLimit (100/5min on /api/ask*)"
echo "  ✓ Added BoardAskRateLimit (100/5min on /api/board_ask*)"

echo ""
echo "[3/3] Verifying..."
VERIFY=$(aws wafv2 get-web-acl --name "$WEBACL_NAME" --scope "$SCOPE" --region "$REGION" --query 'WebACL.Rules[].Name' --output text --no-cli-pager)
echo "  Active rules: $VERIFY"
echo ""
echo "=== R18-F06 complete ==="
echo "Note: WAF rate-based rules have a minimum of 100 requests/5min."
echo "In-memory Lambda rate limits (3 anon / 20 subscriber per hour) provide tighter control."
```

Note: WAF rate-based rules have a minimum threshold of 100 requests per 5 minutes per IP. The in-memory Lambda rate limits (3/hr anon, 20/hr subscriber) are tighter. The WAF rules catch bulk abuse; Lambda limits catch per-user throttling.

**Commit:** `git add -A && git commit -m "R18-F06: WAF endpoint-specific rate rules for /api/ask and /api/board_ask"`

Then Matthew runs: `bash deploy/setup_waf_endpoint_rules.sh`

---

## PHASE 5: Site Deploy Script (R18-F05)

Create `deploy/deploy_site.sh`:

```bash
#!/bin/bash
set -euo pipefail

# R18-F05: Canonical site deployment script
# Replaces ad-hoc "aws s3 sync" commands with validation + sync + invalidation

BUCKET="matthew-life-platform"
DISTRIBUTION_ID="E3S424OXQZ8NBE"
SITE_DIR="site"
S3_PREFIX="site"
REGION="us-west-2"

echo "=== Site Deploy ==="
echo "Source: $SITE_DIR/"
echo "Target: s3://$BUCKET/$S3_PREFIX/"

# 1. Validate site directory exists and has index.html
if [ ! -f "$SITE_DIR/index.html" ]; then
  echo "❌ $SITE_DIR/index.html not found. Are you in the project root?"
  exit 1
fi

PAGE_COUNT=$(find "$SITE_DIR" -name 'index.html' | wc -l | tr -d ' ')
echo "Pages: $PAGE_COUNT"

# 2. Check for broken internal links (basic)
echo ""
echo "[1/4] Checking for obviously broken internal links..."
BROKEN=0
for f in $(find "$SITE_DIR" -name '*.html'); do
  # Find href="/something/" patterns and verify the target exists
  grep -oP 'href="/([^"#?]+)"' "$f" 2>/dev/null | sed 's|href="/||;s|"||' | while read -r link; do
    # Skip external, API, and anchor links
    [[ "$link" == http* ]] && continue
    [[ "$link" == api/* ]] && continue
    [[ "$link" == mailto* ]] && continue
    TARGET="$SITE_DIR/$link"
    # Check if target is a file or directory with index.html
    if [ ! -f "$TARGET" ] && [ ! -f "${TARGET}index.html" ] && [ ! -f "${TARGET%/}/index.html" ]; then
      echo "  ⚠️  Broken link in $(basename $f): /$link"
      BROKEN=$((BROKEN + 1))
    fi
  done
done
if [ "$BROKEN" -gt 0 ]; then
  echo "  $BROKEN broken links found (warnings only — not blocking deploy)"
else
  echo "  ✓ No broken links detected"
fi

# 3. Sync to S3 (using safe_sync if available)
echo ""
echo "[2/4] Syncing to S3..."
if [ -f "deploy/lib/safe_sync.sh" ]; then
  source deploy/lib/safe_sync.sh
  safe_sync "$SITE_DIR" "s3://$BUCKET/$S3_PREFIX" --delete \
    --exclude "*.DS_Store" \
    --cache-control "public, max-age=86400"
else
  aws s3 sync "$SITE_DIR" "s3://$BUCKET/$S3_PREFIX" --delete \
    --exclude "*.DS_Store" \
    --cache-control "public, max-age=86400" \
    --region "$REGION" --no-cli-pager
fi
echo "  ✓ S3 sync complete"

# 4. CloudFront invalidation
echo ""
echo "[3/4] Invalidating CloudFront cache..."
INVALIDATION_ID=$(aws cloudfront create-invalidation \
  --distribution-id "$DISTRIBUTION_ID" \
  --paths "/*" \
  --query 'Invalidation.Id' \
  --output text --no-cli-pager)
echo "  ✓ Invalidation created: $INVALIDATION_ID"

# 5. Log
echo ""
echo "[4/4] Done."
echo "  Pages deployed: $PAGE_COUNT"
echo "  Target: https://averagejoematt.com/"
echo "  Invalidation: $INVALIDATION_ID (takes 1-2 min to propagate)"
```

**Commit:** `git add -A && git commit -m "R18-F05: Canonical site deploy script with validation + sync + invalidation"`

---

## PHASE 6: Persisting R17 Findings Cleanup

### 6a. R17-F08: Check google_calendar in config.py
```bash
grep -rn "google_calendar" mcp/config.py lambdas/ --include="*.py"
```
If found in a SOURCES list, remove it. Google Calendar was retired in ADR-030.

### 6b. R17-F10: Check hardcoded model strings in site_api_lambda.py
```bash
grep -n "claude\|haiku\|sonnet\|model=" lambdas/site_api_lambda.py
```
If model strings are hardcoded (e.g., `"claude-3-5-haiku-20241022"`), replace with `os.environ.get('AI_MODEL', 'claude-3-5-haiku-20241022')`. Then add the `AI_MODEL` env var to the CDK web stack config.

### 6c. R17-F07: Add CORS headers to site_api_lambda.py
In the response builder function of `lambdas/site_api_lambda.py`, ensure all responses include:
```python
'headers': {
    'Access-Control-Allow-Origin': 'https://averagejoematt.com',
    'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
    'Access-Control-Allow-Headers': 'Content-Type',
    ...existing headers...
}
```
Also add an OPTIONS handler that returns 200 with CORS headers for preflight requests.

**Commit:** `git add -A && git commit -m "R17-F07/F08/F10: CORS headers, remove google_calendar, model string env var"`

---

## PHASE 7: Final Sweep

### 7a. Update CHANGELOG.md
Prepend an entry for the remediation work:

```markdown
## v4.3.1 — 2026-XX-XX: R18 Architecture Review Remediation

### Documentation (R18-F01, R18-F08)
- Reconciled all doc headers with AWS audit: Lambda count, MCP tool count, page count, CDK stack count, data source count
- Added freeze label to INTELLIGENCE_LAYER.md (stale since v3.7.68, flagged 5 consecutive reviews)
- Created `deploy/audit_system_state.sh` for pre-review system state verification

### CI/CD (R18-F03)
- Updated lambda_map.json with all missing Lambda entries
- Added CI lint step for orphan Lambda source files

### Monitoring (R18-F04)
- CloudWatch error alarms added for: og-image-generator, food-delivery-ingestion, challenge-generator, email-subscriber
- Food delivery added to freshness checker (7-day stale threshold)

### Security (R18-F06)
- WAF endpoint-specific rate rules: /api/ask (100/5min), /api/board_ask (100/5min)

### Operations (R18-F05)
- Created `deploy/deploy_site.sh` — canonical site deploy with link validation + S3 sync + CloudFront invalidation

### R17 Cleanup
- Removed google_calendar from SOURCES (R17-F08, ADR-030)
- Site API model string moved to environment variable (R17-F10)
- CORS headers added to site_api_lambda.py (R17-F07)
```

### 7b. Update handover
Write `handovers/HANDOVER_R18_REMEDIATION.md` and update `HANDOVER_LATEST.md`.

### 7c. Final commit and push
```bash
git add -A && git commit -m "v4.3.1: R18 Architecture Review remediation — 9 findings addressed" && git push
```

---

## DEFERRED (requires Matthew or separate session)

These items are noted but NOT in scope for this remediation:

- **R18-F02: CDK adoption of CLI Lambdas** — Requires CDK stack modifications and `npx cdk deploy`. Do in a dedicated CDK session.
- **R18-F07: SIMP-1 Phase 2 (110→80 tools)** — Large scope, needs MCP tool usage analysis first. Target: week 2-3 post-launch.
- **R18-F09: Cross-region migration** — site-api us-east-1→us-west-2. Requires CloudFront origin change + CDK stack migration. Target: week 3 post-launch.
- **R17-F12: PITR restore drill** — Requires running `aws dynamodb restore-table-to-point-in-time` against a test table. 15 min but manual verification needed.
