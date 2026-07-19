# Life Platform — Operator Guide

> **Status:** canonical · **Owner:** Matthew · **Verified:** 2026-05-19

> Everything you need to run this platform. Read this on Day 1.
> For architectural decisions: ARCHITECTURE.md
> For emergency procedures: RUNBOOK.md
> For deployment steps: QUICKSTART.md
> Last updated: 2026-05-19 (V2 audit refresh)

---

## System in 60 Seconds

The Life Platform is a personal health intelligence system. It pulls data from ~19 sources (wearables, apps, food logs, labs), stores everything in DynamoDB single-table (`life-platform`, us-west-2), and makes it queryable by Claude through 68 MCP tools. **94 Lambdas** run the ingest → compute → email pipeline daily.

**Pipeline (UTC, ADR-052):**
- Ingestion: 06:45-09:00 PT
- 16:30 UTC `character-sheet-compute` → 16:35 `adaptive-mode-compute` → 16:40 `daily-metrics-compute` → 16:45 `daily-insight-compute` → 17:00 `daily-brief`
- 11:30 PT OG images

AWS run-rate (real CE, 2026-06-08 sweep): steady-state **~$25-40/mo** against an **$85/mo enforced ceiling** (ADR-063 + ADR-133 amendment; $100 in reader-traffic surge mode; cost-governor degrades AI by tier). Bedrock AI is the swing factor and is in-budget. See `docs/COST_TRACKER.md`.

All infrastructure is CDK-managed across 9 stacks (`cdk/stacks/`).

---

## Day 1 Onboarding Checklist

Before you can operate the platform, you need:

1. **AWS auth**: `aws configure list` should show the `205930651321` account, region `us-west-2`. (Use SSO or aws-vault — never long-lived keys for daily work. Setup procedure: `docs/AWS_ACCESS.md`.)
2. **Pager off**: disable AWS CLI pager so commands don't block scripts:
   ```bash
   aws configure set cli_pager ""
   ```
3. **Git clone**: `~/Documents/Claude/life-platform/` is the canonical workdir.
4. **Read `docs/RUNBOOK.md`** end-to-end at least once.
5. **Bookmark these**:
   - https://averagejoematt.com/status/ — system health dashboard
   - https://averagejoematt.com/api/healthz — JSON health check
   - AWS Console → CloudWatch → Dashboards → `life-platform-ops`
   - AWS Console → SQS → `life-platform-ingestion-dlq`

---

## Daily Health Check (2 minutes)

1. **Visit** https://averagejoematt.com/status/
2. All sources should show **green**. Yellow = overdue. Red = broken.
3. Check inbox for any SNS alarm notifications from overnight (sent to `awsdev@mattsusername.com`).
4. Hit https://averagejoematt.com/api/healthz — should return `{"status": "ok"}`.
5. Verify daily-brief sent. Inbox check, or:
   ```bash
   aws logs tail /aws/lambda/daily-brief --since 24h | tail -50
   ```
6. If anything is red, follow "Responding to Failures" below.

---

## Weekly Operational Rhythm

| Day | Check |
|-----|-------|
| Monday | Monday Compass email sent? (`aws logs tail /aws/lambda/monday-compass --since 12h`) |
| Wednesday | Chronicle email sent? Both `wednesday-chronicle` (08:00 PT, compute) AND `chronicle-email-sender` (08:10 PT, email) Lambdas should have run. Re-enabled in V2 P3. |
| Friday | Weekly Plate email sent? (`weekly-plate`) |
| Saturday | Nutrition review email sent? (`nutrition-review`) |
| Sunday | Hypothesis engine ran + Weekly Digest sent? (`hypothesis-engine`, `weekly-digest`) |
| Any time | Glance at CloudWatch dashboard `life-platform-ops`. Investigate any alarms in ALARM state. |

---

## Responding to Failures

### A Lambda is erroring

1. Find the Lambda name from the alarm email or status page.
2. Read the most recent log:
   ```bash
   aws logs tail /aws/lambda/<function-name> --since 2h --follow
   ```
