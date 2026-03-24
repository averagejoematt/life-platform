# Life Platform — Onboarding Guide

> Start here. Everything else is reference material.
> Last updated: 2026-03-24 (v3.9.8)

---

## What Is This?

A personal health intelligence system built on AWS. It pulls data from 20 sources (wearables, apps, manual logs), stores everything in a single DynamoDB table, and makes it queryable by Claude through a Lambda-backed MCP server.

The end result: ask Claude a natural-language question about your health, and it queries real data rather than relying on memory or estimates.

---

## How to Navigate the Docs

| File | Purpose |
|------|---------|
| **ONBOARDING.md** (this file) | Start here — mental model + key concepts |
| `ARCHITECTURE.md` | Full system design, all AWS resources, data flows |
| `RUNBOOK.md` | How to operate the platform (deploys, re-auth, troubleshooting) |
| `SCHEMA.md` | Every DynamoDB field per source |
| `PROJECT_PLAN.md` | Active roadmap and backlog |
| `CHANGELOG.md` | Version history (current 30 days) |
| `PLATFORM_GUIDE.md` | How to use the platform + all MCP tools in conversation with Claude |
| `MCP_TOOL_CATALOG.md` | Full catalog of all 95 tools |
| `deploy/README.md` | Guide to the deploy scripts |
| `DATA_FLOW_DIAGRAM.md` | Visual data flow (Mermaid diagrams) |

---

## System at a Glance

```
19 data sources
    ↓
13 ingestion Lambdas (scheduled + webhook)
    ↓
DynamoDB (single table) + S3 (raw backup)
    ↓
MCP Lambda (95 tools) ← Claude queries this
    ↓
49 compute/email/operational Lambdas
    ↓
Daily Brief email + Dashboard + Weekly emails + averagejoematt.com
```

All infrastructure is AWS, us-west-2. CDK manages all 8 stacks. Monthly cost: ~$13.

---

## Key Mental Models

### 1. Single-table DynamoDB

Every data source writes to one table: `life-platform`. The key schema is:

```
PK: USER#matthew#SOURCE#<source>   (e.g. USER#matthew#SOURCE#whoop)
SK: DATE#YYYY-MM-DD
```

To look up today's Whoop data: PK = `USER#matthew#SOURCE#whoop`, SK = `DATE#2026-03-15`. No GSI — all access patterns work with this composite key.

### 2. Ingestion → Compute → Email pipeline

Data flows in one direction, with timing enforced by EventBridge:

```
07:00–09:00 AM  →  Ingestion Lambdas (fetch from APIs + webhook)
10:20–10:45 AM  →  Compute Lambdas (pre-compute metrics, character sheet)
11:00 AM        →  Daily Brief (reads pre-computed results, sends email)
```

If a compute Lambda fails, the Brief will degrade gracefully (missing section) rather than fail entirely.

### 3. MCP tools are read-only (mostly)

