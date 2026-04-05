# Life Platform — A-Grade Remediation Plan

> **Purpose:** Executable technical brief for Claude Code to bring all 10 architecture review dimensions to A grade.
> **Baseline:** R19 Architecture Review (2026-03-30, v4.5.0) — Composite B+
> **Target:** All dimensions at A or above
> **Cost rule:** Any change projected to increase monthly spend by >$1 in isolation → STOP and review with Matthew before implementing.
> **Generated:** 2026-03-30 by Technical Board of Directors

---

## Current State → Target

| # | Dimension | R19 Grade | Target | Gap Summary |
|---|-----------|-----------|--------|-------------|
| 1 | Architecture | B+ | A | Body-section doc contradictions, CDK adoption audit needed |
| 2 | Security | A- | A | Minor: IAM audit script, security.txt verification, input validation audit |
| 3 | Reliability | A- | A | PITR drill, alarm coverage verification |
| 4 | Observability | B+ | A | Per-route API metrics, consolidated ops dashboard |
| 5 | Cost | A | A | ✅ Maintain — no changes needed |
| 6 | Code Quality | B+ | A | INFRASTRUCTURE.md, ARCHITECTURE.md body, INCIDENT_LOG, Section 13b |
| 7 | Data Quality | A | A | ✅ Maintain — no changes needed |
| 8 | AI Rigour | A | A | ✅ Maintain — no changes needed |
| 9 | Operability | B | A | Docs must match reality, operator onboarding verification |
| 10 | Product | A | A | ✅ Maintain — no changes needed |

**Dimensions requiring work:** 1 (Architecture), 2 (Security), 3 (Reliability), 4 (Observability), 6 (Code Quality), 9 (Operability)

---

## Execution Order

Tasks are grouped into 5 phases. Each phase can be completed in a single Claude Code session. Phases should be executed in order — later phases depend on earlier ones.

---

## PHASE 1: Documentation Sprint (Code Quality B+ → A, Operability B → A-)

This is the single highest-impact phase. Elena Reyes (Code Quality) and Jin Park (SRE) both identified documentation as the #1 blocker to A grade. Every task in this phase is zero-cost.

### Task 1.1: INFRASTRUCTURE.md Full Update
**Finding:** R19-F01 (High)
**File:** `docs/INFRASTRUCTURE.md`
**What to do:**
1. Update header line to: `Last updated: 2026-03-30 (v4.5.0 — 60 Lambdas, 10 active secrets, 118 MCP tools, ~49 alarms)`
2. Delete the `google-calendar` row from the Secrets Manager table (permanently deleted 2026-03-15, ADR-030)
3. Delete `google-calendar-ingestion` from the Lambda listing under Ingestion
4. Delete the `webhook-key` "scheduled for deletion" note — it's been deleted
5. Update the Lambdas section count from "45" to "60"
6. Add all missing Lambdas to the appropriate category:
   - **Ingestion:** `food-delivery-ingestion`, `measurements-ingestion`
   - **Email/Digest:** `chronicle-email-sender`, `subscriber-onboarding`
   - **Compute:** `acwr-compute`, `sleep-reconciler`, `circadian-compliance`
   - **Infrastructure:** `site-stats-refresh`, `challenge-generator`, `og-image-generator`, `email-subscriber`, `pipeline-health-check`, `chronicle-approve`
7. Update MCP Server section: tools from "105" to "118", modules from "32" to "35"
8. Update the Secrets count to "10 active secrets" (add `site-api-ai-key` if missing)
9. Remove the note about `webhook-key` being "scheduled for deletion" — that's ancient history
10. Verify the `_updated` note in the Secrets section still says "Note: webhook-key scheduled for deletion 2026-03-15" — remove this entirely

**Validation:** After editing, run `grep -c "google-calendar" docs/INFRASTRUCTURE.md` — should return 0. Run `grep "52 Lambdas\|105 MCP\|45)" docs/INFRASTRUCTURE.md` — should return 0.

### Task 1.2: ARCHITECTURE.md Body-Section Reconciliation
**Finding:** R19-F02 (Medium)
**File:** `docs/ARCHITECTURE.md`
**What to do:**
1. In the Three-Layer Architecture diagram (ASCII art):
   - Change `MCP Server Lambda (95 tools, 768 MB)` → `MCP Server Lambda (118 tools, 768 MB)`
   - Change `averagejoematt.com (66 pages)` → `averagejoematt.com (68 pages)`
