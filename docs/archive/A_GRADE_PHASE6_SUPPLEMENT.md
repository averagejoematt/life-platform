# A-Grade Remediation Plan — PHASE 6: From A- to A

> **Purpose:** Additional tasks required to move from A- (achievable with Phases 1-5) to a straight A across all dimensions.
> **Prerequisite:** Complete Phases 1-5 first. These tasks build on the A- foundation.
> **Cost rule:** Same as main plan — flag anything >$1/month for review.

---

## Gap Analysis: A- vs A

| # | Dimension | After Phase 1-5 | Gap to A |
|---|-----------|-----------------|----------|
| 1 | Architecture | A- | CDK adoption (not just audit) of unmanaged Lambdas |
| 2 | Security | A- | CI dependency scanning + API input validation audit |
| 3 | Reliability | A | ✅ Closed by PITR drill + alarm verification |
| 4 | Observability | A- | Ops dashboard with real-time SLO widgets + /api/healthz endpoint |
| 5 | Cost | A | ✅ No changes needed |
| 6 | Code Quality | A- | INTELLIGENCE_LAYER.md full refresh (unfreeze) |
| 7 | Data Quality | A | ✅ No changes needed |
| 8 | AI Rigour | A | ✅ No changes needed |
| 9 | Operability | A- | Operator onboarding guide (narrative Day-1 document) |
| 10 | Product | A | ✅ No changes needed |

**Dimensions needing Phase 6 work:** Architecture, Security, Observability, Code Quality, Operability

---

## Task 6.1: CDK Adoption of Unmanaged Lambdas (Architecture A- → A)

**Why A- stops short:** The Phase 2 CDK audit documents which Lambdas are outside CDK — but doesn't adopt them. Priya's standard for A is "all infrastructure is managed, not just catalogued."

**Prerequisite:** Task 2.1 CDK audit must be complete — the audit document lists exactly which Lambdas need adoption and which CDK stacks they belong to.

**What to do:**
1. Read the CDK audit document from Phase 2 (`docs/audits/AUDIT_2026-03-30_cdk_adoption.md`)
2. For each unmanaged Lambda identified:
   - Add it to the appropriate CDK stack file in `cdk/stacks/`
   - Add its IAM role to `cdk/stacks/role_policies.py`
   - Add its EventBridge rule if it's a scheduled Lambda
   - Add its CloudWatch alarm to the monitoring stack
3. Run `npx cdk diff` on each affected stack to verify the changes look correct
4. Present the diff output to Matthew for review

**⚠️ REVIEW WITH MATTHEW before running `cdk deploy`.** CDK deploys can delete and recreate resources. Matthew must review every diff and approve each stack deploy individually.

**Deploy sequence (Matthew runs in terminal):**
```bash
cd ~/Documents/Claude/life-platform/cdk
npx cdk diff LifePlatformIngestion
npx cdk diff LifePlatformCompute
npx cdk diff LifePlatformOperational
# Review each diff, then:
npx cdk deploy LifePlatformIngestion --require-approval never
# Wait 30s
npx cdk deploy LifePlatformCompute --require-approval never
# Wait 30s
npx cdk deploy LifePlatformOperational --require-approval never
```

5. After each deploy, run a smoke test: invoke the Lambda manually and verify it succeeds
6. Update the CDK audit document with "ADOPTED" status for each Lambda

