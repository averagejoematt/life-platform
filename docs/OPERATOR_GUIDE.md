# Life Platform — Operator Guide

> Everything you need to run this platform. Read this on Day 1.
> For architectural decisions: ARCHITECTURE.md
> For emergency procedures: RUNBOOK.md
> For deployment steps: QUICKSTART.md
> Last updated: 2026-03-30 (v4.5.1)

---

## System in 60 Seconds

The Life Platform is a personal health intelligence system. It pulls data from 26 sources (wearables, apps, food logs, labs), stores everything in DynamoDB, and makes it queryable by Claude through 118 MCP tools. A pipeline of 60 Lambdas runs daily: ingestion (6:45-9 AM PT) feeds compute (10:20-10:35 AM) which feeds the daily brief email + website update (11 AM). The public website at averagejoematt.com has 68 pages serving real-time health data.

Monthly cost: ~$19 (including WAF). All infrastructure is CDK-managed across 8 stacks.

---

## Daily Health Check (2 minutes)

1. **Visit** https://averagejoematt.com/status/
2. All sources should show **green**. Yellow = overdue. Red = broken.
3. Check email for any SNS alarm notifications from overnight
4. Hit https://averagejoematt.com/api/healthz — should return `{"status": "ok"}`
5. If anything is red: see "Responding to Failures" below

---

## Weekly Operational Rhythm

| Day | Check |
|-----|-------|
| Monday | Monday Compass email sent? (CloudWatch: `monday-compass`) |
| Wednesday | Chronicle email sent? (CloudWatch: `wednesday-chronicle`) |
| Saturday | Nutrition review email sent? (CloudWatch: `nutrition-review`) |
| Sunday | Hypothesis engine ran? (CloudWatch: `hypothesis-engine`) |
| Any time | Glance at CloudWatch dashboard: `life-platform-ops` |

---

## Responding to Failures

### A Lambda is erroring
1. Find the Lambda name from the alarm email
2. Check CloudWatch logs: **AWS Console → Lambda → [function name] → Monitor → View logs**
3. Read the most recent error
4. Common fixes:
   - `AccessDenied` → IAM role missing permission → check `cdk/stacks/role_policies.py`
   - `ResourceNotFoundException` on secret → secret was deleted → check Secrets Manager
   - `ImportModuleError` → stale code → redeploy: `bash deploy/deploy_lambda.sh [function-name]`
   - `logger.set_date` → stale platform_logger.py → rebuild shared layer: `bash deploy/build_layer.sh`

### A data source is stale
1. Check the status page to identify which source
2. Check the ingestion Lambda's CloudWatch logs
3. Common causes:
   - OAuth token expired → re-run auth setup (e.g., `python3 setup/fix_withings_oauth.py`)
   - Upstream API down → wait and monitor
   - Lambda code bug → fix and redeploy
   - Secret deleted → check Secrets Manager, restore if in recovery window

### DLQ has messages
1. Check DLQ depth: status page or `aws sqs get-queue-attributes --queue-url [url]`
2. DLQ messages are failed async Lambda invocations
3. The `dlq-consumer` Lambda processes them on schedule (every 6 hours)
4. If messages accumulate: check which Lambda is failing and fix the root cause

### Daily brief didn't send
1. Check CloudWatch logs for `daily-brief` Lambda
2. Common causes: upstream compute Lambda failed, AI API timeout, SES issue
3. The brief reads pre-computed results — if compute Lambdas failed, sections degrade gracefully
4. Manual trigger: invoke `daily-brief` Lambda from AWS Console with empty test event

---

## Deployment Procedures

| Change | Command | Notes |
|--------|---------|-------|
| Single Lambda | `bash deploy/deploy_lambda.sh [name] lambdas/[name]_lambda.py` | Auto-reads handler config |
| MCP server | Full zip build (see RUNBOOK) | **NEVER** use deploy_lambda.sh for MCP |
| Website | `bash deploy/sync_site_to_s3.sh` | Validates, syncs, invalidates CDN |
| Shared layer module | `bash deploy/build_layer.sh` then redeploy dependents | Rebuilds layer for all consumers |
| CDK stack | `cd cdk && npx cdk diff [Stack] && npx cdk deploy [Stack]` | Always diff first |

---

## Key URLs

| URL | Purpose |
|-----|---------|
| https://averagejoematt.com/ | Public site |
| https://averagejoematt.com/status/ | System health dashboard |
| https://averagejoematt.com/api/healthz | Health check endpoint (JSON) |
| https://dash.averagejoematt.com/ | Private analytics dashboard |
| AWS Console → CloudWatch → Dashboards → `life-platform-ops` | Ops metrics |
| AWS Console → SQS → `life-platform-ingestion-dlq` | Dead letter queue |

---

## Secrets & Credentials

- All 10 secrets in AWS Secrets Manager under `life-platform/` prefix
- OAuth tokens (Whoop, Withings, Strava, Garmin) auto-refresh — if broken, re-run auth setup
- MCP API key auto-rotates every 90 days via `life-platform-key-rotator`
- `pipeline-health-check` Lambda probes all secrets daily at 6 AM PT
- **Never** store secrets in code, env vars, or documentation

---

## Pipeline Ordering (Critical)

The pipeline runs in strict order. Changing schedules without maintaining this order produces stale results.

```
06:45-09:00 AM PT  →  Ingestion (13 Lambdas fetch from APIs)
09:05 AM           →  Anomaly detector
10:20-10:35 AM     →  Compute (metrics, day grade, character sheet, adaptive mode)
11:00 AM           →  Daily brief (reads ALL computed + raw → 4 AI calls → email + 4 S3 files)
11:30 AM           →  OG image generator
```

---

## Emergency Contacts

- Platform builder: Matthew
- AWS account: 205930651321 (us-west-2)
- Alert SNS topic: `life-platform-alerts` → email notifications
- CloudFront distribution: `E3S424OXQZ8NBE`