2. In the Serve Layer / MCP Server section:
   - Change `**Tools:** 95 | **Modules:** 31` → `**Tools:** 118 | **Modules:** 35`
   - Change `31-module package` → `35-module package`
3. In the overview paragraph:
   - Change `twenty-five sources` → `twenty-six sources`
4. In the Local Project Structure section:
   - Change `mcp/                            ← MCP server package (32 modules)` → `mcp/                            ← MCP server package (35 modules)`
   - Change `site/                           ← 12-page static website` → `site/                           ← 68-page static website`
   - Update the site/ subdirectory listing to reflect current pages (or remove the specific listing and just note "68 pages — see site/ directory")
   - Update the lambdas/ comment to note "60 Lambdas" not the partial list
5. In the Site API Lambda section:
   - Remove the stale Function URL `https://lxhjl2qvq2ystwp47464uhs2jti0hpdcq.lambda-url.us-east-1.on.aws/` — the Lambda is confirmed in us-west-2 (verified via AWS CLI 2026-03-30). Replace with the correct us-west-2 Function URL, or note "Function URL: see CloudFront origin config (routed through CloudFront, not called directly)"
6. In the Secrets Manager table:
   - Verify count says "9 active secrets" or update to "10 active secrets" if site-api-ai-key is counted
   - Remove any references to deleted secrets that aren't marked as deleted

**Validation:** After editing, `grep -n "95 tools\|31-module\|32 modules\|30 tool\|12-page\|66 pages\|twenty-five" docs/ARCHITECTURE.md` should return 0.

### Task 1.3: INCIDENT_LOG Update — Add 5 Missing Incidents
**Finding:** R19-F03 (Medium)
**File:** `docs/INCIDENT_LOG.md`
**What to do:**
1. Update header: `Last updated: 2026-03-30 (v4.5.0)`
2. Add these 5 incidents to the Incident History table (insert after the existing Mar 16 S3 wipe entry, in chronological order):

```
| 2026-03-19 | **P2** | Eight Sleep data ingestion down for 10 days | `logger.set_date` crash — Lambda had stale bundled `platform_logger.py` missing `set_date()` method. Same class of bug as 2026-03-09 P2 incident but on a Lambda that wasn't redeployed in the v3.3.8 batch fix. | 10 days (discovered during pipeline validation session) | ~30 min (hasattr guard + redeploy + re-auth after password change). 7 days backfilled. | No — backfill recovered missing data |
| 2026-03-19 | **P2** | Dropbox secret deleted — entire MacroFactor nutrition chain silently broken since Mar 10 | Secret `life-platform/ingestion-keys` was scheduled for deletion (7-day recovery window). Dropbox poll Lambda couldn't read credentials → MacroFactor CSV never downloaded → nutrition data stopped flowing. Undetected for 9 days. | 9 days (discovered during pipeline validation session) | ~15 min (restored secret from deletion recovery) | No — MacroFactor data backfilled after restore |
| 2026-03-19 | **P3** | Notion secret deleted — journal ingestion silently broken | Same pattern as Dropbox: secret scheduled for deletion and not caught. Notion journal entries stopped ingesting. | Days (discovered during pipeline validation) | ~10 min (restored secret) | No — re-ingested after restore |
| 2026-03-19 | **P3** | Health Auto Export webhook Lambda crash | `logger.set_date` bug — same root cause as Eight Sleep. Lambda had been redeployed with stale platform_logger.py. | Days (discovered during pipeline validation) | ~15 min (redeploy with current code) | No — webhook data in S3, reprocessed |
| 2026-03-19 | **P3** | Garmin ingestion broken — missing modules + expired tokens | garth/garminconnect modules missing from Lambda package. OAuth tokens expired. | Days (discovered during pipeline validation) | Partial — layer published (garth-layer:2), auth pending due to Garmin SSO rate limiting | Garmin data gap — auth retry pending |
```

