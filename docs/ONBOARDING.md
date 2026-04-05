# Life Platform — Onboarding Guide

> Start here. For your first day, also read `docs/QUICKSTART.md` (AWS setup, deploy commands, gotchas).
> Last updated: 2026-03-29 (v4.4.0)

---

## What Is This?

A personal health intelligence system built on AWS. It pulls data from 13 API-based sources (wearables, apps, webhooks) plus manual/periodic uploads, stores everything in a single DynamoDB table (26 source partitions total), and makes it queryable by Claude through a Lambda-backed MCP server with 115 tools.

The end result: ask Claude a natural-language question about your health, and it queries real data rather than relying on memory or estimates.

---

## How to Navigate the Docs

| File | Purpose |
|------|---------|
| **ONBOARDING.md** (this file) | Start here — mental model + key concepts |
| `QUICKSTART.md` | Your first day — AWS setup, deploy commands, gotchas |
| `ARCHITECTURE.md` | Full system design, all AWS resources, data flows |
| `RUNBOOK.md` | How to operate the platform (deploys, re-auth, troubleshooting) |
| `SCHEMA.md` | Every DynamoDB field per source |
| `PROJECT_PLAN.md` | Active roadmap and backlog |
| `CHANGELOG.md` | Version history (current 30 days) |
| `PLATFORM_GUIDE.md` | How to use the platform + all MCP tools in conversation with Claude |
| `MCP_TOOL_CATALOG.md` | Full catalog of all 115 tools |
| `deploy/README.md` | Guide to the deploy scripts |
| `DEPENDENCY_GRAPH.md` | Full dependency map: Lambdas → DDB → MCP → website. SPOFs + critical path |
| `DATA_FLOW_DIAGRAM.md` | Visual data flow (Mermaid diagrams) |

---

## System at a Glance

```
13 API-based data sources (26 DDB partitions total)
    ↓
13 ingestion Lambdas (EventBridge cron + webhook + S3 trigger)
    ↓
DynamoDB (single table) + S3 (raw backup)
    ↓
MCP Lambda (115 tools) ← Claude queries this
    ↓
46 compute/email/operational Lambdas
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

No credentials in code or environment variables. All secrets live under prefix `life-platform/` in Secrets Manager. 11 active secrets as of v4.4.0.

---

## The Data Sources (26)

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

Architecture reviews happen periodically. Run `python3 deploy/generate_review_bundle.py` first — it creates the bundle Claude needs to conduct the review. Reviews are stored in `docs/reviews/`. The platform is at review R18 (grade B+). CI/CD pipeline active (v3.9.4).

---

## Glossary

| Term | Meaning |
|------|---------|
| **MCP** | Model Context Protocol — Claude's native tool interface. The MCP Lambda exposes 115 tools that Claude calls to query health data. |
| **IC** | Intelligence Capability — the platform's computed health features (IC-1 through IC-30). Each IC is a specific analysis (e.g., IC-8 = intent vs execution, IC-18 = hypothesis engine). |
| **DLQ** | Dead Letter Queue — failed async Lambda invocations land here. Consumed every 6 hours by `dlq-consumer` Lambda. |
| **SOT** | Source of Truth — which device/service owns each health domain (e.g., Whoop owns sleep, MacroFactor owns nutrition). See `mcp/config.py`. |
| **PITR** | Point-in-Time Recovery — DynamoDB's 35-day rolling backup. Enables table restore to any second within the window. |
| **CDK** | AWS Cloud Development Kit — Python-based infrastructure as code. 8 stacks in `cdk/stacks/` define all Lambda, IAM, EventBridge, and CloudWatch resources. |
| **P40** | Protocol 40 — the 65-habit personal framework tracked via Habitify. Habits are grouped into 9 P40 groups with tier weighting (T0/T1/T2). |
| **Character Sheet** | Gamified scoring system aggregating 7 health pillars (Sleep, Movement, Nutrition, Metabolic, Mind, Relationships, Consistency) into a level 1-100 with RPG-style tiers (Foundation → Elite). Computed daily. |
| **Board of Directors** | 14 fictional AI advisor personas (not real people) that provide domain-specific coaching in emails and the website. Configured in `s3://matthew-life-platform/config/board_of_directors.json`. See ADR-040. |
| **Day Grade** | Daily score (0-100, A-F letter grade) computed from sleep, nutrition, exercise, habits, hydration, and glucose. Drives the Character Sheet and daily brief email. |

---

## Key Architecture Assumptions

Things that are true but not obvious from reading the code:

1. **Single-user platform.** All DynamoDB keys are `USER#matthew#SOURCE#...`. IAM roles, secrets, schedules — everything assumes one user. Do not try to generalize without reading ADR-001.
2. **Site-api is primarily read-only.** The public API Lambda (`life-platform-site-api`) is read-only for all data queries, with limited writes for interactive features (votes, follows, checkins). See ADR-037.
3. **`public_stats.json` is the website heartbeat.** The homepage, story, mission, and observatory pages all read from this single S3 file, written by the daily brief Lambda at 11 AM PT. If the daily brief fails, the entire website shows stale data.
4. **All EventBridge crons are fixed UTC.** Schedules don't drift with DST. The PT times in documentation are for human reference only.
5. **Pipeline ordering is strict.** Ingestion (6:45-9 AM) must complete before Compute (10:20-10:35), which must complete before Daily Brief (11 AM). Changing schedules without maintaining this order produces stale computed results.
6. **Budget is $15/month target, $20 AWS Budget cap.** Current actual spend is ~$13/month.
