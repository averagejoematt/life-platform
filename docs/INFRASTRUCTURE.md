# Life Platform — Infrastructure Reference

> Quick-reference for all URLs, IDs, and configuration. No secrets stored here.
> Last updated: 2026-03-11 (v3.6.0 — 42 Lambdas, 9 secrets, 150 MCP tools, ~42 alarms)

---

## AWS Account

| Field | Value |
|-------|-------|
| Account ID | `205930651321` |
| Region | `us-west-2` (Oregon) |
| Budget | $20/month (alerts at 25% / 50% / 100%) |
| CloudTrail | `life-platform-trail` → S3 |

---

## Domain & DNS

| Field | Value |
|-------|-------|
| Domain | `averagejoematt.com` |
| Registrar | *(check where you bought the domain — Namecheap, Google Domains, etc.)* |
| Hosted Zone ID | `Z063312432BPXQH9PVXAI` |
| Nameservers | `ns-214.awsdns-26.com` · `ns-1161.awsdns-17.org` · `ns-858.awsdns-43.net` · `ns-1678.awsdns-17.co.uk` |

### DNS Records

| Subdomain | Type | Target |
|-----------|------|--------|
| `dash.averagejoematt.com` | A (alias) | `d14jnhrgfrte42.cloudfront.net` |
| `blog.averagejoematt.com` | A (alias) | `d1aufb59hb2r1q.cloudfront.net` |
| `buddy.averagejoematt.com` | A (alias) | `d1empeau04e0eg.cloudfront.net` |

---

## Web Properties

| Property | URL | Auth | CloudFront ID |
|----------|-----|------|---------------|
| Dashboard | `https://dash.averagejoematt.com/` | Lambda@Edge password (`life-platform-cf-auth`) | `EM5NPX6NJN095` |
| Blog | `https://blog.averagejoematt.com/` | None (public) | `E1JOC1V6E6DDYI` |
| Buddy Page | `https://buddy.averagejoematt.com/` | Lambda@Edge password (`life-platform-buddy-auth`) | `ETTJ44FT0Z4GO` |

Dashboard and Buddy passwords are stored in **Secrets Manager** (not here).

---

## MCP Server

| Field | Value |
|-------|-------|
| Lambda | `life-platform-mcp` (1024 MB) |
| Function URL (remote) | `https://c5hljblvma4u2xd6wf6oe4clk40unthu.lambda-url.us-west-2.on.aws/` |
| Auth (remote) | HMAC Bearer token via `life-platform/mcp-api-key` secret (auto-rotates every 90 days) |
| Auth (local) | `mcp_bridge.py` → `.config.json` → Function URL |
| Tools | 150 across 31 modules |
| Cache warmer | 12 tools pre-computed nightly at 9:00 AM PT |

---

## API Gateway

| Field | Value |
|-------|-------|
| Name | `health-auto-export-api` |
| ID | `a76xwxt2wa` |
| Endpoint | `https://a76xwxt2wa.execute-api.us-west-2.amazonaws.com` |
| Purpose | Webhook ingestion for Health Auto Export (Apple Health CGM, BP, State of Mind) |

---

## S3

| Field | Value |
|-------|-------|
| Bucket | `matthew-life-platform` |
| Key prefixes | `raw/` (source data) · `dashboard/` (web dashboard) · `blog/` (Chronicle) · `buddy/` (accountability page) · `config/` (profile, board, character sheet) · `inbound-email/` (insight parser) · `avatar/` (pixel art sprites) |

---

## DynamoDB

| Field | Value |
|-------|-------|
| Table | `life-platform` |
| Key schema | PK: `USER#matthew#SOURCE#<source>` · SK: `DATE#YYYY-MM-DD` |
| Protection | Deletion protection ON · PITR enabled (35-day rolling) |
| Encryption | KMS CMK `alias/life-platform-dynamodb` (key `444438d1-a5e0-43b8-9391-3cd2d70dde4d`) · annual auto-rotation ON |
| Partitions (30) | whoop, eightsleep, garmin, strava, withings, habitify, macrofactor, apple_health, notion_journal, todoist, weather, supplements, cgm, labs, genome, dexa, day_grade, habit_scores, character_sheet, chronicle, coaching_insights, life_events, contacts, temptations, cold_heat_exposure, exercise_variety, adaptive_mode, platform_memory, insights, hypotheses |

---

## SES (Email)

| Field | Value |
|-------|-------|
| Sender / Recipient | `awsdev@mattsusername.com` |
| Inbound rule set | `life-platform-inbound` (active) |
| Inbound rule | `insight-capture` → routes `insight@aws.mattsusername.com` → S3 |

---

## SNS

| Field | Value |
|-------|-------|
| Alert topic | `life-platform-alerts` → email to `awsdev@mattsusername.com` |
| CloudWatch alarms | ~47 metric alarms (ALARM-only; base + invocation-count + DDB item size + canary + new Lambda alarms) |

---

## SQS

| Field | Value |
|-------|-------|
| Dead-letter queue | `life-platform-ingestion-dlq` |
| DLQ coverage | All ingestion Lambdas (MCP + webhook excluded — request/response pattern) |