**Cost impact:** $0 (CDK manages existing resources, doesn't create new ones)

---

## Task 6.2: CI Dependency Scanning (Security A- → A)

**Why A- stops short:** Phase 3 verifies existing security controls but doesn't add automated scanning. Yael's standard for A is "security is automated, not just verified once."

**What to do:**
1. Read `.github/workflows/ci-cd.yml`
2. Add a dependency security scan step to the test job:
```yaml
  - name: Dependency Security Scan
    run: |
      pip install pip-audit --break-system-packages
      pip-audit -r requirements.txt --desc on --fix || true
      pip-audit -r requirements.txt --desc on
```
3. If there's no `requirements.txt`, create one by scanning all Lambda imports:
```bash
# Generate from Lambda source files
grep -rh "^import\|^from" lambdas/*.py | sort -u | grep -v "^from \." | grep -v "^import os\|^import json\|^import time\|^import datetime\|^import boto3\|^import re\|^import hashlib\|^import logging" > /tmp/external_deps.txt
```
4. Alternatively, add the pip-audit step as a `|| true` (advisory, non-blocking) so it doesn't break deploys for known-accepted vulnerabilities

**Cost impact:** $0 (CI minutes are within GitHub free tier for this project size)

### Task 6.2b: API Input Validation Audit

**What to do:**
1. Read `lambdas/site_api_lambda.py`
2. For every route that accepts user input (query parameters, POST bodies):
   - Verify the input is validated (type-checked, length-bounded, sanitized)
   - Verify SQL-injection-like strings in query params don't cause errors
   - Verify excessively long inputs are rejected (e.g., POST /api/ask with a 100KB body)
3. For any route missing validation, add it:
```python
# Example: validate and bound query parameter length
email = event.get('queryStringParameters', {}).get('email', '')
if len(email) > 254 or not re.match(r'^[^@]+@[^@]+\.[^@]+$', email):
    return {"statusCode": 400, "body": json.dumps({"error": "Invalid email"})}
```
4. Document findings in `docs/audits/AUDIT_2026-03-30_input_validation.md`
5. Deploy updated site-api if changes were made

**Cost impact:** $0

---

## Task 6.3: Ops Dashboard + Health Endpoint (Observability A- → A)

**Why A- stops short:** Structured logging gives query-able metrics but requires manual investigation. Jin's standard for A is "health is visible at a glance."

### Task 6.3a: Update Existing Ops Dashboard

**What to do:**
1. Check if `life-platform-ops` dashboard exists: `aws cloudwatch get-dashboard --dashboard-name life-platform-ops --region us-west-2`
2. If it exists, update it. If not, create it.
3. The dashboard should include these widgets:
   - **SLO Status Row:** 4 alarm-status widgets for SLO-1 through SLO-4
   - **Lambda Health:** Error count for daily-brief, MCP, site-api, pipeline-health-check (last 24h)
   - **Data Freshness:** StaleSourceCount metric (last 7 days)
   - **DLQ Depth:** ApproximateNumberOfMessages (last 7 days)
   - **API Latency:** site-api Duration p50/p95 (last 24h)
   - **Cost:** MTD spend widget (if Cost Explorer metric is available)
4. Use the dashboard JSON format and deploy via:
```bash
aws cloudwatch put-dashboard --dashboard-name life-platform-ops --dashboard-body file:///tmp/dashboard.json --region us-west-2
```

**⚠️ COST FLAG: If creating a NEW dashboard, cost is $3/month. If updating existing, $0. Check first and flag for Matthew.**

### Task 6.3b: /api/healthz Endpoint

**What to do:**
1. Add a new route to `lambdas/site_api_lambda.py`:
```python
elif path == '/api/healthz' and method == 'GET':
    # Lightweight health check — no AI calls, no heavy queries
    import time
    start = time.time()
    
    # 1. DynamoDB read latency test
    try:
        ddb_start = time.time()
        table.get_item(Key={'PK': 'USER#matthew#SOURCE#whoop', 'SK': 'DATE#2026-01-01'})
        ddb_latency = round((time.time() - ddb_start) * 1000)
        ddb_status = 'ok'
    except Exception as e:
        ddb_latency = -1
        ddb_status = f'error: {str(e)[:50]}'
    
    # 2. Source freshness summary (from cached public_stats.json)
    try:
        stats = json.loads(s3.get_object(Bucket=BUCKET, Key='site/public_stats.json')['Body'].read())
        refreshed = stats.get('_meta', {}).get('refreshed_at', 'unknown')
    except Exception:
        refreshed = 'unavailable'
    
    # 3. Lambda status
    total_ms = round((time.time() - start) * 1000)
    
    health = {
        'status': 'ok' if ddb_status == 'ok' else 'degraded',
        'version': 'v4.5.1',
        'checks': {
            'dynamodb': {'status': ddb_status, 'latency_ms': ddb_latency},
            'last_daily_refresh': refreshed,
            'lambda_warm': not getattr(context, '_cold_start', True)
        },
        'response_ms': total_ms
    }
    return {'statusCode': 200, 'headers': CORS_HEADERS, 'body': json.dumps(health)}
```
2. This gives external monitors (UptimeRobot, or just a browser bookmark) a single URL to verify everything's running
3. No authentication required — the response contains no PII, just system health
4. Deploy: `bash deploy/deploy_lambda.sh life-platform-site-api`

**Cost impact:** $0 (uses existing Lambda invocations and DDB read capacity)

---

## Task 6.4: INTELLIGENCE_LAYER.md Full Refresh (Code Quality A- → A)

**Why A- stops short:** The freeze label was honest pragmatism at R18. But 70+ versions later, Elena's standard for A is "documentation is complete and current, not just honestly labelled as stale."

**What to do:**
1. Read `docs/INTELLIGENCE_LAYER.md`
2. Remove the freeze label at the top
3. Update the header to `Last updated: 2026-03-30 (v4.5.1)`
4. Update the Architecture diagram to reflect current compute pipeline timing
5. Update IC feature status table:
   - IC-29 (Deficit Sustainability): status → Live (v3.7.67), add MCP tool details
   - IC-30 (Autonomic Balance Score): status → Live (v3.7.67), add tool details  
   - IC-4/IC-5: update data gate status (approaching ~Apr 18)
   - IC-27 through IC-31: update from Board Summit section
6. Add new sections for features added since v3.7.68:
   - Signal Doctrine (v3.9.34-36): evidence badges, N=1 caveats, confidence tiers
   - Challenge System modifiers: how challenges interact with IC features
   - Food Delivery integration: delivery index as IC input
   - Reader Engagement signals: freshness indicators, engagement tracking
   - Elena Voss pull-quote pipeline: how AI-generated content flows to observatory pages
7. Update the Prompt Architecture Standards section with any new patterns
8. Update the "What NOT to Build" section with any new ADRs (ADR-035 through ADR-044)
9. Update the Data Maturity Roadmap dates based on current state

**Cost impact:** $0 (documentation only)

---

## Task 6.5: Operator Onboarding Guide (Operability A- → A)

**Why A- stops short:** The RUNBOOK is a reference. The QUICKSTART covers dev setup. Neither walks a new operator through "here's how you take care of this platform day-to-day." Jin's standard for A is "a competent SRE can take over operations in one day."

**What to do:**
Create `docs/OPERATOR_GUIDE.md`:

```markdown
# Life Platform — Operator Guide

> Everything you need to run this platform. Read this on Day 1.
> For architectural decisions: ARCHITECTURE.md
> For emergency procedures: RUNBOOK.md
> For deployment steps: QUICKSTART.md

## System in 60 Seconds

[One-paragraph description of what the platform does, what's running, and why]

## Daily Health Check (2 minutes)

1. Visit https://averagejoematt.com/status/
2. All sources should show green. Yellow = overdue. Red = broken.
3. Check email for any SNS alarm notifications from overnight
4. If anything is red: see "Responding to Failures" below

## Weekly Operational Rhythm

- **Monday:** Check that Monday Compass email was sent (CloudWatch logs for `monday-compass`)
- **Wednesday:** Check that Chronicle email was sent
- **Sunday:** Verify hypothesis engine ran (check `hypothesis-engine` CloudWatch logs)
- **Anytime:** Glance at CloudWatch ops dashboard: `life-platform-ops`

## Responding to Failures

### A Lambda is erroring
1. Find the Lambda name from the alarm email
2. Check CloudWatch logs: AWS Console → Lambda → [function name] → Monitor → View logs
3. Read the most recent error
4. Common fixes:
   - `AccessDenied` → IAM role missing permission → check `cdk/stacks/role_policies.py`
   - `ResourceNotFoundException` on secret → secret was deleted → check Secrets Manager
   - `ImportModuleError` → stale code → redeploy: `bash deploy/deploy_lambda.sh [function-name]`

### A data source is stale
1. Check the status page to identify which source
2. Check the ingestion Lambda's CloudWatch logs
3. Common causes: OAuth token expired (re-run auth setup), upstream API down (wait), Lambda code bug (fix and redeploy)

### DLQ has messages
1. Check DLQ depth: status page or `aws sqs get-queue-attributes`
2. DLQ messages are failed Lambda invocations
3. The `dlq-consumer` Lambda processes them on a schedule
4. If messages are accumulating: check which Lambda is failing and fix the root cause

## Deployment Procedures

| Change | Command | Notes |
|--------|---------|-------|
| Single Lambda | `bash deploy/deploy_lambda.sh [name]` | Auto-reads handler config |
| MCP server | Full zip build (see RUNBOOK) | NEVER use deploy_lambda.sh for MCP |
| Website | `bash deploy/deploy_site.sh` | Validates, syncs, invalidates CDN |
| Shared layer module | `bash deploy/p3_build_shared_utils_layer.sh` then `bash deploy/p3_attach_shared_utils_layer.sh` | Rebuilds layer, attaches to all consumers |
| CDK stack | `cd cdk && npx cdk deploy [StackName]` | Always run `cdk diff` first |

## Key URLs

| URL | Purpose |
|-----|---------|
| https://averagejoematt.com/ | Public site |
| https://averagejoematt.com/status/ | System health dashboard |
| https://dash.averagejoematt.com/ | Private analytics dashboard (password protected) |
| AWS Console → CloudWatch → Dashboards → life-platform-ops | Ops metrics |
| AWS Console → SQS → life-platform-ingestion-dlq | Dead letter queue |

## Secrets & Credentials

- All secrets in AWS Secrets Manager under `life-platform/` prefix
- OAuth tokens (Whoop, Withings, Strava, Garmin) auto-refresh — if they break, re-run the auth setup script
- MCP API key auto-rotates every 90 days via `life-platform-key-rotator`
- Never store secrets in code, env vars, or documentation

## Emergency Contacts

- Platform builder: Matthew Walker
- AWS account: 205930651321 (us-west-2)
- Alert SNS topic: life-platform-alerts → awsdev@mattsusername.com
```

**Cost impact:** $0 (documentation only)

---

## Phase 6 Execution Checklist

```
Phase 6: A- to A
[ ] 6.1 CDK adoption of unmanaged Lambdas (⚠️ review each cdk diff with Matthew)
[ ] 6.2 CI dependency scanning + API input validation audit
[ ] 6.3a Ops dashboard update/creation (⚠️ flag if new = $3/mo)
[ ] 6.3b /api/healthz endpoint
[ ] 6.4 INTELLIGENCE_LAYER.md full refresh
[ ] 6.5 OPERATOR_GUIDE.md creation
[ ] 6.E git add -A && git commit -m "v4.5.2: Phase 6 — all dimensions to A" && git push
```

## Cost Summary (Phase 6)

| Item | Monthly Cost | Flagged? |
|------|-------------|----------|
| CDK adoption | $0 | No |
| CI dependency scanning | $0 | No |
| API input validation | $0 | No |
| Ops dashboard (if new) | $3/month | ⚠️ YES — check if existing |
| /api/healthz | $0 | No |
| INTELLIGENCE_LAYER.md | $0 | No |
| OPERATOR_GUIDE.md | $0 | No |
| **Total Phase 6** | **$0 – $3** | Dashboard only |

---

## Summary: Complete Path B+ → A

| Phase | Effort | Gets You To | Key Deliverable |
|-------|--------|-------------|-----------------|
| Phase 1 | ~2h | Docs from B+/B to A- | INFRA + ARCH + INCIDENT_LOG + Section 13b |
| Phase 2 | ~1h | Architecture audit documented | CDK audit + SIMP-1 ADR |
| Phase 3 | ~1h | Reliability A, Security A- | PITR drill + alarm audit + security verification |
| Phase 4 | ~1h | Observability A- | Structured route logging |
| Phase 5 | ~30m | Operability A- | Audit script + runbook verification |
| **Phase 6** | **~4h** | **All dimensions A** | CDK adoption + CI scanning + dashboard + INT_LAYER + OPERATOR_GUIDE |
| **Total** | **~9.5h** | **Straight A** | |