The MCP Lambda queries DynamoDB and returns results. Tools never write to ingestion partitions. The only writes are: cache entries (CACHE#matthew), and supplement/memory writes via dedicated tools.

### 4. CDK owns infrastructure

Never create Lambda roles, EventBridge rules, or alarms manually. Everything goes through `cdk/stacks/`. Run `cd cdk && npx cdk deploy <StackName>` after code changes that affect IAM or scheduling.

### 5. Secrets are in Secrets Manager

No credentials in code or environment variables. All secrets live under prefix `life-platform/` in Secrets Manager. 10 active secrets as of v3.9.4.

---

## The Data Sources (19)

| Category | Sources |
|----------|---------|
| Wearables | Whoop (recovery, HRV, sleep), Eight Sleep (bed environment), Garmin (steps, body battery), Withings (weight, body composition) |
| Fitness | Strava (activities, training load) |
| Nutrition | MacroFactor (calories, macros, food log via Dropbox CSV) |
| Health tracking | Apple Health via Health Auto Export webhook (CGM, blood pressure, gait, steps) |
| Productivity | Todoist (tasks), Notion (journal) |
| Lifestyle | Habitify (habits), Weather (Open-Meteo) |
| Manual/periodic | Labs (blood work), DEXA (body comp scan), Genome (SNPs), Supplements |
| Derived | Day grade, Habit scores, Character sheet, Computed metrics |

---

## Your Development Setup

### Prerequisites
- AWS CLI configured for account `205930651321` / `us-west-2`
- Node.js 18+ (for CDK)
- Python 3.12 with venv
- Claude Desktop with `mcp_bridge.py` running

### Clone and install
```bash
cd ~/Documents/Claude/life-platform
python3 -m venv .venv
source .venv/bin/activate
pip install -r cdk/requirements.txt
pip install boto3 anthropic
```

### CDK setup (first time)
```bash
cd cdk
npm install -g aws-cdk
pip install -r requirements.txt
cdk bootstrap aws://205930651321/us-west-2   # one-time
```

### Run the MCP bridge locally
```bash
python3 mcp_bridge.py
```
The bridge translates Claude Desktop's stdio MCP calls into HTTPS requests to the Lambda Function URL.

---

## Common Tasks (Quick Reference)

| Task | Command/File |
|------|-------------|
| Deploy a Lambda | `bash deploy/deploy_lambda.sh <function-name>` |
| Deploy + verify | `bash deploy/deploy_and_verify.sh <function-name>` |
| Check all Lambda logs | AWS Console → CloudWatch → Log groups |
| Re-auth Withings | `python3 setup/fix_withings_oauth.py` |
| Setup Google Calendar | `python3 setup/setup_google_calendar_auth.py` |
| Run QA smoke | AWS Console → Lambda → `qa-smoke` → Test |
| See today's freshness | Ask Claude: "get_data_freshness" |
| Enter maintenance mode | `bash deploy/maintenance_mode.sh enable` |
| CDK deploy (all stacks) | `cd cdk && npx cdk deploy --all` |
| CDK deploy (one stack) | `cd cdk && npx cdk deploy LifePlatformEmail` |

Stack names: `LifePlatformCore`, `LifePlatformIngestion`, `LifePlatformCompute`, `LifePlatformEmail`, `LifePlatformOperational`, `LifePlatformMcp`, `LifePlatformMonitoring`, `LifePlatformWeb`

---

## Session Handover Protocol

Every development session ends with a handover file written to `handovers/`. Use the Claude prompt:

> "Write a session handover"

The handover captures: version bump, what changed, what's pending, and context for the next session. This is how context is preserved across Claude's session limits.

Handovers live at `handovers/YYYY-MM-DD-session<N>-<slug>.md`. The latest is always symlinked/referenced from `docs/HANDOVER_LATEST.md`.

---

## Where Things Can Go Wrong

| Symptom | Likely cause | Fix |
|---------|-------------|-----|
| Withings data gap | OAuth token expired | `python3 setup/fix_withings_oauth.py` |
| Daily Brief missing sections | Compute Lambda failed upstream | Check CloudWatch logs for `daily-metrics-compute` |
| MacroFactor data stale | CSV not dropped to Dropbox folder | Manually export from MacroFactor → drop to Dropbox folder |
| MCP tool timeout | Query too broad or cold start | Narrow date range; wait for warm container |
| CDK deploy fails with IAM error | Policy change blocked by CI lint | Check `tests/test_iam_secrets_consistency.py` |
| Freshness checker alarm firing | Source hasn't updated in >48h | Check source Lambda logs; may need manual backfill |

---

## Architecture Review Schedule

Architecture reviews happen periodically. Run `python3 deploy/generate_review_bundle.py` first — it creates the bundle Claude needs to conduct the review. Reviews are stored in `docs/reviews/`. The platform is at review R17 (grade A-). CI/CD pipeline active (v3.9.4).