3. Common fixes:
   - `AccessDenied` → IAM role missing permission. Check `cdk/stacks/role_policies.py`, then `cd cdk && npx cdk diff && npx cdk deploy <stack>`.
   - `ResourceNotFoundException` on secret → secret deleted or in deletion window. Run `aws secretsmanager list-secrets --include-planned-deletion`.
   - `ImportModuleError` → stale code or wrong handler. Redeploy: `bash deploy/deploy_lambda.sh <function-name>`.
   - `AttributeError` on a recently-added shared function → some functions missed the last fleet deploy (stale bundle). Fleet-redeploy: `bash deploy/deploy_fleet.sh` (or `cd cdk && npx cdk deploy --all`).
   - For MCP: `bash deploy/deploy_lambda.sh life-platform-mcp` (since #781 it stages the mcp-shaped full bundle). Never hand-roll a partial zip — missing `lambdas/` tree = import failure at boot.

### A data source is stale

1. Identify the source from `https://averagejoematt.com/status/`.
2. Read the ingestion Lambda's logs.
3. Common causes:
   - OAuth token expired → re-run the auth setup (see `setup/` directory). For Garmin: `python3 setup/setup_garmin_browser_auth.py` (Playwright/Chromium). For Withings: `python3 setup/fix_withings_oauth.py`.
   - `auth_breaker` tripped → clear the marker (see RUNBOOK "Garmin: 429 Too Many Requests" section for the procedure; same pattern applies to all OAuth sources).
   - Upstream API outage → wait, retry.
   - Secret deleted or in deletion window → restore via Secrets Manager Console (the 7-day recovery window is your friend).

### DLQ has messages

The DLQ `life-platform-ingestion-dlq` is normally near-empty. As of 2026-05-19 it shows 66 messages — investigate via the dlq-consumer Lambda:

```bash
aws sqs get-queue-attributes \
  --queue-url https://sqs.us-west-2.amazonaws.com/205930651321/life-platform-ingestion-dlq \
  --attribute-names ApproximateNumberOfMessages
aws logs tail /aws/lambda/life-platform-dlq-consumer --since 1d | tail -50
```

The `life-platform-dlq-consumer` runs every 6 hours, logs failure context, and re-drives where possible. If accumulation persists, identify the root-cause Lambda from the consumer's logs and fix that.

### Daily brief didn't send

1. Read CloudWatch logs:
   ```bash
   aws logs tail /aws/lambda/daily-brief --since 6h | tail -100
   ```
2. Verify all upstream compute Lambdas succeeded (their failure degrades but should not block the brief):
   ```bash
   for fn in character-sheet-compute adaptive-mode-compute daily-metrics-compute daily-insight-compute; do
     echo "== $fn =="
     aws logs tail /aws/lambda/$fn --since 6h | tail -5
   done
   ```
3. Common causes: Anthropic API timeout or quota exhausted (check `LifePlatform/AI::AnthropicAPIFailure` metric), SES `AccessDenied` (verify `ses:SendEmail` on identity AND configuration-set ARN), config drift.
4. Manual trigger:
   ```bash
   aws lambda invoke --function-name daily-brief --payload '{}' \
     --cli-binary-format raw-in-base64-out /tmp/brief.json && cat /tmp/brief.json
   ```

### Costs spiked

```bash
# MTD spend
aws ce get-cost-and-usage \
  --time-period Start=$(date -u +%Y-%m-01),End=$(date -u +%Y-%m-%d) \
  --granularity MONTHLY --metrics UnblendedCost --region us-east-1

# Group by service to find the spike
aws ce get-cost-and-usage \
  --time-period Start=$(date -u +%Y-%m-01),End=$(date -u +%Y-%m-%d) \
  --granularity MONTHLY --metrics UnblendedCost \
  --group-by Type=DIMENSION,Key=SERVICE --region us-east-1 \
  --query 'ResultsByTime[0].Groups[].{Service:Keys[0],Cost:Metrics.UnblendedCost.Amount}' --output table
```

If Anthropic is the cause, check the daily-brief AI token alarm `ai-tokens-daily-brief-daily` and the `LifePlatform/AI` metrics.

### MCP Tool Usage Audit

```bash
# What tools are clients actually using? (CloudWatch namespace: LifePlatform/MCP)
aws cloudwatch list-metrics --namespace LifePlatform/MCP --metric-name ToolInvocations \
  --query 'Metrics[*].Dimensions[?Name==`ToolName`].Value' --output text
```

V2 P4.1 finding (2026-05, registry then at ~133 tools): only ~11 used in 30 days. Executed as the #395 prune (143→60, 2026-07-08) — ledger: `docs/MCP_TOOL_AUDIT.md`.

---

## Deployment Procedures

| Change | Command | Notes |
|--------|---------|-------|
| Single Lambda code | `bash deploy/deploy_lambda.sh <name>` | Auto-reads handler config from AWS |
| Single Lambda code + smoke | `bash deploy/deploy_and_verify.sh <name>` | Preferred for non-trivial changes |
| MCP server | `bash deploy/deploy_lambda.sh life-platform-mcp` | Stages the mcp-shaped full bundle since #781; never hand-roll a partial zip |
| Website | `bash deploy/sync_site_to_s3.sh` | Uses `safe_sync.sh` wrapper; targets `s3://matthew-life-platform/site/` |
| Shared module (`lambdas/` root) | Merge to main (CI fleet-deploys) or `bash deploy/deploy_fleet.sh` | ONE bundle per function (#781) — no layer step |
| CDK stack | `cd cdk && npx cdk diff <Stack> && npx cdk deploy <Stack>` | Always diff first |
| Full CDK redeploy | `cd cdk && npx cdk deploy --all` | After layer bump or cross-stack changes |

**Rollback procedure:** see `docs/RUNBOOK.md` → "Rolling Back a Failed Lambda".

---

## Key URLs

| URL | Purpose |
|-----|---------|
| https://averagejoematt.com/ | Public site |
| https://averagejoematt.com/status/ | System health dashboard |
| https://averagejoematt.com/api/healthz | Health check endpoint (JSON) |
| AWS Console → CloudWatch → Dashboards → `life-platform-ops` | Ops metrics |
| AWS Console → SQS → `life-platform-ingestion-dlq` | Dead letter queue (retention 14d) |
| MCP Lambda URL | `<not committed — SEC-02 #780; read live: aws lambda get-function-url-config --function-name life-platform-mcp --region us-west-2>` |

---

## Secrets & Credentials

- **12 active secrets** in AWS Secrets Manager under `life-platform/` prefix (as of 2026-05-19).
- **0 in deletion window** (live-verified 2026-07-10). Note: `notion` was RESTORED 2026-05-24 and is live-but-idle — flagged retire-candidate in `SECRETS_MAP.md` (owner decision pending).
- OAuth tokens (Whoop, Withings, Strava, Garmin, Eight Sleep) auto-refresh on each successful API call.
- MCP API key auto-rotates every 90 days via `life-platform-key-rotator`.
- `pipeline-health-check` Lambda probes all secrets daily and emits CloudWatch metrics.
- **Never** store secrets in code, env vars, or documentation.
- See `docs/SECRETS_MAP.md` (inventory + consumer map) and `docs/SECRETS_ROTATION.md` (rotation procedures).

---

## Pipeline Ordering (Critical)

The pipeline runs in strict order (ADR-052). Changing schedules without maintaining this order produces stale results.

```
06:45-09:00 PT     →  Ingestion (multiple Lambdas fetch from APIs)
09:05 PT (16:05Z)  →  Anomaly detector
16:30 UTC          →  character-sheet-compute
16:35 UTC          →  adaptive-mode-compute
16:40 UTC          →  daily-metrics-compute
16:45 UTC          →  daily-insight-compute
17:00 UTC          →  daily-brief (4 AI calls → email + S3 files; async-invokes coach-quality-gate per coach)
11:30 PT           →  OG image generator
```

All EventBridge crons are fixed UTC. PT references shift 1 hour at DST boundaries; UTC never does.

---

## Concurrency Limit (Active Constraint)

**Account-wide Lambda concurrency limit: 100** (raised from 10; verified live 2026-07-10 via `aws lambda get-account-settings`).

The 2026-05 raise request (Support case 177921309700709) was approved — the limit is 100 (AWS default for mature accounts is 1000; a further raise hasn't been needed). Operational habits that still apply:

- Avoid invoking high-fan-out workflows manually during the daily pipeline window (16:30-17:00 UTC).
- Reserved concurrency in CDK is **pre-staged but commented out** (see `docs/RESERVED_CONCURRENCY.md`).
- Throttled invocations land in the DLQ — if you see DLQ growth during the compute window, suspect concurrency.

---

## Emergency Contacts

- Platform builder: Matthew
- AWS account: **205930651321** (us-west-2)
- Alert SNS topic: `life-platform-alerts` → email to `awsdev@mattsusername.com`
- CloudFront distribution: `E3S424OXQZ8NBE`
- The 2026-05-19 concurrency-raise Support case (177921309700709) was RESOLVED — limit is 100 now

---

**Verified:** 2026-05-19 (V2 audit operational sweep)
