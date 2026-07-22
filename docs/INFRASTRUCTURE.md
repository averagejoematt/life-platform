# Life Platform — Infrastructure Reference

> **Status:** canonical · **Owner:** Matthew · **Verified:** 2026-05-19

> Quick-reference for all URLs, IDs, and configuration. No secrets stored here.
> Last updated: 2026-07-22 (v8.6.0 — 96 Lambdas, 21 active secrets, 68 MCP tools, ~78 alarms)

---

## AWS Account

| Field | Value |
|-------|-------|
| Account ID | `205930651321` |
| Region | `us-west-2` (Oregon); us-east-1 for Lambda@Edge + OG image + email-subscriber |
| Budget | $85/month all-in, **enforced** (ADR-063 + ADR-133 amendment — was $75, floats to $100 on reader-traffic surge; alerts at 50/70/85/100%; cost-governor degrades AI by tier) |
| CloudTrail | `life-platform-trail` → S3 (data events enabled on `raw/` and `uploads/` S3 prefixes) |
| Account Lambda concurrency quota | **10** (default; raise request filed 2026-05-19, AWS Support case 177921309700709) |

---

## Domain & DNS

| Field | Value |
|-------|-------|
| Domain | `averagejoematt.com` |
| Registrar | NameCheap, Inc. — whois-verified 2026-07-10 (not Route53; DNS is still served by Route53's hosted zone below). Full detail: `docs/ACCOUNTS.md` |
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
| Public Site | `https://averagejoematt.com/` | None (public) | `E3S424OXQZ8NBE` |
| Dashboard | `https://dash.averagejoematt.com/` | Lambda@Edge password (`life-platform-cf-auth`) | `EM5NPX6NJN095` |
| Blog | `https://blog.averagejoematt.com/` | None (public) | `E1JOC1V6E6DDYI` |
| Buddy Page | `https://buddy.averagejoematt.com/` | None (public — Tom's accountability page, no PII) | `ETTJ44FT0Z4GO` |

Dashboard and Buddy passwords are stored in **Secrets Manager** (not here).

---

## MCP Server

| Field | Value |
|-------|-------|
| Lambda | `life-platform-mcp` (768 MB, python3.12) |
| Function URL (remote) | `<not committed — SEC-02 #780; read live: aws lambda get-function-url-config --function-name life-platform-mcp --region us-west-2>` |
| Auth (remote) | OAuth 2.1 auto-approve + HMAC Bearer via `life-platform/mcp-api-key` secret (auto-rotates every 90 days) |
| Auth (local) | `mcp_bridge.py` → `.config.json` → Function URL |
| Tools | **68** across **24** tool modules (`mcp/tools_*.py`) |
| Cache warmer | 14 warm-steps pre-computed nightly (warmer config) |

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
| Default encryption | **AES256** (KMS CMK `5c50ca02-c187-4338-8704-5b27f1efafca` scheduled for deletion 2026-06-16 — bucket reverted to AES256 for CloudFront website-endpoint compatibility, ADR-053/054) |
| Key prefixes | `raw/` (source data) · `site/` (public website — ~72 pages) · `generated/` (Lambda-generated files — public_stats.json, character_stats.json, OG images, journal posts; ADR-046) · `dashboard/` (web dashboard) · `blog/` (Chronicle) · `buddy/` (accountability page) · `config/` (profile, board, character sheet, coaches) · `inbound-email/` (insight parser) · `uploads/` (MacroFactor CSVs) · `imports/` (Apple Health XML) · `avatar/` (pixel art sprites) |

---

## DynamoDB

| Field | Value |
|-------|-------|
| Table | `life-platform` |
| Key schema | PK: `USER#matthew#SOURCE#<source>` · SK: `DATE#YYYY-MM-DD` |
| Protection | Deletion protection ON · PITR enabled (35-day rolling) |
| Encryption | KMS CMK `alias/life-platform-dynamodb` (key `444438d1-a5e0-43b8-9391-3cd2d70dde4d`) · annual auto-rotation ON |
| Partitions (raw + derived) | whoop, eightsleep, garmin, strava, withings, habitify, macrofactor, macrofactor_workouts, apple_health, notion, todoist, weather, supplements, labs, genome, dexa, state_of_mind, food_delivery, measurements, travel · derived: day_grade, habit_scores, character_sheet, adaptive_mode, computed_metrics, platform_memory, insights, hypotheses, decisions, chronicle, coaching_insights, COACH#, ENSEMBLE#, NARRATIVE# |

---

## SES (Email)

| Field | Value |
|-------|-------|
| Sender / Recipient | `awsdev@mattsusername.com` |
| Inbound rule set | `life-platform-inbound` (active) |
| Inbound rule | `insight-capture` → routes `insight@aws.mattsusername.com` → S3 |
| Outbound configuration set | `life-platform-emails` — wired to `daily-brief`, `weekly-digest`, `monthly-digest`, `partner-weekly-email` |

---

## SNS

| Field | Value |
|-------|-------|
| Alert topic | `life-platform-alerts` → email to `awsdev@mattsusername.com` |
| CloudWatch alarms | **~78 metric alarms** (base + invocation-count + DDB item size + canary + duration + freshness + pipeline health) |

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

## Secrets Manager (21 active secrets)

All under prefix `life-platform/`. No values stored in this doc — access via AWS console or CLI.

| Secret | Type | Fields / Notes |
|--------|------|----------------|
| `whoop` | OAuth | Auto-refreshed by Lambda |
| `eightsleep` | OAuth | Auto-refreshed by Lambda |
| `eightsleep-client` | Client credential | Companion to `eightsleep`; required by Eight Sleep API |
| `strava` | OAuth | Auto-refreshed by Lambda |
| `withings` | OAuth | Auto-refreshed by Lambda |
| `garmin` | Session | garth OAuth tokens — auto-refreshed by Lambda |
| `ai-keys` | JSON bundle | `anthropic_api_key` + `mcp_api_key` (90-day auto-rotation) |
| `ingestion-keys` | JSON bundle | `notion_api_key` + `todoist_api_key` + `habitify_api_key` + `dropbox_app_key` + `health_auto_export_api_key`. COST-B pattern — single secret, per-service key fields. Now the **sole** source for Notion + Dropbox creds after the dedicated secrets were soft-deleted 2026-05-17. |
| `habitify` | API key | Dedicated Habitify API token. Also present in `ingestion-keys` — see ADR-014 for governing principle. |
| `todoist` | API key | Todoist API token used by MCP write tools (TD-23). |
| `mcp-api-key` | Rotation target | MCP server bearer token consumed by `ai-keys`. 90-day auto-rotation via `life-platform-key-rotator`. |
| `site-api-ai-key` | API key | Subscriber validation key for site-api-ai Lambda (ADR-041). |

**Soft-deleted (30-day recovery window):**
- `life-platform/notion` — deleted 2026-05-17 (consumer migrated to `ingestion-keys`)
- `life-platform/dropbox` — deleted 2026-05-17 (consumer migrated to `ingestion-keys`)
- `life-platform/anthropic-api-key` — deleted 2026-05-16 (orphan, no consumer)

**Hard-deleted (historical):** `api-keys` (2026-03-14), `webhook-key` (2026-03-14), `google-calendar` (2026-03-15, ADR-030).

---

## Lambdas (73 us-west-2 + 4 us-east-1 = 77 total)

CDK-managed in us-west-2 (73) plus 4 standalone in us-east-1 (Lambda@Edge + OG + email-subscriber).
Source of truth: `aws lambda list-functions --region us-west-2 --query 'length(Functions)'`.

### Ingestion (14)
`whoop-data-ingestion` · `eightsleep-data-ingestion` · `garmin-data-ingestion` · `strava-data-ingestion` · `withings-data-ingestion` · `habitify-data-ingestion` · `macrofactor-data-ingestion` · `notion-journal-ingestion` · `todoist-data-ingestion` · `weather-data-ingestion` · `health-auto-export-webhook` · `apple-health-ingestion` · `dropbox-poll` · `food-delivery-ingestion` · `measurements-ingestion`

> SIMP-2 cohort (8, ADR-056): whoop, garmin, strava, withings, eightsleep, habitify, todoist, weather. Pattern-exempt (6): notion, macrofactor, apple_health, dropbox_poll, food_delivery, measurements (HAE-fed).

### Enrichment / Compute (15)
`journal-enrichment` · `activity-enrichment` · `character-sheet-compute` · `adaptive-mode-compute` · `daily-metrics-compute` · `daily-insight-compute` · `hypothesis-engine` · `weekly-correlation-compute` · `acwr-compute` · `sleep-reconciler` · `circadian-compliance` · `failure-pattern-compute` · `journal-analyzer` · `field-notes-generate` · `weekly-signal`

### Coach Intelligence (8)
`coach-computation-engine` · `coach-narrative-orchestrator` · `coach-quality-gate` (BLOCKING N-06 #390) · `coach-state-updater` · `coach-ensemble-digest` · `coach-prediction-evaluator` · `coach-history-summarizer` · `coach-observatory-renderer` · plus legacy `ai-expert-analyzer` (deprecated, fallback only)

### Email / Digest (11)
`daily-brief` · `weekly-digest` · `monthly-digest` · `nutrition-review` · `wednesday-chronicle` (EventBridge ENABLED) · `chronicle-email-sender` (EventBridge ENABLED) · `weekly-plate` · `monday-compass` · `anomaly-detector` · `evening-nudge` · `partner-weekly-email`

### Infrastructure / Operational (~17)
`life-platform-mcp` · `life-platform-mcp-warmer` · `life-platform-site-api` · `life-platform-site-api-ai` · `site-stats-refresh` · `life-platform-freshness-checker` · `life-platform-key-rotator` · `dashboard-refresh` · `life-platform-data-export` · `life-platform-data-reconciliation` · `life-platform-delete-user-data` · `life-platform-dlq-consumer` · `life-platform-canary` · `life-platform-pip-audit` · `life-platform-qa-smoke` · `life-platform-alert-digest` · `insight-email-parser` · `challenge-generator` · `pipeline-health-check` · `chronicle-approve` · `subscriber-onboarding`

### us-east-1 functions (4)
- `life-platform-cf-auth` (Lambda@Edge) — attached to dashboard CloudFront (`EM5NPX6NJN095`), password-gates `dash.averagejoematt.com`
- `life-platform-buddy-auth` (Lambda@Edge) — function exists; buddy CloudFront currently runs **without auth** (intentionally public; see Web Properties table)
- `life-platform-og-image` — OG image generation (Pillow layer)
- `email-subscriber` — Subscribe form intake

### Shared-code distribution — the retired layer (#781/ADR-131)
Canonical in `docs/CONVENTIONS.md` §1. Old layer versions remain published in AWS (`RemovalPolicy.RETAIN`) but nothing references them. Dependency layers with real third-party packages remain (they are NOT the shared layer): Pillow (og-image-generator), garth (Garmin ingestion).

---

## EventBridge

All rules CDK-managed as of v3.4.0 (PROD-1). IAM role: `life-platform-scheduler-role`.

| Field | Value |
|-------|-------|
| Total rules | 65 (`aws events list-rules --region us-west-2`) |
| Timezone | Fixed UTC cron (no DST drift; see CLAUDE.md convention) |
| Chronicle pipeline | `wednesday-chronicle-schedule` ENABLED (`cron(0 15 ? * WED *)` — Wed 8 AM PT). Chronicle email sender ENABLED (`cron(10 15 ? * WED *)`). Re-enabled as part of V2 follow-up. |
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
├── mcp/                   # 26 tool modules + helpers
├── lambdas/               # Lambda source + zips
├── deploy/                # Deploy scripts (run in terminal, never via MCP)
├── config/                # Local copies of S3 configs
├── content/               # Manually-written Chronicle installments
├── docs/                  # All documentation (.md)
├── handovers/             # Session handover notes
├── backfill/ seeds/ patches/ setup/ tests/ datadrops/
└── .config.json           # Local MCP bridge credentials (gitignored)
```

---

**Verified:** 2026-05-19 — full audit (V2 audit + follow-up). Lambda inventory via `aws lambda list-functions` (both regions), secrets via `aws secretsmanager list-secrets --include-planned-deletion`, alarms via `aws cloudwatch describe-alarms`, EventBridge via `aws events list-rules`, S3 encryption via `aws s3api get-bucket-encryption`, CloudTrail data events via `aws cloudtrail get-event-selectors`, SES config sets via `aws sesv2 list-configuration-sets`. (The shared layer was retired #781 — there is no "layer version" to verify for it anymore. `cdk/stacks/constants.py:37` is `GARTH_LAYER_VERSION`, the *dependency* layer for Garmin ingestion, not the retired shared layer.)