3. Add to "Patterns & Observations" section:
   - New pattern: **"Silent secret deletion"** — Secrets Manager 7-day deletion recovery window can expire unnoticed. Two secrets (Dropbox, Notion) were scheduled for deletion and expired without any Lambda failing loudly (the Lambdas just couldn't read credentials and failed silently or with generic errors not connected to the specific secret). **Mitigation deployed:** `pipeline-health-check` Lambda (v4.4.0) now probes all 11 secrets daily at 6 AM PT and writes results to DynamoDB for status page overlay.
   - Update existing pattern: **"Stale lambda module caches"** — add note: "This pattern recurred in v4.4.0 despite the v3.3.8 batch fix. The v3.3.8 fix redeployed 13 ingestion Lambdas but missed Eight Sleep and Health Auto Export. Root fix: `hasattr(logger, 'set_date')` guard added to all 14 Lambdas."

### Task 1.4: Section 13b Update in generate_review_bundle.py
**Finding:** R19-F07 (Medium)
**File:** `deploy/generate_review_bundle.py`
**What to do:**
Add R17 and R18 finding dispositions to the Section 13b resolved findings table. Insert after the R13 findings table. The new section should look like:

```python
    sections.append("""
### R17 Findings (2026-03-20, v3.7.82)

| ID | Finding | Status | Version | Proof |
|----|---------|--------|---------|-------|
| R17-F01 | Public AI endpoints lack persistent rate limiting | ✅ RESOLVED | v4.3.0 | WAF WebACL deployed with SubscribeRateLimit (60/5min) and GlobalRateLimit (1000/5min) |
| R17-F02 | In-memory rate limiting resets on cold start | ✅ RESOLVED | v4.3.0 | WAF at CloudFront edge provides persistent rate limiting independent of Lambda lifecycle |
| R17-F03 | No WAF on public-facing CloudFront | ✅ RESOLVED | v4.3.0 | WAF WebACL attached to E3S424OXQZ8NBE |
| R17-F04 | Subscriber email verification has no rate limit | ✅ RESOLVED | v4.3.0 | WAF SubscribeRateLimit rule covers /api/subscribe* at 60/5min per IP |
| R17-F05 | Cross-region DynamoDB reads (site-api) | ✅ RESOLVED | v4.3.0 | Site-api confirmed in us-west-2 (AWS CLI verification 2026-03-30) |
| R17-F06 | No observability on public API endpoints | ⏳ PARTIAL | — | AskEndpointErrors alarm added. Full per-route dashboard still needed. |
| R17-F07 | CORS headers not evidenced | ✅ RESOLVED | v4.3.1 | CORS_HEADERS dict + OPTIONS handler confirmed in site_api_lambda.py |
| R17-F08 | google_calendar in config.py SOURCES | ✅ RESOLVED | v4.3.1 | Retired file only, not in active SOURCES list |
| R17-F09 | MCP Lambda memory discrepancy in docs | ✅ RESOLVED | v4.3.1 | Doc headers reconciled to 116 tools (now 118 at v4.5.0) |
| R17-F10 | Site API hardcoded model strings | ✅ RESOLVED | v4.3.1 | Using os.environ.get() pattern |
| R17-F11 | No privacy policy on public website | ✅ RESOLVED | v4.3.0 | /privacy/ directory exists |
| R17-F12 | PITR restore drill not executed | ⏳ PENDING | — | 7th consecutive review. Scheduled for Week 2 post-launch. |
| R17-F13 | 95 MCP tools — context window pressure | ⏳ WORSENED | — | Tools at 118. SIMP-1 Phase 2 deferred. ADR decision needed. |

### R18 Findings (2026-03-28, v4.3.0)

| ID | Finding | Status | Version | Proof |
|----|---------|--------|---------|-------|
| R18-F01 | Severe documentation drift | ⏳ PARTIAL | v4.3.1+ | Header reconciled; body sections still have contradictions. Phase 1 of this remediation plan addresses. |
| R18-F02 | CLI-created Lambdas outside CDK | ⏳ PARTIAL | v4.3.0 | OG image Lambda added to CDK. Other new Lambdas need audit. |
| R18-F03 | lambda_map.json stale | ✅ RESOLVED | v4.3.1 | Updated with all new Lambdas. CI orphan-file lint added. |
| R18-F04 | New resources without monitoring | ✅ RESOLVED | v4.3.1 | Alarms added for og-image, food-delivery, challenge, email-subscriber. Pipeline health check covers rest. |
| R18-F05 | 47-page manual S3 deploy | ✅ RESOLVED | v4.3.1 | deploy/deploy_site.sh created |
| R18-F06 | WAF rules too broad | ✅ RESOLVED | v4.3.1 | Endpoint-specific rules: /api/ask (100/5min), /api/board_ask (100/5min) |
| R18-F07 | SIMP-1 regression (95→110) | ⏳ WORSENED | — | Now 118. ADR decision needed. |
| R18-F08 | INTELLIGENCE_LAYER.md stale | ✅ RESOLVED | v4.3.1 | Freeze label applied with CHANGELOG redirect |
| R18-F09 | Cross-region split on 13+ routes | ✅ RESOLVED | v4.3.0 | Site-api confirmed us-west-2 (AWS CLI 2026-03-30). No cross-region reads. |
""")
```

### Task 1.5: SLOs.md Refresh
**Finding:** R19-F04 (Low)
**File:** `docs/SLOs.md`
**What to do:**
1. Update header: `Last updated: 2026-03-30 (v4.5.0)`
2. In SLO-2 (Data Source Freshness), update the monitored sources list:
   - Remove "Google Calendar" (retired, ADR-030)
   - Current monitored sources should be: Whoop, Withings, Strava, Todoist, Apple Health, Eight Sleep, MacroFactor, Garmin, Habitify, Notion Journal (10 sources with daily cadence)
   - Note: Food Delivery, Labs, DEXA, Genome are periodic/manual — not subject to 48h freshness SLO

### Task 1.6: RUNBOOK.md Verification Pass
**File:** `docs/RUNBOOK.md`
**What to do:**
1. Verify the header line matches current platform state (should already say v4.5.0 — if not, update)
2. Verify the "Common Mistakes" table is current
3. Add a new entry to Common Mistakes if not already present:
   - "Secret scheduled for deletion goes unnoticed" | "Data pipeline silently breaks when recovery window expires" | "pipeline-health-check Lambda probes all secrets daily. Check status page."

**Cost impact:** $0 (all documentation changes)

---

## PHASE 2: Architecture Integrity (Architecture B+ → A)

### Task 2.1: CDK Adoption Audit
**Purpose:** Verify all Lambdas are CDK-managed. CLI-created Lambdas drift silently (3 historical incidents traced to this pattern).
**What to do:**
1. Run: `aws lambda list-functions --region us-west-2 --query "Functions[].FunctionName" --output json`
2. Cross-reference against CDK stack definitions in `cdk/stacks/`:
   - Read each stack file and extract Lambda function names
   - Compare with the AWS output
   - List any Lambdas that exist in AWS but are NOT defined in any CDK stack
3. For each unmanaged Lambda found, document it with:
   - Function name
   - Creation date (from AWS)
   - Which CDK stack it should belong to
   - What needs to happen (add to stack definition)
4. Write findings to `docs/audits/AUDIT_2026-03-30_cdk_adoption.md`

**⚠️ DO NOT modify CDK stacks or run `cdk deploy` — just audit and document.** CDK stack changes can have cascading effects and need Matthew's review.

**Cost impact:** $0 (read-only audit)

### Task 2.2: SIMP-1 Phase 2 — ADR Decision
**Finding:** R19-F05 (Medium, 4th consecutive review)
**Purpose:** The Tech Board (Viktor, 12-2 vote) directed: either execute SIMP-1 Phase 2 (consolidate to ≤80 tools) or formally accept 118 as the operating state via ADR. Perpetual deferral is the worst outcome.
**What to do:**
1. Count current MCP tools: `grep -c "def tool_" mcp/tools_*.py` (each `tool_` function = one tool)
2. Also count from the TOOLS dict in `mcp_server.py`: `grep -c "'tool_" mcp_server.py`
3. Analyze tool usage patterns:
   - Identify tool modules with 5+ tools that could be consolidated into view-dispatchers (per ADR-035)
   - Identify tools that are strict subsets of other tools (e.g., `get_X_summary` vs `get_X_detail` where summary is just detail with fewer fields)
   - Identify tools with zero or near-zero usage (check CloudWatch logs if accessible, or just flag tools that seem redundant)
4. Write ADR-045 to `docs/DECISIONS.md`:

   **If consolidation to ≤80 is feasible within ~1 week of work:**
   Write ADR-045 as "SIMP-1 Phase 2: Tool consolidation plan — target ≤80 via view-dispatchers" with the specific consolidation plan.

   **If consolidation to ≤80 would require >2 weeks or break MCP functionality:**
   Write ADR-045 as "SIMP-1 Phase 2: Accept 118 tools as operating state" with rationale: tool breadth supports product depth across 26 data sources and 6 observatory domains. Context window impact managed by MCP cache warmer (14 pre-computed tools). Revisit if tool selection accuracy degrades measurably or context window limits are hit.

   **Either way, the finding is closed by making the decision explicit.**

**⚠️ REVIEW WITH MATTHEW:** Present the analysis and recommended ADR direction before writing it.

**Cost impact:** $0 (analysis and documentation)

---

## PHASE 3: Reliability & Security (Reliability A- → A, Security A- → A)

### Task 3.1: PITR Restore Drill
**Finding:** R17-F12 / R13-F07 (7th consecutive review!)
**Purpose:** Prove that DynamoDB Point-in-Time Recovery actually works. This has been flagged since Review #13 and is Jin Park's #1 item.
**What to do:**
1. Pick a safe test: restore to a new table (not the production table)
2. Run the drill:
```bash
# Restore to a test table from 1 hour ago
aws dynamodb restore-table-to-point-in-time \
  --source-table-name life-platform \
  --target-table-name life-platform-pitr-drill-2026-03-30 \
  --use-latest-restorable-time \
  --region us-west-2
```
3. Wait for restore to complete (check status):
```bash
aws dynamodb describe-table --table-name life-platform-pitr-drill-2026-03-30 --region us-west-2 --query "Table.TableStatus"
```
4. Verify data integrity:
```bash
# Count items in restored table
aws dynamodb scan --table-name life-platform-pitr-drill-2026-03-30 --select COUNT --region us-west-2
# Compare with production
aws dynamodb scan --table-name life-platform --select COUNT --region us-west-2
# Spot-check a few records
aws dynamodb get-item --table-name life-platform-pitr-drill-2026-03-30 --key '{"PK":{"S":"USER#matthew#SOURCE#whoop"},"SK":{"S":"DATE#2026-03-29"}}' --region us-west-2
```
5. Document results in `docs/audits/AUDIT_2026-03-30_pitr_drill.md`:
   - Restore duration
   - Item count comparison
   - Spot-check results
   - Any issues found
6. Clean up: delete the test table
```bash
aws dynamodb delete-table --table-name life-platform-pitr-drill-2026-03-30 --region us-west-2
```

**⚠️ COST FLAG: DynamoDB restore creates a new table with on-demand billing. The table exists only for verification (~minutes), so cost is negligible (<$0.01). The delete command removes it immediately. But flag this for Matthew's awareness.**

### Task 3.2: Alarm Coverage Verification
**Purpose:** Verify every Lambda has a CloudWatch error alarm. "Every Lambda has an alarm" was the operational contract established at R17 — we need to confirm it still holds at 60 Lambdas.
**What to do:**
1. Get all Lambda functions: `aws lambda list-functions --region us-west-2 --query "Functions[].FunctionName" --output json`
2. Get all CloudWatch alarms: `aws cloudwatch describe-alarms --region us-west-2 --query "MetricAlarms[?Namespace=='AWS/Lambda'].{Name:AlarmName,Metric:MetricName,Dimensions:Dimensions}" --output json`
3. Cross-reference: for each Lambda, verify there is at least one alarm with `MetricName=Errors` targeting that function
4. List any Lambdas without error alarms
5. For any gaps found, create the missing alarms using the established pattern:
```bash
aws cloudwatch put-metric-alarm \
  --alarm-name "life-platform-<function-name>-errors" \
  --namespace "AWS/Lambda" \
  --metric-name Errors \
  --dimensions Name=FunctionName,Value=<function-name> \
  --comparison-operator GreaterThanThreshold \
  --threshold 0 \
  --evaluation-periods 1 \
  --period 86400 \
  --statistic Sum \
  --alarm-actions "arn:aws:sns:us-west-2:205930651321:life-platform-alerts" \
  --treat-missing-data notBreaching \
  --region us-west-2
```
6. Document in `docs/audits/AUDIT_2026-03-30_alarm_coverage.md`

**Cost impact:** Each new CloudWatch alarm costs ~$0.10/month. Even if 10 are missing, that's $1/month total — right at the review threshold. **Flag for Matthew if >5 new alarms are needed.**

### Task 3.3: Security Hardening Verification
**Purpose:** Close the A- → A gap on security. Yael Cohen's remaining concerns from R18/R19.
**What to do:**
1. **Verify security.txt:** `curl -s https://averagejoematt.com/.well-known/security.txt` — confirm it exists and has contact info
2. **Verify security headers:** `curl -sI https://averagejoematt.com/ | grep -i "x-content-type\|x-frame\|strict-transport"` — confirm nosniff, DENY, HSTS are present
3. **WAF rule verification:** `aws wafv2 list-web-acls --scope CLOUDFRONT --region us-east-1 --query "WebACLs[].Name"` — confirm WAF is attached
4. **IAM role audit:** For each Lambda, verify the role follows least-privilege:
   - No role has `dynamodb:Scan` (confirmed policy)
   - Site-api role is read-only (no PutItem)
   - Run: `aws lambda get-function --function-name life-platform-site-api --region us-west-2 --query "Configuration.Role"`
   - Then: `aws iam list-attached-role-policies --role-name <role-name>` and `aws iam list-role-policies --role-name <role-name>`
   - Verify no `dynamodb:PutItem` or `dynamodb:Scan` in site-api policy
5. Document findings in `docs/audits/AUDIT_2026-03-30_security.md`

**Cost impact:** $0 (read-only verification)

---

## PHASE 4: Observability (Observability B+ → A)

### Task 4.1: Per-Route API Metrics in Site-API Lambda
**Purpose:** Jin Park and Marcus Webb both flagged: 65+ API endpoints with no per-route metrics. The site-api Lambda is a monolith serving all routes — we need to know which routes are slow, which error, and how often each is called.
**File:** `lambdas/site_api_lambda.py`
**What to do:**
1. Read the current site_api_lambda.py to understand the routing structure
2. Add a lightweight per-route metric emission at the end of each request:
```python
import time

def _emit_route_metric(route, duration_ms, status_code):
    """Emit per-route CloudWatch custom metric. Best-effort, never fails the request."""
    try:
        import boto3
        cw = boto3.client('cloudwatch', region_name='us-west-2')
        cw.put_metric_data(
            Namespace='LifePlatform/SiteApi',
            MetricData=[
                {
                    'MetricName': 'RouteLatency',
                    'Dimensions': [{'Name': 'Route', 'Value': route}],
                    'Value': duration_ms,
                    'Unit': 'Milliseconds'
                },
                {
                    'MetricName': 'RouteCount',
                    'Dimensions': [{'Name': 'Route', 'Value': route}],
                    'Value': 1,
                    'Unit': 'Count'
                }
            ]
        )
    except Exception:
        pass  # Never fail the request for metrics
```
3. Wrap the main handler's route dispatch with timing:
```python
start = time.time()
# ... existing route dispatch ...
duration_ms = (time.time() - start) * 1000
_emit_route_metric(route_name, duration_ms, status_code)
```
4. Ensure the site-api IAM role has `cloudwatch:PutMetricData` permission. Check `cdk/stacks/` for the relevant role and add if missing.

**⚠️ COST FLAG: CloudWatch custom metrics cost $0.30/metric/month. With ~15 unique routes × 2 metrics (latency + count) = 30 custom metrics = ~$9/month. This EXCEEDS the $1 threshold. REVIEW WITH MATTHEW before implementing.**

**Alternative (zero-cost):** Instead of CloudWatch custom metrics, log structured JSON to CloudWatch Logs and use CloudWatch Logs Insights for ad-hoc queries. This approach uses existing log storage (no incremental cost) but doesn't give real-time dashboards:
```python
import json
print(json.dumps({
    "metric_type": "route",
    "route": route_name,
    "duration_ms": duration_ms,
    "status": status_code,
    "timestamp": datetime.utcnow().isoformat()
}))
```
Then query with: `fields route, avg(duration_ms) | filter metric_type="route" | stats count(*) as requests, avg(duration_ms) as avg_latency by route | sort requests desc`

**Recommendation:** Use the structured logging approach ($0 cost). Create a saved CloudWatch Logs Insights query that Matthew can run on-demand.

### Task 4.2: Consolidated Ops Dashboard Verification
**Purpose:** Verify the `life-platform-ops` CloudWatch dashboard exists and has the SLO widgets described in SLOs.md.
**What to do:**
1. Check: `aws cloudwatch get-dashboard --dashboard-name life-platform-ops --region us-west-2`
2. If it exists, verify it includes:
   - SLO-1 through SLO-4 alarm status widgets
   - Lambda error rates for critical functions (daily-brief, MCP, site-api)
   - DLQ depth metric
3. If it doesn't exist or is incomplete, create/update it with the widgets described in SLOs.md
4. Add a new widget for pipeline-health-check results (reads from DynamoDB status data)

**⚠️ COST FLAG: CloudWatch dashboards cost $3/month per dashboard. If we're creating a NEW dashboard, this exceeds $1. If updating an existing one, it's $0 incremental. Check first and flag if new.**

### Task 4.3: Structured Logging for Site-API Routes
**Purpose:** Enable per-route observability without CloudWatch custom metric cost.
**File:** `lambdas/site_api_lambda.py`
**What to do:**
1. Add structured JSON logging at the end of each request handler:
```python
import json, time

# At start of handler:
_start = time.time()

# At end of handler (before return):
print(json.dumps({
    "_type": "route_metric",
    "route": route_path,
    "method": http_method,
    "status": status_code,
    "duration_ms": round((time.time() - _start) * 1000, 1),
    "cold_start": getattr(lambda_context, '_cold_start', False)
}))
```
2. Create a saved Logs Insights query file at `deploy/queries/site_api_route_metrics.txt`:
```
fields @timestamp, route, duration_ms, status
| filter _type = "route_metric"
| stats count(*) as requests, avg(duration_ms) as avg_ms, max(duration_ms) as max_ms, sum(status >= 500) as errors by route
| sort requests desc
```
3. Deploy the Lambda: `bash deploy/deploy_lambda.sh life-platform-site-api`

**Cost impact:** $0 (uses existing CloudWatch Logs allocation)

---

## PHASE 5: Operability Polish (Operability B → A)

### Task 5.1: System State Audit Script Update
**Purpose:** `deploy/audit_system_state.sh` was created in v4.3.1 to catch doc drift. Verify it works and covers all current state.
**File:** `deploy/audit_system_state.sh`
**What to do:**
1. Read the current script
2. Verify it checks:
   - Lambda count vs ARCHITECTURE.md header
   - MCP tool count vs ARCHITECTURE.md header
   - Site page count vs ARCHITECTURE.md header
   - Secret count vs INFRASTRUCTURE.md
   - CDK stack count
3. Run it and fix any false positives from stale expected values
4. Add to the script: a check that INFRASTRUCTURE.md header version matches ARCHITECTURE.md header version (they should reference the same platform version)

**Cost impact:** $0

### Task 5.2: Operator Quick-Start Verification
**Purpose:** An A-grade operability score means a new operator can understand and run the system from documentation alone.
**What to do:**
1. Read `docs/QUICKSTART.md` (if it exists) or `docs/RUNBOOK.md`
2. Verify it covers:
   - How to deploy a Lambda change (answer: `bash deploy/deploy_lambda.sh <name>`)
   - How to deploy a site change (answer: `bash deploy/deploy_site.sh` or `bash deploy/sync_site_to_s3.sh`)
   - How to deploy an MCP change (answer: full zip build, see ADR-031)
   - How to check system health (answer: visit averagejoematt.com/status/ or run `pipeline-health-check`)
   - How to check data freshness (answer: freshness-checker or status page)
   - How to respond to an alarm (answer: check CloudWatch logs for the alarming Lambda)
   - How to do a PITR restore (answer: see Task 3.1 procedure)
3. If any of these are missing, add them to the appropriate doc
4. Verify the "Common Mistakes" table in RUNBOOK.md is complete

### Task 5.3: CHANGELOG Entry for This Remediation
**File:** `docs/CHANGELOG.md`
**What to do:**
Prepend a new version entry at the top of CHANGELOG.md:
```markdown
## v4.5.1 — 2026-03-30: R19 Architecture Review Remediation

### Documentation (R19-F01, R19-F02, R19-F03, R19-F04, R19-F07)
- INFRASTRUCTURE.md full update: removed google-calendar references, added 15 missing Lambdas, updated all counts to 60 Lambdas / 118 MCP tools / 10 secrets
- ARCHITECTURE.md body-section reconciliation: all numeric references in body now match header (118 tools, 68 pages, 35 modules, 26 sources)
- INCIDENT_LOG updated with 5 v4.4.0 incidents (Eight Sleep, Dropbox, Notion, HAE, Garmin) + new "silent secret deletion" pattern
- SLOs.md: removed google-calendar from monitored sources, updated header
- Section 13b: added R17 + R18 findings with disposition to generate_review_bundle.py

### Reliability (R17-F12)
- PITR restore drill executed and documented — 7th consecutive review finding finally closed
- Alarm coverage audit: [N] Lambdas verified, [M] missing alarms added

### Security
- Security hardening audit documented (security.txt, headers, WAF, IAM least-privilege verified)

### Observability
- Site-API structured route logging: per-route JSON metrics in CloudWatch Logs
- Saved Logs Insights query for route-level latency/error analysis

### Architecture (R19-F05)
- ADR-045: SIMP-1 Phase 2 decision — [consolidation plan / accept 118]
- CDK adoption audit documented

### Operations
- audit_system_state.sh updated for v4.5.0 expected values
- Operator runbook verification pass
```

---

## Post-Remediation: Expected Grade Movement

| # | Dimension | R19 | Post-Remediation | Evidence |
|---|-----------|-----|-----------------|----------|
| 1 | Architecture | B+ | A | CDK audit documented, SIMP-1 ADR written, body-section contradictions resolved |
| 2 | Security | A- | A | Security audit documented, all verification passing, WAF confirmed |
| 3 | Reliability | A- | A | PITR drill executed (7-review finding closed), alarm coverage verified at 100% |
| 4 | Observability | B+ | A | Per-route structured logging, ops dashboard verified, pipeline health check proven |
| 5 | Cost | A | A | Maintained — no cost-increasing changes without approval |
| 6 | Code Quality | B+ | A | All 3 stale docs updated, Section 13b current, INCIDENT_LOG complete |
| 7 | Data Quality | A | A | Maintained |
| 8 | AI Rigour | A | A | Maintained |
| 9 | Operability | B | A | Docs match reality, operator runbook verified, audit scripts functional |
| 10 | Product | A | A | Maintained |

---

## Execution Checklist

```
Phase 1: Documentation Sprint
[ ] 1.1 INFRASTRUCTURE.md full update
[ ] 1.2 ARCHITECTURE.md body-section reconciliation
[ ] 1.3 INCIDENT_LOG — add 5 missing incidents
[ ] 1.4 Section 13b — add R17/R18 findings to generate_review_bundle.py
[ ] 1.5 SLOs.md refresh
[ ] 1.6 RUNBOOK.md verification pass

Phase 2: Architecture Integrity
[ ] 2.1 CDK adoption audit (document only, no deploys)
[ ] 2.2 SIMP-1 Phase 2 ADR decision (⚠️ review with Matthew)

Phase 3: Reliability & Security
[ ] 3.1 PITR restore drill (⚠️ flag for Matthew — creates temp table)
[ ] 3.2 Alarm coverage verification (⚠️ flag if >5 new alarms needed)
[ ] 3.3 Security hardening verification

Phase 4: Observability
[ ] 4.1 Per-route metrics decision (⚠️ COST FLAG — use structured logging, not custom metrics)
[ ] 4.2 Ops dashboard verification (⚠️ flag if new dashboard needed)
[ ] 4.3 Structured logging for site-api routes + saved query

Phase 5: Operability Polish
[ ] 5.1 audit_system_state.sh update
[ ] 5.2 Operator quick-start verification
[ ] 5.3 CHANGELOG entry + version bump
[ ] 5.4 git add -A && git commit -m "v4.5.1: R19 remediation — all dimensions to A" && git push
```

---

## Cost Summary

| Item | Monthly Cost | Flagged? |
|------|-------------|----------|
| Phase 1 (docs) | $0 | No |
| Phase 2 (audit + ADR) | $0 | No |
| Phase 3 PITR drill | <$0.01 (temp table, deleted immediately) | Yes — awareness |
| Phase 3 new alarms | ~$0.10/alarm × N | Yes if >5 alarms |
| Phase 4 custom metrics | ~$9/month | **YES — DO NOT IMPLEMENT. Use structured logging instead ($0)** |
| Phase 4 structured logging | $0 | No |
| Phase 4 new dashboard | $3/month if new | Yes — check if existing first |
| Phase 5 (docs) | $0 | No |
| **Total expected** | **$0 – $1** | Within budget |

---

*Plan generated by Technical Board of Directors, 2026-03-30. Approved for Claude Code execution with flagged review points.*