---

## ACM Certificates (us-east-1, required by CloudFront)

| Domain | Purpose |
|--------|---------|
| `dash.averagejoematt.com` | Dashboard CloudFront |
| `blog.averagejoematt.com` | Blog CloudFront |
| `buddy.averagejoematt.com` | Buddy CloudFront |

All DNS-validated via Route 53 CNAME records.

---

## Secrets Manager (9 active secrets + 1 pending deletion)

All under prefix `life-platform/`. No values stored in this doc — access via AWS console or CLI.

| Secret | Type | Fields / Notes |
|--------|------|----------------|
| `whoop` | OAuth | Auto-refreshed by Lambda |
| `eightsleep` | OAuth | Auto-refreshed by Lambda |
| `strava` | OAuth | Auto-refreshed by Lambda |
| `withings` | OAuth | Auto-refreshed by Lambda |
| `garmin` | Session | Auto-refreshed by Lambda |
| `ai-keys` | JSON bundle | `anthropic_api_key` + `mcp_api_key` (90-day auto-rotation) |
| `todoist` | API key | Todoist API token |
| `notion` | API key | Notion integration key + database ID |
| `habitify` | API key | Habitify API token. Own dedicated secret — NOT bundled in api-keys (different Lambda consumer set). |
| ~~`api-keys`~~ | ~~Legacy bundle~~ | ~~**PENDING PERMANENT DELETION 2026-03-17** (7-day recovery window). All Lambdas migrated to per-service secrets.~~ |

---

## Lambdas (42)

### Ingestion (13)
`whoop-data-ingestion` · `eightsleep-data-ingestion` · `garmin-data-ingestion` · `strava-data-ingestion` · `withings-data-ingestion` · `habitify-data-ingestion` · `macrofactor-data-ingestion` · `notion-journal-ingestion` · `todoist-data-ingestion` · `weather-data-ingestion` · `health-auto-export-webhook` · `journal-enrichment` · `activity-enrichment`

### Email / Digest (8)
`daily-brief` · `weekly-digest` · `monthly-digest` · `nutrition-review` · `wednesday-chronicle` · `weekly-plate` · `monday-compass` · `anomaly-detector`

### Compute (5)
`character-sheet-compute` · `adaptive-mode-compute` · `daily-metrics-compute` · `daily-insight-compute` · `hypothesis-engine`

### Infrastructure (14)
`life-platform-freshness-checker` · `dropbox-poll` · `insight-email-parser` · `life-platform-key-rotator` · `dashboard-refresh` · `life-platform-data-export` · `life-platform-qa-smoke` · `life-platform-mcp` · `dlq-consumer` · `life-platform-canary` · `data-reconciliation` · `pip-audit` · `brittany-weekly-email` · `sick-day-checker`

### Lambda@Edge (us-east-1)
`life-platform-cf-auth` (dashboard) · `life-platform-buddy-auth` (buddy page)

---

## EventBridge

All rules CDK-managed as of v3.4.0 (PROD-1). IAM role: `life-platform-scheduler-role`.

| Field | Value |
|-------|-------|
| Timezone | `America/Los_Angeles` (DST-safe) |
| Schedules | 50+ total (see PROJECT_PLAN.md Ingestion Schedule for timing) |
| Old manual rules | Deleted in v3.4.0 migration |

---

## KMS

| Field | Value |
|-------|-------|
| Key alias | `alias/life-platform-dynamodb` |
| Key ID | `444438d1-a5e0-43b8-9391-3cd2d70dde4d` |
| Key ARN | `arn:aws:kms:us-west-2:205930651321:key/444438d1-a5e0-43b8-9391-3cd2d70dde4d` |
| Purpose | DynamoDB table `life-platform` SSE (server-side encryption) |
| Rotation | Annual auto-rotation ON |
| Key policy | Root admin + all Lambda execution roles + DynamoDB service principal |
| CloudTrail | Every Decrypt/GenerateDataKey call logged |

See `deploy/p1_kms_dynamodb.sh` for creation script.

---

## Key Config Files (S3)

| Key | Purpose |
|-----|---------|
| `config/profile.json` | Personal targets (wake time, macros, weight phases, eating window) |
| `config/board_of_directors.json` | 13 expert personas for AI-generated content (incl. Conti + Murthy) |
| `config/character_sheet.json` | 7 pillar weights, tier definitions, leveling thresholds |
| `config/project_pillar_map.json` | Todoist project → platform pillar mapping (Monday Compass) |

---

## Local Project Structure

```
~/Documents/Claude/life-platform/
├── mcp_server.py          # MCP Lambda source
├── mcp_bridge.py          # Local Claude Desktop bridge
├── mcp/                   # 30 tool modules
├── lambdas/               # Lambda source + zips
├── deploy/                # Deploy scripts (run in terminal, never via MCP)
├── config/                # Local copies of S3 configs
├── content/               # Manually-written Chronicle installments
├── docs/                  # All documentation (.md)
├── handovers/             # Session handover notes
├── backfill/ seeds/ patches/ setup/ tests/ datadrops/
└── .config.json           # Local MCP bridge credentials (gitignored)
```
