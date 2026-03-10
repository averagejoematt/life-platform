# Life Platform — Pre-Compiled Review Bundle
**Generated:** 2026-03-10
**Purpose:** Single-file input for architecture reviews. Contains all platform state needed for a Technical Board assessment.
**Usage:** Start a new session and say: "Read this review bundle file, then conduct Architecture Review #N using the Technical Board of Directors."

---

## 1. PLATFORM STATE SNAPSHOT

### Latest Handover

<!-- This file is auto-updated each session. For history see handovers/ -->
<!-- Last updated: 2026-03-10 v3.4.9 -->

See: [handovers/2026-03-10_cloudfront_tls_v3.4.9.md](../handovers/2026-03-10_cloudfront_tls_v3.4.9.md)


---

## 2. RECENT CHANGELOG

# Life Platform — Changelog

## v3.4.9 — 2026-03-10: CloudFront TLS Fix

### Bug Fix
- `cdk/stacks/web_stack.py`: Wired ACM certificate ARNs to all three CloudFront distributions
- Root cause: `CERT_ARN_*` constants were `None` — CDK was deploying distributions without `viewer_certificate`, causing browsers to receive the default `*.cloudfront.net` cert
- Fix: Added `ViewerCertificateProperty` with `ssl_support_method=sni-only`, `minimum_protocol_version=TLSv1.2_2021` to all three distributions
- Certs (all `ISSUED`, us-east-1):
  - `dash.averagejoematt.com` → `8e560416-e5f6-4f87-82a6-17b5e7df25d0`
  - `blog.averagejoematt.com` → `952ddf18-d073-4d04-a0b7-42c7f5150dc2`
  - `buddy.averagejoematt.com` → `cfaf8364-1353-48d3-8522-6892a5aef680`
- Deploy: `npx cdk deploy LifePlatformWeb --require-approval never`

---

## v3.4.8 — 2026-03-10: COST-A + COST-B Completion

### COST-B + Habitify Secret (combined)
- `deploy/setup_ingestion_keys.sh`: merges todoist/notion/dropbox/habitify keys into `life-platform/ingestion-keys`
- Supersedes CHANGELOG v3.4.4 warning — `life-platform/habitify` is NOT created separately; `habitify_api_key` goes into `ingestion-keys` (per role_policies.py COST-B update)
- CDK env vars already deployed (v3.4.7): todoist→`SECRET_NAME`, notion→`NOTION_SECRET_NAME`, dropbox→`SECRET_NAME`, habitify→`HABITIFY_SECRET_NAME` all = `life-platform/ingestion-keys`
- Schedules deletion of `life-platform/todoist`, `life-platform/notion`, `life-platform/dropbox` (~2026-04-10, saves $1.20/mo)
- `life-platform/api-keys` still pending permanent deletion ~2026-04-07

### COST-A Completion
- `deploy/finish_cost_a.sh`: orchestrates orphan deletion + CDK Monitoring + CDK Operational deploys
- Remaining stacks to deploy: `LifePlatformMonitoring`, `LifePlatformOperational` (Email already deployed v3.4.6)
- `delete_orphan_alarms.sh` already populated (48 orphans identified in v3.4.5)
- Expected result: ~87 → ~41 alarms, saves ~$4.60/mo

### Scripts (run in order)
1. `bash deploy/setup_ingestion_keys.sh` — merge keys + delete old secrets
2. `bash deploy/finish_cost_a.sh` — orphan deletion + CDK deploy

---

## v3.4.7 — 2026-03-10: IAM Health Check — S3 Paths + KMS + Strava OAuth

### Bug Fixes (found during platform health check)
- `role_policies.py` — `_ingestion_base()`: S3 write prefix corrected from `raw/{source}/*` → `raw/matthew/{source}/*` (all ingestion Lambdas write under user-prefixed paths — was silently failing on gap-fill attempts)
- `role_policies.py` — `ingestion_hae()`: S3 write corrected to `raw/matthew/*` (HAE writes to multiple sub-paths: cgm_readings, blood_pressure, state_of_mind, workouts)
- `role_policies.py` — `ingestion_apple_health()`: S3 write corrected to `raw/matthew/apple_health/*`
- `role_policies.py` — `ingestion_strava()`: Added `secretsmanager:PutSecretValue` (OAuth token refresh writes back to secret on every API call)
- `role_policies.py` — `ingestion_dropbox()`: S3 path corrected to `uploads/macrofactor/*` (actual write target, not `imports/*`)
- `role_policies.py` — `ingestion_notion()` + `ingestion_habitify()`: S3 prefixes corrected to `raw/matthew/notion/*` and `raw/matthew/habitify/*`

### Deployed
- `LifePlatformIngestion` CDK stack

### Smoke Tests (post-deploy)
- `whoop-data-ingestion` ✅ 200
- `strava-data-ingestion` ✅ 200
- `journal-enrichment` ✅ 200

---

## v3.4.6 — 2026-03-10: EMAIL_RECIPIENT + KMS Bug Fixes

### Bug Fixes
- `lambda_helpers.py`: Added `EMAIL_RECIPIENT` + `EMAIL_SENDER` to base env vars for all Lambdas (was previously console-only orphan config — wiped by COST-A CDK deploy)
- `cdk/cdk.json`: Added `email_recipient` + `email_sender` context keys (`lifeplatform@mattsusername.com`)
- `role_policies.py` — `_email_base()`: Added missing `kms:Decrypt` + `kms:GenerateDataKey` for all 8 email Lambdas (CMK-encrypted DDB table requires KMS on every reader)
- `role_policies.py` — Also added KMS to 5 inline policy functions that were missing it: `ingestion_journal_enrichment`, `ingestion_activity_enrichment`, `ingestion_apple_health`, `ingestion_hae`, `ingestion_weather`
- `daily_brief_lambda.py`: Removed redundant `from datetime import timezone` inside `lambda_handler` (shadowed module-level import, causing `UnboundLocalError` at line 1171)

### Deployed
- `LifePlatformEmail` CDK stack (2x — first deploy fixed EMAIL vars, second fixed KMS)
- `daily-brief` Lambda (timezone fix)

### Result
- Daily brief confirmed sending: `statusCode 200`, "Daily brief v2.77.0 sent"
- Today's 9 AM brief was missed; next scheduled run tomorrow will succeed

---

## v3.4.5 — 2026-03-10: COST-A CloudWatch Alarm Consolidation

### CloudWatch Alarms
- Identified 87 alarms vs ~55 CDK-managed — ~32 pre-CDK orphans + 14 CDK duplicates
- `monitoring_stack.py`: Removed `life-platform-daily-brief-invocations` (dup of `daily-brief-no-invocations-24h`)
- `monitoring_stack.py`: Consolidated AI token alarms from 13 → 2 (keep `ai-tokens-daily-brief-daily` + `ai-tokens-platform-daily-total`)
- `email_stack.py`: daily-brief passes `alerts_topic=None` (removes `ingestion-error-daily-brief` dup)
- `operational_stack.py`: Removed `life-platform-canary-any-failure` (bug: watched same metric as `canary-ddb-failure`)
- Scripts: `deploy/audit_alarms.sh` + `deploy/delete_orphan_alarms.sh`
- **Savings: ~$4.60/mo** ($7.70 → ~$3.10 CloudWatch); 87 → ~41 alarms
- ⚠️ CDK changes NOT YET DEPLOYED — run: `cdk deploy LifePlatformMonitoring LifePlatformEmail LifePlatformOperational`
- ⚠️ Orphan deletion pending — run `audit_alarms.sh`, populate PRECDK_ORPHANS in delete script, then run delete

### Docs
- COST_TRACKER.md: corrected CloudWatch cost row, monthly actuals, decision log
- HANDOVER_LATEST.md: updated

---

## v3.4.4 — 2026-03-10: Hygiene Sweep (Architecture Review #4 follow-up)

### INCIDENT_LOG
- Added 5 missing incidents from v3.4.0/v3.4.1 (retroactive, flagged for Matthew review)
- P1: CDK IAM role gap during bulk migration
- P2: CoreStack DLQ ARN change
- P3: EB rule recreation gap (2 Lambdas)
- P3: Orphan Lambda adoption — failure-pattern-compute EB rule missing
- P4: Duplicate CloudWatch alarms after CDK adoption

### DECISIONS.md
- ADR-021: EventBridge rule naming convention (CDK)
- ADR-022: CoreStack scoping — shared infra vs. per-stack resources
- ADR-023: Sick day checker as shared utility module (not standalone Lambda)

### role_policies.py (cdk/stacks)
- `needs_kms=True` added to 6 compute functions: anomaly_detector, daily_insight, adaptive_mode, hypothesis_engine, dashboard_refresh, failure_pattern
- `ingestion_habitify()` secret ref updated: `life-platform/api-keys` → `life-platform/habitify` (⚠️ secret needs creating before 2026-04-07)

### failure_pattern_compute_lambda.py
- `store_failure_patterns()` now sets `ttl` = `now + 90 days` on all platform_memory records
- ⚠️ Deploy needed: `bash deploy/deploy_lambda.sh failure-pattern-compute`

### ARCHITECTURE.md
- Header updated to v3.4.2, 147 tools, 41 Lambdas, 8 CDK stacks
- CDK resource table updated to list all 8 stacks (Core added)

### deploy/ housekeeping
- 19 one-time scripts archived to `deploy/archive/20260310/`
- `deploy/cleanup_dead_files.sh` written — run once to delete `weather_lambda.py.archived` and `freshness_checker.py`
- Session-end checklist updated: archive deploy/ scripts is now step (1)

### PlatformLogger %s (item 7)
- Already fixed in v1.0.1 — no action needed

---

## v3.4.3 — 2026-03-10: CDK IaC Bugfix Sprint

### PlatformLogger `*args` fix
- `platform_logger.py`: all log methods now accept `*args, **kwargs` + `%s` interpolation
- Fixes `takes 2 positional arguments but 3 were given` across daily-metrics-compute, character-sheet-compute, anomaly-detector, and others
- SharedUtilsLayer:7 deployed to all stacks

### `role_policies.py` — 22 missing methods added
- 5 compute methods: `compute_daily_insight`, `compute_adaptive_mode`, `compute_hypothesis_engine`, `compute_dashboard_refresh`, `compute_failure_pattern`
- 9 email methods: `_email_base()` helper + `email_daily_brief`, `email_weekly_digest`, `email_monthly_digest`, `email_nutrition_review`, `email_wednesday_chronicle`, `email_weekly_plate`, `email_monday_compass`, `email_brittany`
- 8 operational methods: `operational_freshness_checker`, `operational_dlq_consumer`, `operational_canary`, `operational_pip_audit`, `operational_qa_smoke`, `operational_key_rotator`, `operational_data_export`, `operational_data_reconciliation`, `operational_insight_email_parser`
- 1 MCP method: `mcp_server`
- KMS policy (`kms:Decrypt` + `kms:GenerateDataKey`) added unconditionally to `_ingestion_base()` — table uses CMK, all ingestion Lambdas need it

### `ingestion_stack.py` — 7 handler strings corrected
- whoop, withings, habitify, strava, todoist, eightsleep, apple-health had `lambda_function.lambda_handler` placeholder
- Corrected to match actual filenames (e.g. `whoop_lambda.lambda_handler`)
- Was masked pre-CDK because `deploy_lambda.sh` reads handler from AWS directly

... [TRUNCATED — 3915 lines omitted, 4065 total]


---

## 3. ARCHITECTURE

# Life Platform — Architecture

Last updated: 2026-03-10 (v3.4.7 — 147 tools, 31-module MCP package, 19 data sources, 41 Lambdas, 8 secrets, 42 alarms, 8 CDK stacks deployed)

---

## Overview

The life platform is a personal health intelligence system built on AWS. It ingests data from nineteen sources (twelve scheduled + one webhook + three manual/periodic + two MCP-managed + one State of Mind via webhook), normalises everything into a single DynamoDB table, and surfaces it to Claude through a Lambda-backed MCP server. The design philosophy is: get data in automatically, store it cheaply, and make it queryable without a data engineering background.

---

## Three-Layer Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  INGEST LAYER                                               │
│  Scheduled Lambdas (EventBridge) + S3 Triggers + Webhooks   │
│  Whoop · Withings · Strava · Todoist · Eight Sleep          │
│  MacroFactor (Dropbox → S3 CSV + scheduled) · Garmin        │
│  Apple Health (S3 XML + webhook) · Habitify · Notion Journal│
│  Health Auto Export (webhook — CGM/Dexcom Stelo, BP, SoM)  │
│  Weather (Open-Meteo, scheduled) · Supplements (MCP write)  │
│  Labs (manual seed) · DEXA (manual seed) · Genome (seed)   │
└────────────────────────┬────────────────────────────────────┘
                         │ normalised records
┌────────────────────────▼────────────────────────────────────┐
│  STORE LAYER                                                │
│  S3 (raw) + DynamoDB (normalised, single-table)             │
└────────────────────────┬────────────────────────────────────┘
                         │ DynamoDB queries
┌────────────────────────▼────────────────────────────────────┐
│  SERVE LAYER                                                │
│  MCP Server Lambda (144 tools, 1024 MB) + Lambda Function URL│
│  ← Claude Desktop + claude.ai + Claude mobile via remote MCP│
│                                                             │
│  COMPUTE LAYER (IC intelligence features)                   │
│  character-sheet-compute · adaptive-mode-compute            │
│  daily-metrics-compute · daily-insight-compute (IC-8)       │
│  hypothesis-engine (IC-18, Sunday 11 AM PT)                 │
│  compute → store → read pattern: runs before Daily Brief    │
│                                                             │
│  EMAIL LAYER                                                │
│  monday-compass (Mon 7am) · daily-brief (10am)              │
│  wednesday-chronicle (Wed 7am) · weekly-plate (Fri 6pm)     │
│  weekly-digest (Sun 8am) · monthly-digest (1st Mon 8am)     │
│  nutrition-review (Sat 9am) · anomaly-detector (8:05am)     │
│  freshness-checker (9:45am) · insight-email-parser (S3 trig)│
│                                                             │
│  WEB LAYER                                                  │
│  CloudFront → S3 static website (OriginPath /dashboard)     │
│  index.html (daily) + clinical.html + data/clinical.json    │
│  Daily Brief writes data.json · Weekly Digest writes        │
│  clinical.json · Custom domain: dash.averagejoematt.com     │
└─────────────────────────────────────────────────────────────┘
```

---

## AWS Resources

**Account:** 205930651321
**Primary region:** us-west-2

| Resource | Type | Name / ARN |
|---|---|---|
| DynamoDB table | NoSQL database | `life-platform` (deletion protection + PITR enabled) |
| S3 bucket | Object storage + static website | `matthew-life-platform` (static hosting on `dashboard/*`) |
| SQS queue | Dead-letter queue | `life-platform-ingestion-dlq` |
| Lambda Function URL (MCP) | MCP HTTPS endpoint | `https://votqefkra435xwrccmapxxbj6y0jawgn.lambda-url.us-west-2.on.aws/` (AuthType NONE — auth handled in Lambda via API key header) |
| Lambda Function URL (remote MCP) | Remote MCP HTTPS endpoint | `https://c5hljblvma4u2xd6wf6oe4clk40unthu.lambda-url.us-west-2.on.aws` (OAuth 2.1 auto-approve + HMAC Bearer) |
| API Gateway | HTTP endpoint | `health-auto-export-api` (a76xwxt2wa) — webhook ingest |
| Secrets Manager | Credential store | 8 secrets: 4 OAuth (`whoop`, `withings`, `strava`, `garmin`) + `eightsleep` + `life-platform/ai-keys` (Anthropic) + `life-platform/todoist` + `life-platform/notion` + `life-platform/dropbox` — **`life-platform/api-keys` pending deletion** |
| SNS topic | Alert routing | `life-platform-alerts` |
| CloudFront (dash) | CDN + auth | `EM5NPX6NJN095` (`d14jnhrgfrte42.cloudfront.net`) → S3 `/dashboard`, Lambda@Edge auth (`life-platform-cf-auth`), alias `dash.averagejoematt.com` |
| CloudFront (blog) | CDN (public) | `E1JOC1V6E6DDYI` (`d1aufb59hb2r1q.cloudfront.net`) → S3 `/blog`, NO auth, alias `blog.averagejoematt.com` |
| CloudFront (buddy) | CDN + auth | `ETTJ44FT0Z4GO` (`d1empeau04e0eg.cloudfront.net`) → S3 `/buddy`, Lambda@Edge auth (`life-platform-buddy-auth`), alias `buddy.averagejoematt.com`, PriceClass_100, HTTP/2+3 |
| ACM Certificate | TLS | `arn:aws:acm:us-east-1:205930651321:certificate/8e560416-...` — `dash.averagejoematt.com` (DNS-validated) |
| SES Receipt Rule Set | Inbound email routing | `life-platform-inbound` (active) — rule `insight-capture` routes `insight@aws.mattsusername.com` → S3 |
| CloudWatch | Alarms + logs | **~47 metric alarms**, all Lambdas monitored |
| CDK | Infrastructure as Code | `cdk/` — 8 stacks deployed: **Core** (SQS DLQ + SNS + Layer), Ingestion, Compute, Email, Operational, Mcp, Monitoring, Web. CDK owns all 41 Lambda IAM roles + ~50 EventBridge rules. `cdk/stacks/lambda_helpers.py` uses `Code.from_asset("../lambdas")`. DDB + S3 deliberately unmanaged (stateful). |}
| CloudTrail | Audit logging | `life-platform-trail` → S3 |
| AWS Budget | Cost guardrail | $20/mo cap, alerts at 25%/50%/100% |

---

## Ingest Layer

### Scheduled ingestion (EventBridge → Lambda)

Each source has its own dedicated Lambda and IAM role. EventBridge triggers fire daily. All cron expressions use fixed UTC — **PT times shift by 1 hour when DST changes**.

**Gap-aware backfill (v2.46.0):** All 6 API-based ingestion Lambdas (Garmin, Whoop, Eight Sleep, Strava, Withings, Habitify) implement self-healing gap detection. On each scheduled run, the Lambda queries DynamoDB for the last N days (default 7, configurable via `LOOKBACK_DAYS` env var), identifies missing DATE# records, and fetches only those from the upstream API. Normal runs with no gaps cost 1 DynamoDB query and 0 extra API calls. Rate-limit pacing (0.5–1s) between gap-day fetches prevents upstream throttling. The pattern is self-bootstrapping — existing records are the reference point, no last-sync marker needed. Sources not at risk (Apple Health webhook, MacroFactor Dropbox polling, Notion, Weather, Todoist) do not need gap detection.

| Source | Lambda | EventBridge Rule | Cron (UTC) | PT (PDT) | IAM Role |
|---|---|---|---|---|---|
| Whoop | `whoop-data-ingestion` | `whoop-daily-ingestion` | `cron(0 14 * * ? *)` | 07:00 AM | `lambda-whoop-role` |
| Garmin | `garmin-data-ingestion` | `garmin-daily-ingestion` | `cron(0 14 * * ? *)` | 07:00 AM | `lambda-garmin-ingestion-role` |
| Notion Journal | `notion-journal-ingestion` | `notion-daily-ingest` | `cron(0 14 * * ? *)` | 07:00 AM | `lambda-notion-ingestion-role` |
| Withings | `withings-data-ingestion` | `withings-daily-ingestion` | `cron(15 14 * * ? *)` | 07:15 AM | `lambda-withings-role` |
| Habitify | `habitify-data-ingestion` | `habitify-daily-ingest` | `cron(15 14 * * ? *)` | 07:15 AM | `lambda-habitify-ingestion-role` |
| Strava | `strava-data-ingestion` | `strava-daily-ingestion` | `cron(30 14 * * ? *)` | 07:30 AM | `lambda-strava-role` |
| Journal Enrichment | `journal-enrichment` | `journal-enrichment-daily` | `cron(30 14 * * ? *)` | 07:30 AM | `lambda-journal-enrichment-role` |
| Todoist | `todoist-data-ingestion` | `todoist-daily-ingestion` | `cron(45 14 * * ? *)` | 07:45 AM | `lambda-todoist-role` |
| Eight Sleep | `eightsleep-data-ingestion` | `eightsleep-daily-ingestion` | `cron(0 15 * * ? *)` | 08:00 AM | `lambda-eightsleep-role` |
| Activity Enrichment | `activity-enrichment` | `activity-enrichment-nightly` | `cron(30 15 * * ? *)` | 08:30 AM | `lambda-enrichment-role` |
| MacroFactor | `macrofactor-data-ingestion` | `macrofactor-daily-ingestion` | `cron(0 16 * * ? *)` | 09:00 AM | `lambda-macrofactor-role` |
| Weather | `weather-data-ingestion` | `weather-daily-ingestion` | `cron(45 13 * * ? *)` | 06:45 AM | `lambda-weather-role` |
| Dropbox Poll | `dropbox-poll` | `dropbox-poll-schedule` | `rate(30 minutes)` | every 30m | `lambda-dropbox-poll-role` |

**⚠️ DST note:** All crons use fixed UTC. Times above reflect PDT (UTC-7, from March 8 2026). Adjust ±1hr during PST (UTC-8, Nov–Mar). Run `deploy/deploy_dst_spring_2026.sh` at each DST transition.

### Operational Lambdas (EventBridge → Lambda)

These are not data ingestion — they compute, alert, or deliver intelligence.

**Compute Lambdas (run before Daily Brief — compute → store → read pattern):**

| Function | Lambda | EventBridge Rule | Cron (UTC) | PT (PDT) | IAM Role |
|---|---|---|---|---|---|
| Character Sheet Compute | `character-sheet-compute` | `character-sheet-compute` | `cron(35 17 * * ? *)` | 10:35 AM | `life-platform-compute-role` |
| Adaptive Mode Compute | `adaptive-mode-compute` | `adaptive-mode-compute-daily` | `cron(30 17 * * ? *)` | 10:30 AM | `lambda-adaptive-mode-role` |
| Daily Metrics Compute | `daily-metrics-compute` | `daily-metrics-compute-daily` | `cron(25 17 * * ? *)` | 10:25 AM | `lambda-daily-metrics-role` |
| Daily Insight Compute (IC-8) | `daily-insight-compute` | `daily-insight-compute-daily` | `cron(20 17 * * ? *)` | 10:20 AM | `lambda-daily-insight-role` |
| Hypothesis Engine (IC-18) | `hypothesis-engine` | `hypothesis-engine-weekly` | `cron(0 19 ? * SUN *)` | Sun 12:00 PM | `lambda-hypothesis-engine-role` |

**Operational & Email Lambdas:**

| Function | Lambda | EventBridge Rule | Cron (UTC) | PT (PDT) | IAM Role |
|---|---|---|---|---|---|
| Anomaly Detector v2.1 | `anomaly-detector` | `anomaly-detector-daily` | `cron(5 16 * * ? *)` | 09:05 AM | `life-platform-email-role` |
| Cache Warmer | `life-platform-mcp` | `life-platform-nightly-warmer` | `cron(0 17 * * ? *)` | 10:00 AM | `lambda-mcp-server-role` |
| Whoop Recovery Refresh | `whoop-data-ingestion` | `whoop-recovery-refresh` | `cron(30 17 * * ? *)` | 10:30 AM | `lambda-whoop-role` |
| Freshness Checker | `life-platform-freshness-checker` | `life-platform-freshness-check` | `cron(45 17 * * ? *)` | 10:45 AM | `lambda-freshness-checker-role` |
| Monday Compass | `monday-compass` | `monday-compass` | `cron(0 15 ? * MON *)` | Mon 08:00 AM | `lambda-monday-compass-role` |
| Daily Brief | `daily-brief` | `daily-brief-schedule` | `cron(0 18 * * ? *)` | 11:00 AM | `lambda-daily-brief-role` |
| Weekly Digest | `weekly-digest` | `weekly-digest-sunday` | `cron(0 16 ? * SUN *)` | Sun 09:00 AM | `lambda-weekly-digest-role-v2` |
| Monthly Digest | `monthly-digest` | `monthly-digest-schedule` | `cron(0 16 ? * 1#1 *)` | 1st Mon 9:00 AM | `lambda-monthly-digest-role` |
| Nutrition Review | `nutrition-review` | `nutrition-review-schedule` | `cron(0 17 ? * SAT *)` | Sat 10:00 AM | `lambda-nutrition-review-role` |
| Wednesday Chronicle | `wednesday-chronicle` | `wednesday-chronicle` | `cron(0 15 ? * WED *)` | Wed 08:00 AM | `lambda-wednesday-chronicle-role` |
| The Weekly Plate | `weekly-plate` | `weekly-plate-schedule` | `cron(0 2 ? * SAT *)` | Fri 07:00 PM | `lambda-weekly-plate-role` |
| Dashboard Refresh (2 PM) | `dashboard-refresh` | `dashboard-refresh-afternoon` | `cron(0 22 * * ? *)` | 03:00 PM | `lambda-mcp-server-role` |
| Dashboard Refresh (6 PM) | `dashboard-refresh` | `dashboard-refresh-evening` | `cron(0 2 * * ? *)` | 07:00 PM | `lambda-mcp-server-role` |
| MCP Key Rotator | `mcp-key-rotator` | Secrets Manager rotation | 90-day auto | — | `lambda-key-rotator-role` |
| QA Smoke | `qa-smoke` | on-demand | — | — | `lambda-qa-smoke-role` |
| Data Export | `data-export` | on-demand | — | — | `lambda-data-export-role` |

**Note:** As of v3.1.3, all Lambdas have dedicated per-function IAM roles (39 total). The original shared `lambda-weekly-digest-role` was deleted and replaced by per-function roles. Three pre-SEC-1 Lambdas (`anomaly-detector`, `character-sheet-compute`, `dashboard-refresh`) use shared roles (`life-platform-email-role`, `life-platform-compute-role`, `lambda-mcp-server-role` respectively) — SEC-1 migration deferred. Each role is least-privilege scoped to the AWS resources that function needs.

### File-triggered ingestion (S3 → Lambda)

| Source | Lambda | S3 Trigger Path | IAM Role |
|---|---|---|---|
| MacroFactor | `macrofactor-data-ingestion` | `s3://matthew-life-platform/uploads/macrofactor/*.csv` | `lambda-macrofactor-role` |
| Apple Health | `apple-health-ingestion` | `s3://matthew-life-platform/imports/apple_health/*.xml` | `lambda-apple-health-role` |

### Event-driven Lambdas (S3 trigger, no schedule)

| Function | Lambda | Trigger | IAM Role |
|---|---|---|---|
| Insight Email Parser | `insight-email-parser` | S3 `raw/inbound_email/*` ObjectCreated | `lambda-insight-email-parser-role` |

**Insight Email Parser:** SES receives email at `insight@aws.mattsusername.com` → stores in S3 `raw/inbound_email/` → Lambda extracts reply text → saves to `USER#matthew#SOURCE#insights` with auto-tagging → sends confirmation. Security: ALLOWED_SENDERS whitelist.

### Webhook ingestion (API Gateway → Lambda)

| Source | Lambda | Endpoint | Auth |
|---|---|---|---|
| Health Auto Export | `health-auto-export-webhook` | `https://a76xwxt2wa.execute-api.us-west-2.amazonaws.com/ingest` | Bearer token (`life-platform/api-keys`) |

**Three-tier source filtering (v1.1.0):**
- Tier 1 (Apple-exclusive): steps, active/basal energy, gait metrics, flights, distance, headphone audio, water intake, caffeine
- Tier 2 (cross-device): HR, RHR, HRV, respiratory rate, SpO2 — filtered to Apple Watch/iPhone sources only
- Tier 3 (skip): nutrition (MacroFactor SOT), sleep environment (Eight Sleep SOT), body comp (Withings SOT)
- **Sleep SOT (v2.55.0):** Sleep duration/staging/score/efficiency → Whoop. Eight Sleep → bed environment only.
- **Webhook v1.4.0:** Blood pressure metrics (systolic, diastolic, pulse). Individual readings in S3 `raw/blood_pressure/`.
- **Webhook v1.5.0:** State of Mind detection. Check-ins in S3 `raw/state_of_mind/`, daily aggregates in DynamoDB.

**⚠️ `apple-health-ingestion` (S3 XML trigger) is a separate legacy Lambda — NOT the webhook. Debug webhook issues in `health-auto-export-webhook` logs.**

### Failure handling

DLQ coverage: all async Lambdas → `life-platform-ingestion-dlq` (SQS). Request/response pattern Lambdas (`life-platform-mcp`, `health-auto-export-webhook`) excluded. CloudWatch metric alarms: **~47 total**, all Lambdas monitored. Alarm actions → SNS `life-platform-alerts`. 24-hour evaluation period, `TreatMissingData: notBreaching`.

**Additional failure safeguards (v3.1.3):**
- **DLQ Consumer Lambda** (`dlq-consumer`): Drains `life-platform-ingestion-dlq` on a schedule, logs failed message details to CloudWatch with structured context for triage.
- **Canary Lambda** (`life-platform-canary`): Synthetic health check — writes a test record, reads it back, deletes it. Fires every 30 min. Alarms if roundtrip fails.
- **Item size guard** (`item_size_guard.py`): Intercepts all DDB `put_item` calls in ingestion Lambdas; truncates oversized items, emits `ItemSizeWarning` CloudWatch metric before write.

### OAuth token management

Whoop, Withings, Strava, Garmin: OAuth2 with self-healing refresh tokens. Each Lambda reads secret → calls API → on expiry, refreshes → writes updated credentials back to Secrets Manager. Eight Sleep: username/password JWT, refreshed each invocation. Notion, Habitify, Todoist: static API keys (consolidated into `life-platform/api-keys`).

---

## Store Layer

### S3 — raw data

```
s3://matthew-life-platform/
  dashboard/
    index.html                        ← daily dashboard (public read, CloudFront cached)
    clinical.html                     ← clinical summary (public read)
    data.json                         ← written by Daily Brief Lambda
    clinical.json                     ← written by Weekly Digest Lambda
  config/
    board_of_directors.json           ← 13-member expert panel (read by all email Lambdas via board_loader.py)
    character_sheet.json              ← Character Sheet config: pillar weights, tiers, XP, cross-pillar effects
    project_pillar_map.json           ← Todoist project → platform pillar mapping (Monday Compass)
    profile.json                      ← user profile (targets, habits, phases)
  raw/
    whoop/2026/02/22/response.json
    cgm_readings/2026/02/25.json      ← MCP reads this for glucose tools
    health_auto_export/2026/02/25_*.json
    inbound_email/<ses-message-id>    ← SES inbound (triggers insight-email-parser)
    state_of_mind/2026/02/27.json     ← How We Feel check-ins
    blood_pressure/2026/02/25.json    ← Individual BP readings
    ...
  uploads/
    macrofactor/*.csv                 ← triggers macrofactor Lambda
  imports/
    apple_health/*.xml                ← triggers apple-health Lambda
```

### DynamoDB — normalised data

Table: `life-platform` (us-west-2) | Single-table | On-demand billing | Deletion protection | PITR (35-day) | TTL on `ttl` attribute (cache partition)

```
PK (partition key):  USER#matthew#SOURCE#<source>
SK (sort key):       DATE#YYYY-MM-DD
```

**Key partitions:**
```
USER#matthew#SOURCE#whoop              DATE#YYYY-MM-DD   → Whoop recovery
USER#matthew#SOURCE#day_grade          DATE#YYYY-MM-DD   → Day grade + components
USER#matthew#SOURCE#habit_scores       DATE#YYYY-MM-DD   → Tier-weighted habit scores
USER#matthew#SOURCE#character_sheet    DATE#YYYY-MM-DD   → Character Sheet RPG scoring
USER#matthew#SOURCE#computed_metrics   DATE#YYYY-MM-DD   → Readiness, HRV, TSB (pre-computed)
USER#matthew#SOURCE#platform_memory    MEMORY#<type>#YYYY-MM-DD → IC feature outputs (IC-8 etc.)
USER#matthew#SOURCE#insights           INSIGHT#<ISO-ts>  → Insights ledger (IC-15/16)
USER#matthew#SOURCE#hypotheses         HYPOTHESIS#<ts>   → Hypothesis engine outputs (IC-18)
USER#matthew                           PROFILE#v1        → User profile/settings
CACHE#matthew                          TOOL#<cache_key>  → MCP pre-computed cache (TTL 26h)
```

No GSI by design — all access patterns served by PK+SK queries.

**⚠️ 400KB item size limit:** Monitor Strava activities, MacroFactor food_log, Apple Health records.

---

## Serve Layer

### MCP Server

**Lambda:** `life-platform-mcp` | **Tools:** 144 | **Memory:** 1024 MB | **Modules:** 30
**Local endpoint:** `https://votqefkra435xwrccmapxxbj6y0jawgn.lambda-url.us-west-2.on.aws/`
**Remote MCP:** `https://c5hljblvma4u2xd6wf6oe4clk40unthu.lambda-url.us-west-2.on.aws` — OAuth 2.1 auto-approve + HMAC Bearer (enables claude.ai + mobile)
**Auth:** `x-api-key` header check; key in `life-platform/api-keys`
**Protocol:** JSON-RPC 2.0 / MCP spec 2025-06-18

30-module package structure:
```
mcp/
  handler.py, config.py, utils.py, core.py, helpers.py
  labs_helpers.py, strength_helpers.py, registry.py, warmer.py
  tools_sleep, tools_health, tools_training, tools_nutrition
  tools_habits, tools_cgm, tools_labs, tools_journal, tools_lifestyle
  tools_social, tools_strength, tools_correlation, tools_character
  tools_board, tools_decisions, tools_adaptive, tools_hypotheses
  tools_memory, tools_data, tools_todoist
```

Cold start: ~700–800ms. Warm: 23–30ms. Cached tools: <100ms.

**IAM role:** `lambda-mcp-server-role` — DynamoDB `GetItem`, `Query`, `PutItem` (cache writes); S3 `GetObject` on `raw/cgm_readings/*`. No `Scan`, no `DeleteItem`.

### Cache warmer

EventBridge triggers MCP Lambda at 10:00 AM PDT daily (`source: aws.events`). Pre-computes 12 tools → `CACHE#matthew` partition, 26-hour TTL. Runtime: ~7s.

Cached tools: `get_aggregated_summary` (5yr + 2yr views), `get_personal_records`, `get_seasonal_patterns`, `get_health_dashboard`, `get_habit_dashboard`, `get_readiness_score`, `get_health_risk_profile`, `get_body_composition_snapshot`, `get_energy_balance`, `get_day_type_analysis`, `get_movement_score`.

### Email / Intelligence cadence

**Daily (every day):**
| Lambda | Time (PDT) | Purpose |
|---|---|---|
| `anomaly-detector` v2.1 | 9:05 AM | Adaptive threshold anomaly detection (15 metrics, 7 sources). CV-based Z thresholds, day-of-week normalization, travel-aware suppression. |
| `daily-brief` v2.62 | 11:00 AM | 18-section brief: readiness, day grade + TL;DR, scorecard, weight phase, training, nutrition, habits, supplements, CGM spotlight, gait, weather, travel banner, blood pressure, guidance, journal coach, BoD insight, anomaly alert. 4 Haiku AI calls. Writes `dashboard/data.json` + `buddy/data.json`. |

**Weekly schedule:**
| Lambda | Day / Time (PDT) | Purpose |
|---|---|---|
| `monday-compass` v1.0 | Mon 8:00 AM | Forward-looking planning email. Todoist tasks by pillar, cross-pillar prioritization AI, overdue debt, Board Pro Tips, Keystone action. |
| `wednesday-chronicle` v1.1 | Wed 8:00 AM | "The Measured Life" — Elena Voss narrative journalism. Thesis-driven synthesis, Board interviews, S3 blog post. |
| `weekly-plate` v1.0 | Fri 7:00 PM | Food-focused magazine column with grocery list for Met Market. ~$0.04/week. |

... [TRUNCATED — 168 lines omitted, 468 total]


---

## 4. INFRASTRUCTURE REFERENCE

# Life Platform — Infrastructure Reference

> Quick-reference for all URLs, IDs, and configuration. No secrets stored here.
> Last updated: 2026-03-08 (v3.1.3 — 39 Lambdas, 8 secrets, ~47 alarms)

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
| Tools | 144 across 30 modules |
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
| Partitions (27) | whoop, eightsleep, garmin, strava, withings, habitify, macrofactor, apple_health, notion_journal, todoist, weather, supplements, cgm, labs, genome, dexa, day_grade, habit_scores, character_sheet, chronicle, coaching_insights, life_events, contacts, temptations, cold_heat_exposure, exercise_variety, adaptive_mode |

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

## Secrets Manager (8 active secrets + 1 pending deletion)

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
| ~~`api-keys`~~ | ~~Legacy bundle~~ | ~~**PENDING DELETION** (~2026-04-07). All Lambdas migrated to per-service secrets. Verify before deleting.~~ |

---

## Lambdas (39)

### Ingestion (13)
`whoop-data-ingestion` · `eightsleep-data-ingestion` · `garmin-data-ingestion` · `strava-data-ingestion` · `withings-data-ingestion` · `habitify-data-ingestion` · `macrofactor-data-ingestion` · `notion-journal-ingestion` · `todoist-data-ingestion` · `weather-data-ingestion` · `health-auto-export-webhook` · `journal-enrichment` · `activity-enrichment`

### Email / Digest (7)
`daily-brief` · `weekly-digest` · `monthly-digest` · `nutrition-review` · `wednesday-chronicle` · `weekly-plate` · `monday-compass` · `anomaly-detector`

### Compute (5)
`character-sheet-compute` · `adaptive-mode-compute` · `daily-metrics-compute` · `daily-insight-compute` · `hypothesis-engine`

### Infrastructure (14) — 4 new in v3.x hardening sprint
`life-platform-freshness-checker` · `dropbox-poll` · `insight-email-parser` · `life-platform-key-rotator` · `dashboard-refresh` · `life-platform-data-export` · `life-platform-qa-smoke` · `life-platform-mcp` · `dlq-consumer` *(new)* · `life-platform-canary` *(new)* · `data-reconciliation` *(new)* · `pip-audit` *(new)*

### Lambda@Edge (us-east-1)
`life-platform-cf-auth` (dashboard) · `life-platform-buddy-auth` (buddy page)

---

## EventBridge Scheduler

Migrated from EventBridge Rules → EventBridge Scheduler on 2026-03-08 (P1.6).

| Field | Value |
|-------|-------|
| Scheduler group | `life-platform` |
| Timezone | `America/Los_Angeles` (DST-safe — no manual rule updates needed at DST transitions) |
| IAM role | `life-platform-scheduler-role` |
| Old rules | Disabled (not deleted) — rollback: `aws events enable-rule --name <rule>` |
| Schedules | 27+ total — see PROJECT_PLAN.md Ingestion Schedule for full timing. New in v3.x: canary (every 30 min), dlq-consumer (every 15 min), data-reconciliation (daily 6 AM PT), pip-audit (weekly) |

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

... [TRUNCATED — 28 lines omitted, 228 total]


---

## 5. ARCHITECTURE DECISIONS (ADRs)

## ADR Index

| # | Title | Status | Date |
|---|-------|--------|------|
| ADR-001 | Single-table DynamoDB design | ✅ Active | 2026-02-23 |
| ADR-002 | Lambda Function URL over API Gateway for MCP | ✅ Active | 2026-02-23 |
| ADR-003 | MCP over REST API for Claude integration | ✅ Active | 2026-02-24 |
| ADR-004 | Source-of-truth domain ownership model | ✅ Active | 2026-02-25 |
| ADR-005 | No GSI on DynamoDB table | ✅ Active | 2026-02-25 |
| ADR-006 | DynamoDB on-demand billing over provisioned | ✅ Active | 2026-02-25 |
| ADR-007 | Lambda memory 1024 MB over provisioned concurrency | ✅ Active | 2026-02-26 |
| ADR-008 | No VPC — public Lambda endpoints with auth | ✅ Active | 2026-02-27 |
| ADR-009 | CloudFront + S3 static site over server-rendered dashboard | ✅ Active | 2026-02-27 |
| ADR-010 | Reserved concurrency over WAF | ✅ Active | 2026-02-28 |
| ADR-011 | Whoop as sleep SOT over Eight Sleep | ✅ Active | 2026-03-01 |
| ADR-012 | Board of Directors as S3 config, not code | ✅ Active | 2026-03-01 |
| ADR-013 | Shared Lambda Layer for common modules | ✅ Active | 2026-03-05 |
| ADR-014 | Secrets Manager consolidation (12→8) | ✅ Active | 2026-03-05 |
| ADR-015 | Compute→Store→Read pattern for intelligence features | ✅ Active | 2026-03-06 |
| ADR-016 | platform_memory DDB partition over vector store | ✅ Active | 2026-03-07 |
| ADR-017 | No fine-tuning — prompt + context engineering instead | ✅ Active | 2026-03-07 |
| ADR-018 | CDK for IaC over Terraform | ✅ Active | 2026-03-09 |
| ADR-019 | SIMP-2 ingestion framework: adopt for new Lambdas, skip migration of existing | ✅ Active | 2026-03-09 |
| ADR-020 | MCP tool functions BEFORE TOOLS={} dict | ✅ Active | 2026-02-26 |
| ADR-021 | EventBridge rule naming convention (CDK) | ✅ Active | 2026-03-10 |
| ADR-022 | CoreStack scoping — shared infrastructure vs. per-stack resources | ✅ Active | 2026-03-10 |
| ADR-023 | Sick day checker as shared utility, not standalone Lambda | ✅ Active | 2026-03-10 |

---


---

## 6. SLOs

# Life Platform — Service Level Objectives (SLOs)

> OBS-3: Formal SLO definitions for critical platform paths.
> Last updated: 2026-03-09 (v3.2.0)

---

## Overview

Four SLOs define the platform's reliability contract. Each SLO has a measurable Service Level Indicator (SLI), a target, and a CloudWatch alarm that fires on breach.

All SLO alarms publish to `life-platform-alerts` SNS topic. The operational dashboard (`life-platform-ops`) includes an SLO tracking widget section.

---

## SLO Definitions

### SLO-1: Daily Brief Delivery

| Field | Value |
|-------|-------|
| **SLI** | Daily Brief Lambda completes without error |
| **Target** | 99% (≤3 missed days per year) |
| **Window** | Rolling 30-day |
| **Alarm** | `slo-daily-brief-delivery` — fires if Daily Brief Lambda errors ≥1 in a 24-hour period |
| **Metric** | `AWS/Lambda::Errors` for `daily-brief`, Sum, 24h period |
| **Recovery** | Check CloudWatch logs → fix code or data issue → re-invoke manually |

**Why 99% not 99.9%:** Single-user platform with no revenue SLA. 99% allows for the occasional bad deploy or upstream API outage without false-alarming. One missed day is annoying, not dangerous.

---

### SLO-2: Data Source Freshness

| Field | Value |
|-------|-------|
| **SLI** | Number of monitored data sources with data older than 48 hours |
| **Target** | 99% of checks show 0 stale sources |
| **Window** | Rolling 30-day |
| **Alarm** | `slo-source-freshness` — fires if `StaleSourceCount > 0` for 2 consecutive checks |
| **Metric** | `LifePlatform/Freshness::StaleSourceCount`, custom metric emitted by `freshness_checker_lambda.py` |
| **Recovery** | Identify stale source → check ingestion Lambda logs → fix auth/API issue → manually invoke |

**Monitored sources (9):** Whoop, Withings, Strava, Todoist, Apple Health, Eight Sleep, MacroFactor, Garmin, Habitify.

**Why 48h threshold:** Many sources only sync once daily. A 24h threshold would false-alarm on normal timezone drift. 48h catches genuine failures while tolerating expected gaps (e.g., no MacroFactor data on a day Matthew doesn't log food).

---

### SLO-3: MCP Availability

| Field | Value |
|-------|-------|
| **SLI** | MCP Lambda invocations that complete without error |
| **Target** | 99.5% |
| **Window** | Rolling 7-day |
| **Alarm** | `slo-mcp-availability` — fires if MCP Lambda error rate exceeds 0.5% over 1 hour |
| **Metric** | `AWS/Lambda::Errors` / `AWS/Lambda::Invocations` for `life-platform-mcp` |
| **Recovery** | Check CloudWatch logs → redeploy from last-known-good code |

**Why 99.5%:** MCP is the interactive query layer — errors directly block Claude from answering questions. Higher bar than batch email Lambdas.

**Cold start note:** Cold starts (~700-800ms) are not errors. The SLI measures availability (error-free completion), not latency. A separate informational metric tracks p95 duration.

---

### SLO-4: AI Coaching Success

| Field | Value |
|-------|-------|
| **SLI** | Anthropic API calls that return a valid response |
| **Target** | 99% |
| **Window** | Rolling 7-day |
| **Alarm** | `slo-ai-coaching-success` — fires if `AnthropicAPIFailure` count exceeds 2 in a 24-hour period |
| **Metric** | `LifePlatform/AI::AnthropicAPIFailure` (already emitted by `ai_calls.py`) |
| **Recovery** | Check Anthropic status page → if upstream outage, wait. If code issue, fix prompt/parsing |

**Why count-based not rate-based:** The platform makes ~15-20 AI calls/day across all Lambdas. A rate-based alarm with so few datapoints would be noisy. A count threshold of 2 failures/day means something is systematically wrong (not just a transient 429).

---

## CloudWatch Dashboard Widgets

The `life-platform-ops` dashboard includes an "SLO Health" section with:

1. **SLO Status Panel** — 4 metric widgets showing current alarm states
2. **Daily Brief Success Rate** — 30-day graph of daily-brief errors
3. **Source Freshness Trend** — 30-day graph of stale source count
4. **MCP Error Rate** — 7-day graph of MCP error count
5. **AI Failure Trend** — 7-day graph of Anthropic API failures

---

## SLO Review Cadence

- **Weekly:** Glance at ops dashboard SLO section during Weekly Digest review
- **Monthly:** Review any SLO breaches in Monthly Digest (future integration)
- **Quarterly:** Review whether SLO targets need adjustment based on platform growth

---

... [TRUNCATED — 11 lines omitted, 111 total]


---

## 7. INCIDENT LOG

# Life Platform — Incident Log

Last updated: 2026-03-10 (v3.4.9)

> Tracks operational incidents, outages, and bugs that affected data flow or system behavior.
> For full details on any incident, check the corresponding CHANGELOG entry or handover file.

---

## Severity Levels

| Level | Definition |
|-------|------------|
| **P1 — Critical** | System broken, no data flowing or MCP completely down |
| **P2 — High** | Major feature broken, data loss risk, or multi-day data gap |
| **P3 — Medium** | Single source affected, degraded but functional |
| **P4 — Low** | Cosmetic, minor data quality, or transient error |

---

## Incident History

| Date | Severity | Summary | Root Cause | TTD* | TTR* | Data Loss? |
|------|----------|---------|------------|------|------|------------|
| 2026-02-28 | **P1** | 5 of 6 API ingestion Lambdas failing after engineering hardening (v2.43.0) | Handler mismatches (4 Lambdas had `lambda_function.py` but handlers pointed to `X_lambda.lambda_handler`), Garmin missing deps + IAM, Withings cascading OAuth expiry | ~hours (next scheduled run) | ~2 hr (sequential fixes) | No — gap-aware backfill self-healed all missing data. Full PIR: `docs/PIR-2026-02-28-ingestion-outage.md` |
| 2026-02-26 | **P1** | MCP server broken since v2.31.0 — every invocation failing with NameError | 3 tool functions defined AFTER TOOLS dict that references them at module load | ~hours | 30 min | No (server returned errors, no silent corruption) |
| 2026-02-26 | P3 | 5 MCP tools failing with `get_table()` NameError | Functions referenced undefined `get_table()` instead of module-level `table` | Found during P1 fix | 15 min | No |
| 2026-02-25 | P3 | Anomaly detector never running on schedule | EventBridge rule `anomaly-detector-daily` never created despite Lambda existing | ~days | 10 min | No (Lambda existed, just never invoked) |
| 2026-02-25 | P4 | Enrichment alarm watching wrong function name | Alarm dimension: `activity-enrichment-nightly` (rule) instead of `activity-enrichment` (Lambda) | Found in audit | 5 min | No |
| 2026-03-03 | **P2** | Hydration data missing/near-zero for 7+ days (Feb 24–Mar 2) | Health Auto Export app not including Dietary Water/Caffeine in automatic webhook pushes — only sending activity metrics. Caused by infrequent sync schedule producing too-large payloads that silently drop nutrition metrics. | ~8 days | 1 hr | Recovered — user forced 7-day water push from app, day grades regraded via new `regrade_dates` mode |
| 2026-03-03 | P3 | Buddy page showing 12-13 exercise sessions (actual: ~2) | Two bugs: (1) rolling 7-day window instead of Monday–Sunday weekly count, (2) WHOOP+Garmin both push to Strava creating duplicate activities | ~2 days | 30 min | No (display only, raw data correct) |
| 2026-03-03 | P3 | Buddy page "No food logged in 99 days" | MacroFactor field name mismatch: code checked `calories`/`energy_kcal`, data uses `total_calories_kcal` | ~2 days | 15 min | No (display only, raw data correct) |
| 2026-03-05 | **P2** | dashboard-refresh Lambda silently failing on every run since deployment | IAM role missing `s3:PutObject` on `dashboard/` path. Lambda invoked successfully but AccessDenied on write. New alarm detected it within hours of being added | Since initial deploy | 30 min | Dashboard never updated by this Lambda (Daily Brief still wrote dashboard data correctly — no user-visible impact) |
| 2026-03-04 | **P2** | wednesday-chronicle + anomaly-detector failing with ImportModuleError since last deploy | Wrong filenames in zip packages — deploy script used hardcoded filenames rather than reading handler config from AWS. Both Lambdas silently broken. Chronicle missed one installment; anomaly detector not running; 5 DLQ messages accumulated | ~2 days | 1 hr | Chronicle: 1 missed installment (backfilled). Anomaly: backfilled Mar 4-5. Root fix: deploy_lambda.sh now auto-reads handler config |
| 2026-03-04 | P3 | State of Mind Lambda deploy not updating | deploy_lambda.sh zipped wrong filename for state-of-mind handler; fixed in v2.70.1 with universal deploy script that reads handler config from AWS | ~1 session | 20 min | No |
| 2026-03-05 | **P2** | dropbox-poll failing with InvalidRequestException on every run since secrets consolidation | Secrets consolidation (v2.75.0) deleted `life-platform/dropbox` secret but Lambda had `SECRET_NAME=life-platform/dropbox` hardcoded as env var, overriding the correct code default. Additionally key names in `api-keys` bundle use `dropbox_` prefix (`dropbox_app_key` etc.) vs old secret's unprefixed names (`app_key`) | Hours (new alarm, alarming proves its worth) | 30 min | No Dropbox polling since secrets consolidation; MacroFactor CSV auto-import non-functional. Fixed: env var updated to `life-platform/api-keys`, key lookups patched in code (v2.76.1) |
| 2026-03-05 | P3 | dashboard-refresh + life-platform-data-export alarms firing from earlier IAM failures | Both Lambdas had IAM fixed during tech debt session (v2.75.0) but earlier failed runs had already triggered alarms. Both resolved on next successful run. | Hours (alarm) | Self-resolved after IAM fix | No — dashboard was still being written by daily-brief; export recovered on subsequent run |
| 2026-03-04 | P3 | character-sheet-compute failing with AccessDenied on S3 + DynamoDB | IAM role missing s3:GetObject on config bucket and dynamodb:PutItem permission. Lambda silently failing since deployment | ~1 day | 30 min | No (compute re-run via backfill) |
| 2026-02-25 | P4 | Day grade zero-score — journal and hydration dragging grades down | `score_journal` returned 0 instead of None when no entries; hydration noise <118ml scored | 1 day | 20 min | No (grades recalculated) |
| 2026-02-25 | P3 | Strava multi-device duplicate activities inflating movement score | WHOOP + Garmin recording same walk → duplicate in Strava | ~days | 30 min | No (dedup applied in brief; raw data retained) |
| 2026-03-10 | **P2** | All three web URLs (dash/blog/buddy) showing TLS cert error — `ERR_CERT_COMMON_NAME_INVALID` | `web_stack.py` had `CERT_ARN_* = None` placeholders — CDK deployed distributions without `viewer_certificate`, causing CloudFront to serve default `*.cloudfront.net` cert. Introduced during PROD-1 (v3.3.5). | Hours (noticed by user) | 15 min (v3.4.9) | No (data unaffected; all URLs inaccessible via HTTPS) |
| 2026-03-08 | **P3** | `todoist-data-ingestion` failing since 2026-03-06 | Stale `SECRET_NAME` env var (`life-platform/api-keys`) set on the Lambda — when api-keys was soft-deleted as part of secrets decomposition, the env var override started producing `ResourceNotFoundException`. Code default was correct but env var took precedence. DLQ consumer caught accumulated failures at 9:15 AM on 2026-03-08. | ~2 days | 15 min (env var removed + Lambda redeployed) | No — Todoist ingestion gap 2026-03-06 to 2026-03-08. Gap-aware backfill (7-day lookback) self-healed all missing task records on next run. |
| 2026-03-08 | **Info** | `data-reconciliation` first run reported RED: 17 gaps across 6 sources | Bootstrap noise, not real failures. First run has no prior reference point — all "gaps" were expected coldstart artifacts (MacroFactor real data only from 2026-02-22, habit gap 2025-11-10→2026-02-22, etc.). | First run | No action needed — monitor next 3 runs for convergence to GREEN | No |
| 2026-03-09 | **P2** | All 23 CDK-managed Lambdas broken after first CDK deploy (PROD-1, v3.3.5) | `Code.from_asset("..")` bundles files at `lambdas/X.py` inside a subdirectory, but Lambda expects `X.py` at zip root — causing `ImportModuleError` on every invocation. Affected: 7 Compute + 8 Email + 1 MCP + 7 Operational Lambdas. | Next scheduled run post-deploy | ~1 hr (`deploy/redeploy_all_cdk_lambdas.sh` redeployed all 23 via `deploy_lambda.sh`) | No — gap-aware backfill + DLQ drained. Permanent fix: update `lambda_helpers.py` to `Code.from_asset("../lambdas")` (tracked as TODO) |
| 2026-03-10 | **P1** | CDK IAM bulk migration — Lambda execution role gap during v3.4.0 deploy | CDK deleted 39 old IAM roles before confirming CDK-managed replacement roles were fully propagated and attached. Two email Lambdas (`wednesday-chronicle`, `nutrition-review`) had no execution role for ~5 min during the migration window, causing invocation failures on any warmup or invocation in that window. Root fix: `cdk deploy` sequencing — always verify role attachment before deleting old roles. *Identified retroactively during Architecture Review #4.* | Deploy logs (real-time) | ~15 min (CDK re-apply with `--force`) | No — no scheduled runs in migration window |
| 2026-03-10 | **P2** | CoreStack SQS DLQ ARN changed on CDK-managed recreation — DLQ send failures across all async Lambdas | CoreStack created a new CDK-managed DLQ (`life-platform-ingestion-dlq`) with a different ARN than the manually-created original. CDK-deployed Lambda env vars referenced the new ARN, but 3 Lambdas that had the old ARN cached in env var overrides (`SECRET_NAME`-style pattern) continued sending to the deleted queue. Result: DLQ send failures and silent dead-letter drop for ~30 min. *Identified retroactively during Architecture Review #4.* | CloudWatch errors (~30 min lag) | CDK update pushed correct ARN to all Lambda configs | Possible: some DLQ messages lost during gap window |
| 2026-03-10 | **P3** | EB rule recreation gap: 2 ingestion Lambdas missed scheduled morning runs during v3.4.0 migration | Old EventBridge rules deleted first; CDK replacements deployed after. 2 ingestion Lambdas (`withings-data-ingestion`, `eightsleep-data-ingestion`) missed their 7:15 AM / 8:00 AM PT windows during ~10 min gap between deletion and CDK rule creation. *Identified retroactively during Architecture Review #4.* | Freshness checker alert (10:45 AM) | Gap-aware backfill self-healed on next scheduled run | No — backfill recovered all missing data |
| 2026-03-10 | **P3** | Orphan Lambda adoption: `failure-pattern-compute` Sunday EB rule not included in CDK Compute stack definition | When 3 orphan Lambdas were adopted into CDK (v3.4.0), the `failure-pattern-compute` Sunday 9:50 AM EventBridge rule was omitted from the Compute stack definition. Lambda did not execute for ~1 week (one missed Sunday run). *Identified retroactively during Architecture Review #4.* | Architecture Review #4 inspection | EB rule added to CDK Compute stack | No — failure pattern memory records simply not generated for that week |
| 2026-03-10 | **P4** | Duplicate CloudWatch alarms after CDK Monitoring stack adoption of orphan Lambdas | CDK Monitoring stack created new alarms for 3 newly-adopted Lambdas (`failure-pattern-compute`, `brittany-email`, `sick-day-checker`) that already had manually-created alarms — resulting in 9 duplicate alarms with overlapping SNS notifications and alert fatigue. *Identified retroactively during Architecture Review #4.* | Architecture Review #4 alarm audit | Manual alarms deleted; CDK alarms authoritative | No |
| 2026-03-09 | **P2** | All 13 ingestion Lambdas failing with `AttributeError: 'Logger' object has no attribute 'set_date'` | After `platform_logger.py` added `set_date()` to support OBS-1 structured logging, ingestion Lambdas had stale bundled copies of `platform_logger.py` missing the new method. 14 DLQ messages accumulated. Affected: whoop, eightsleep, withings, strava, todoist, macrofactor, garmin, habitify, notion, journal-enrichment, dropbox-poll, weather, activity-enrichment. | DLQ depth alarm + CloudWatch errors | ~30 min (`deploy/redeploy_ingestion_with_logger.sh` redeployed all 13 with `--extra-files lambdas/platform_logger.py`). DLQ purged in v3.3.8. | No — gap-aware backfill recovered all ingestion gaps. |
| 2026-02-25 | P4 | Daily brief IAM — day grade PutItem AccessDeniedException | `lambda-weekly-digest-role` missing `dynamodb:PutItem` | Since v2.20.0 | 10 min | Grades not persisted until fixed |
| 2026-02-24 | P2 | Apple Health data not flowing — 2+ day gap | Investigated wrong Lambda (`apple-health-ingestion` vs `health-auto-export-webhook`) + deployment timing | ~2 days | 4 hr investigation, 15 min actual fix | No (S3 archives preserved, backfill recovered) |
| 2026-02-24 | P3 | Garmin Lambda pydantic_core binary mismatch | Wrong platform binary in deployment package | 1 day | 30 min | No |
| 2026-02-24 | P3 | Garmin data gap (Jan 19 – Feb 23) | Garmin app sync issue (Battery Saver mode suspected) | ~5 weeks | Backfill script | Partial (gap backfilled from Feb 23 forward) |
| 2026-02-23 | P4 | Habitify alarm in ALARM state | Transient Lambda networking error ("Cannot assign requested address") | Hours | Manual alarm reset | No (re-invoked successfully) |
| 2026-02-23 | P4 | DynamoDB TTL field name mismatch | Cache using `ttl_epoch` but TTL configured on `ttl` attribute | ~1 day | 5 min | No (cache items never expired, just accumulated) |
| 2026-02-23 | P4 | Weight projection sign error in weekly digest | Delta calculation reversed (showing gain as loss) | 1 day | 5 min | No |
| 2026-02-23 | P4 | MacroFactor hit rate denominator off | Division denominator using wrong field | 1 day | 5 min | No |

*TTD = Time to Detect, TTR = Time to Resolve

---

## Patterns & Observations

**Most common root causes:**
1. **Deployment errors** (wrong function ordering, missing IAM, wrong binary, CDK packaging) — 7 incidents
2. **Stale config / env var overrides** (SECRET_NAME env var pointing at deleted secret) — 3 incidents
3. **Wrong component investigated** (two Apple Health Lambdas, alarm dimension mismatch) — 3 incidents
4. **Missing infrastructure** (EventBridge rule never created, IAM missing permission) — 2 incidents
5. **Data quality / scoring logic** (zero-score defaults, dedup, sign errors) — 4 incidents

**CDK packaging watch-out:** `Code.from_asset("..")` bundles source files one directory deep in the zip — Lambda can't find the handler. Always use `Code.from_asset("../lambdas")` (points at the lambdas directory directly). When CDK-managing Lambdas for the first time, verify a sample function works before assuming all 23 are healthy. `deploy_lambda.sh` is immune to this bug.

**Stale lambda module caches:** When a shared module (like `platform_logger.py`) adds new methods, all Lambdas that bundle their own copy of that file need to be redeployed. CDK packaging re-bundles from source automatically; `deploy_lambda.sh --extra-files` is the manual equivalent for Lambdas not yet on CDK.

**Secrets consolidation watch-out:** When consolidating Secrets Manager entries, Lambdas with `SECRET_NAME` (or similar) set as explicit env vars will override code defaults and continue pointing at the deleted secret. Always audit Lambda env vars — not just code — when retiring secrets. Also verify key naming conventions match between old and new secret schemas.

**Key lesson (from RCA):** When data isn't flowing, check YOUR pipeline first (CloudWatch logs for the receiving Lambda), not the external dependency. Document the full request path so you investigate the right component.

---

## Open Monitoring Gaps

| Gap | Risk | Mitigation |
|-----|------|------------|
| No end-to-end data flow dashboard | Slow detection of silent failures | Freshness checker provides daily coverage |
| DLQ coverage: MCP + webhook excluded | Request/response pattern — DLQ not applicable | CloudWatch error alarms cover both |
| No webhook health check endpoint | Can't externally monitor webhook availability | CloudWatch alarm on zero invocations/24h |
| No duration/throttle alarms | Timeouts without errors go undetected | Daily brief and MCP are most at risk |

**Resolved gaps (v2.75.0):** All 29 Lambdas now have CloudWatch error alarms. 10 log groups now have 30-day retention. Deployment zip filename bug eliminated by `deploy_lambda.sh` auto-reading handler config from AWS.

**Resolved gaps (v3.1.x):** DLQ consumer Lambda (`dlq-consumer`) now drains and logs failures from `life-platform-ingestion-dlq` on a schedule — silent DLQ accumulation is now caught proactively. Canary Lambda (`life-platform-canary`) runs synthetic DDB+S3+MCP round-trip every 30 min with 4 CloudWatch alarms — end-to-end health check is now automated. `item_size_guard.py` monitors 400KB DDB write limits before they cause failures.


---

## 8. INTELLIGENCE LAYER

# Life Platform — Intelligence Layer

> Documents the Intelligence Compounding (IC) features: how the platform learns, remembers, and improves over time.
> For the IC roadmap and future phases, see PROJECT_PLAN.md (Tier 7).
> Last updated: 2026-03-09 (v3.3.9)

---

## Overview

The Intelligence Layer transforms the platform from a stateless data observer into a compounding intelligence engine. Rather than running the same analysis fresh each day and generating the same generic insight repeatedly, the IC system:

1. **Persists** insights and patterns to DynamoDB (`platform_memory`, `insights`, `decisions`, `hypotheses`)
2. **Compounds** — each new analysis reads previous findings as context
3. **Learns** Matthew's specific biology, psychology, and failure patterns over time
4. **Self-improves** — coaching calibration evolves as evidence accumulates

The architecture decision (ADR-016) is explicit: no vector store, no embeddings, no fine-tuning. Pure DynamoDB key-value + structured context injection + prompt engineering.

---

## Architecture

```
┌──────────────────────────────────────────────────────────────┐
│  PRE-COMPUTE PIPELINE (runs before Daily Brief)              │
│                                                              │
│  9:35 AM  character-sheet-compute                            │
│  9:40 AM  daily-metrics-compute → computed_metrics DDB       │
│  9:42 AM  daily-insight-compute → insight_data (JSON)        │
│           ├─ 7-day habit × outcome correlations              │
│           ├─ leading indicator flags                         │
│           ├─ platform_memory pull (relevant records)         │
│           └─ structured JSON handoff to Daily Brief          │
│                                                              │
│  SUNDAY   hypothesis-engine (11 AM PT)                       │
│           └─ cross-domain hypotheses → hypotheses DDB        │
└─────────────────────────────────┬────────────────────────────┘
                                  │ reads pre-computed data
┌─────────────────────────────────▼────────────────────────────┐
│  AI CALL LAYER (all email/digest Lambdas)                    │
│                                                              │
│  IC-3: Chain-of-thought two-pass (BoD + TL;DR)               │
│    Pass 1: identify patterns + causal chains (JSON)          │
│    Pass 2: write coaching output using Pass 1 analysis       │
│                                                              │
│  IC-7: Cross-pillar trade-off reasoning instruction          │
│  IC-23: Attention-weighted prompt budgeting (surprise score) │
│  IC-24: Data quality scoring (flag incomplete sources)       │
│  IC-25: Diminishing returns detection (per-pillar)           │
│  IC-17: Red Team / Contrarian Skeptic pass (anti-confirmation│
│          bias, challenges correlation claims)                │
└─────────────────────────────────┬────────────────────────────┘
                                  │ writes after generation
┌─────────────────────────────────▼────────────────────────────┐
│  MEMORY LAYER                                                │
│                                                              │
│  insight_writer.py (shared module in Lambda Layer)           │
│  → SOURCE#insights — universal write by all email Lambdas    │
│  → SOURCE#platform_memory — failure patterns, milestones,    │
│    intention tracking, what worked, coaching calibration      │
│  → SOURCE#decisions — platform decisions + outcomes          │
│  → SOURCE#hypotheses — weekly generated cross-domain hypotheses│
└──────────────────────────────────────────────────────────────┘
```

---

## Live IC Features (as of v3.3.9)

### IC-1: platform_memory Partition
**Status:** Live (v2.86.0)  
**What it does:** DDB partition `SOURCE#platform_memory`, SK `MEMORY#<category>#<date>`. The compounding substrate — structured memory written by compute Lambdas and digest Lambdas, read back into AI prompts as context. Enables "the last 4 weeks show X pattern" without re-querying raw data.

**Memory categories live:** `milestone_architecture`, `intention_tracking`  
**Memory categories coming:** `failure_patterns` (Month 2), `what_worked` (Month 3), `coaching_calibration` (Month 3), `personal_curves` (Month 4)

### IC-2: Daily Insight Compute Lambda
**Status:** Live (v2.86.0)  
**Lambda:** `daily-insight-compute` (9:42 AM PT)  
**What it does:** Pre-computes structured insight JSON before Daily Brief runs. Pulls 7 days of metrics, computes habit×outcome correlations, flags leading indicators, pulls relevant platform_memory records. Daily Brief receives curated intelligence rather than raw data.

**Key output fields in insight JSON:**
- `habit_outcome_correlations` — which habit completions correlate with better sleep/recovery
- `leading_indicators` — early warning signals (e.g., HRV declining 3 consecutive days)
- `memory_context` — relevant platform_memory records for today's conditions
- `data_quality` — per-source confidence scores (IC-24)
- `surprise_scores` — per-metric deviation from rolling baseline (IC-23)

### IC-3: Chain-of-Thought Two-Pass
**Status:** Live (v2.86.0)  
**What it does:** Board of Directors + TL;DR AI calls use two-pass reasoning. Pass 1 generates structured JSON identifying patterns and causal chains. Pass 2 writes coaching output using Pass 1 analysis. ~2× token cost but material quality improvement — model reasons before writing.

### IC-6: Milestone Architecture
**Status:** Live (v2.86.0)  
**What it does:** 6 weight/health milestones with biological significance for Matthew stored in `platform_memory`. Surfaced in coaching when approaching each threshold. Example: "At 285 lbs: sleep apnea risk drops substantially (genome flag)." Converts abstract goal into biological waypoints.

**Current milestones:** 285 lbs (sleep apnea risk), 270 lbs (walking pace natural improvement), 250 lbs (Zone 2 accessible at real-workout pace), 225 lbs (FFMI crosses athletic range), 200 lbs (visceral fat normalization target), 185 lbs (goal weight).

### IC-7: Cross-Pillar Trade-off Reasoning
**Status:** Live (v2.89.0)  
**What it does:** Explicit instruction added to Board of Directors prompts to reason about trade-offs between pillars rather than analyzing each in isolation. Enables: "Movement is strong but Sleep is degrading — adding training volume at current TSB will compound sleep debt. Optimize sleep first."

### IC-8: Intent vs. Execution Gap
**Status:** Live (v2.90.0)  
**What it does:** Journal analysis pass comparing stated intentions ("going to meal prep Sunday") against next-day metrics. Builds personal intention-completion rate. Writes to `MEMORY#intention_tracking`. Coaching AI told when stated intentions have historically not been followed through.

### IC-15: Insight Ledger
**Status:** Live (v2.87.0)  
**What it does:** Universal write-on-generate — every email/digest Lambda appends a structured insight record to `SOURCE#insights` via `insight_writer.py` (shared Layer module). Accumulates the raw material for downstream IC features. Schema: pillar, data_sources, confidence, actionable flag, semantic tags, digest_type, generated_text hash (dedup).

### IC-16: Progressive Context — All Digests
**Status:** Live (v2.88.0)  
**What it does:** Weekly Digest, Monthly Digest, Chronicle, Nutrition Review, and Weekly Plate all retrieve recent high-value insights before generating. Weekly Digest gets 30-day window; Monthly gets quarterly; Chronicle gets narrative-relevant threads. Each digest reads as if written by someone who has followed Matthew for months. ~500-1,500 extra tokens per call.

### IC-17: Red Team / Contrarian Pass
**Status:** Live (v2.87.0)  
**What it does:** "The Skeptic" persona injected into Board of Directors calls. Explicitly tasked to challenge consensus — question whether correlations are causal, flag misleading data, identify when insights are obvious vs. genuinely novel. Counteracts single-model confirmation bias. Prompt-only change, zero cost.

### IC-18: Hypothesis Engine Lambda
**Status:** Live (v2.89.0)  
**Lambda:** `hypothesis-engine` (Sunday 11 AM PT)  
**What it does:** Weekly Lambda pulls 14 days of all-pillar data. Prompts Claude to identify non-obvious cross-domain correlations the existing 144 tools don't explicitly monitor. Writes hypothesis records to `SOURCE#hypotheses`. Subsequent insight compute + digest prompts told to watch for confirming/refuting evidence.

**Validation rules (v1.1.0):** Fields + domains + numeric criteria required. Dedup check against active hypotheses. 30-day hard expiry. Min 7 days sample. 3 confirming checks required for promotion to permanent check.

Access: `get_active_hypotheses`, `evaluate_hypothesis` MCP tools.

### IC-19: Decision Journal
**Status:** Live (v2.88.0)  
**What it does:** Tracks platform-guided decisions and their outcomes. `log_decision` MCP tool or inferred from journal + metrics. Builds trust-calibration dataset. Access via `log_decision`, `get_decision_journal`, `get_decision_effectiveness` MCP tools.

### IC-23: Attention-Weighted Prompt Budgeting
**Status:** Live (v2.88.0)  
**What it does:** Pre-processing step computes "surprise score" for every metric — deviation from personal rolling baseline. High-surprise metrics get expanded context in AI prompts; low-surprise ones compress to one line or are omitted. `_compute_surprise_scores(data, baselines)` returns metric → surprise_score (0-1). Information theory applied to prompt engineering.

### IC-24: Data Quality Scoring
**Status:** Live (v2.88.0)  
**What it does:** `_compute_data_quality(data)` runs before AI calls. Per-source confidence score based on completeness, recency, and consistency. Outputs compact quality block injected into prompts: "⚠️ Nutrition: 800 cal — likely incomplete (7d avg 1,750)". AI treats flagged sources with skepticism.

### IC-25: Diminishing Returns Detector
**Status:** Live (v2.88.0)  
**What it does:** Weekly computation of each pillar's score trajectory vs. effort (habit completion rate, active habit count). When high effort + flat trajectory detected, coaching redirects to highest-leverage pillar. "Sleep optimization is mature at 82 — your biggest lever is movement consistency at 45%."

---

## Prompt Architecture Standards

All IC-era AI calls follow these structural standards:


... [TRUNCATED — 98 lines omitted, 248 total]


---

## 9. TIER 8 HARDENING STATUS

### Tier 8 — Architecture Review Hardening (added 2026-03-08)

> Full architecture review conducted 2026-03-08 at v2.91.0. Results: `docs/REVIEW_2026-03-08.md`. Methodology: `docs/REVIEW_METHODOLOGY.md`. Review bundle script: `deploy/generate_review_bundle.sh`.
>
> **Review grades:** Architecture B+, Security C+, Reliability B-, Operability C+, Cost A, Data Quality B, AI Rigor C+, Maintainability C, Production Readiness D+.
>
> **Principle:** No new features until P0/P1 hardening items complete. Fix the plumbing before installing the smart home system.

#### Epic: Security Hardening

| # | Task | Priority | Effort | Model | Status |
|---|------|----------|--------|-------|--------|
| SEC-1 | **Decompose shared IAM role into per-function roles.** 13 dedicated roles created and assigned. Most restrictive: DDB+KMS only. | P0 | M (3-4 hr) | Sonnet | ✅ v3.1.0 |
| SEC-2 | **Split consolidated api-keys secret into domain-specific secrets.** todoist, notion, dropbox split. ai-keys isolated. api-keys pending deletion. | P1 | M (2-3 hr) | Sonnet | ✅ v3.1.0 |
| SEC-3 | **Add input validation to MCP tool arguments.** `_validate_tool_args()` in handler.py — required fields, type coercion, string caps, date format, enum. | P1 | M (3-4 hr) | Sonnet | ✅ v3.1.0 |
| SEC-4 | **Add rate limiting to API Gateway webhook.** Health Auto Export API Gateway has no WAF/rate limiting. Add 100 req/min rate rule. | P2 | S (1 hr) | Sonnet | ✅ v3.3.9 |
| SEC-5 | **Implement dependency vulnerability scanning.** pip-audit Lambda, monthly first-Monday schedule. 18 requirements files scanned. | P2 | S (1-2 hr) | Sonnet | ✅ v3.1.3 |

#### Epic: IAM Cleanup

| # | Task | Priority | Effort | Model | Status |
|---|------|----------|--------|-------|--------|
| IAM-1 | **Audit all Lambda IAM roles for excessive permissions.** SES wildcards scoped, api-keys-read scoped per domain, KMS policy updated. | P1 | M (3-4 hr) | Sonnet | ✅ v3.1.1 |
| IAM-2 | **Enable IAM Access Analyzer.** Enabled, findings triaged. | P2 | S (1 hr) | Sonnet | ✅ v2.99.0 |

#### Epic: Reliability & Recovery

| # | Task | Priority | Effort | Model | Status |
|---|------|----------|--------|-------|--------|
| REL-1 | **Add compute failure signals.** 4 CW alarms + html_builder staleness banner. | P1 | M (3-4 hr) | Sonnet | ✅ v3.1.0 |
| REL-2 | **Implement DLQ consumer Lambda.** Deployed, classified + retried 4 real messages on first run. Found todoist SECRET_NAME bug. | P2 | M (3-4 hr) | Sonnet | ✅ v2.99.0 |
| REL-3 | **Add 400KB item size monitoring.** item_size_guard.py (300KB warn / 380KB truncate), CW alarm, strava + macrofactor wired. | P2 | S (2 hr) | Sonnet | ✅ v2.99.0 |
| REL-4 | **Add synthetic end-to-end health check.** Canary Lambda: DDB + S3 + MCP round-trip every 4h, dedicated partition, 4 CW alarms. | P2 | S (2 hr) | Sonnet | ✅ v2.99.0 |

#### Epic: Observability Uplift

| # | Task | Priority | Effort | Model | Status |
|---|------|----------|--------|-------|--------|
| OBS-1 | **Standardize structured logging across all Lambdas.** `platform_logger.py` built and wired into `daily-brief`. Emits structured JSON with `correlation_id` field. Incremental rollout to other Lambdas ongoing. | P1 | L (6-8 hr) | Sonnet | ⚠️ Partial (daily-brief wired) |
| OBS-2 | **Create operational health CloudWatch dashboard.** `life-platform-ops`: 23 widgets, 47 alarms, KPIs, error matrix, AI tokens. | P2 | M (3-4 hr) | Sonnet | ✅ v2.99.0 |
| OBS-3 | **Define SLOs for critical paths.** 4 SLOs defined (Daily Brief 99%, Freshness 99%, MCP 99.5%, AI 99%). 4 CW alarms + freshness metrics + ops dashboard widgets. `docs/SLOs.md`. | P3 | S (1-2 hr) | **Opus** | ✅ v3.2.0 |

#### Epic: Cost Optimization

| # | Task | Priority | Effort | Model | Status |
|---|------|----------|--------|-------|--------|
| COST-1 | **Archive unused S3 raw data to Glacier.** Lifecycle rule deployed. | P3 | S (30 min) | Sonnet | ✅ v2.99.0 |
| COST-2 | **Audit MCP tool usage and archive low-use tools.** CloudWatch metric per tool invocation. After 30 days, archive 0-invocation tools. | P2 | M (2-3 hr) | Sonnet | 🔴 |
| COST-3 | **Monitor AI token usage trends.** 14 CW alarms, per-Lambda daily budgets + $15/mo platform cap. | P2 | S (1 hr) | Sonnet | ✅ v2.99.0 |

#### Epic: Codebase Maintainability

| # | Task | Priority | Effort | Model | Status |
|---|------|----------|--------|-------|--------|
| MAINT-1 | **Add dependency management (requirements.txt per Lambda).** 18 files in `lambdas/requirements/`. Only garmin has third-party deps. | P1 | M (3-4 hr) | Sonnet | ✅ v2.99.0 |
| MAINT-2 | **Create Lambda Layer for shared modules.** 8 modules, attached to 16 Lambdas. Fix-once-deploy-everywhere. | P1 | M (3-4 hr) | Sonnet | ✅ v2.97.0 |
| MAINT-3 | **Clean deploy/ and lambdas/ directories.** lambdas/ zip-free. deploy/ archived ~247 one-off scripts → `archive/YYYYMMDD/deploy/`; 8 active files remain. | P2 | S (1-2 hr) | Sonnet | ✅ v3.3.9 |
| MAINT-4 | **Implement basic CI/CD with GitHub Actions.** 4-job pipeline: lint (flake8) → plan (change detection via `ci/lambda_map.json`) → deploy (manual approval, shared layer rebuild, MCP handling) → smoke test (qa-smoke + canary). OIDC auth. | P2 | L (6-8 hr) | **Opus** | ✅ v3.2.1 |

#### Epic: Data Model & Quality

| # | Task | Priority | Effort | Model | Status |
|---|------|----------|--------|-------|--------|
| DATA-1 | **Add schema_version to all DDB items.** All ingestion Lambdas + backfill script run. | P1 | S (2 hr) | Sonnet | ✅ v2.98.0 |
| DATA-2 | **Add ingestion validation layer.** `ingestion_validator.py` built with 19-source schemas. Wired into all 13 ingestion Lambdas. CRITICAL failures archive to S3 + skip DDB write; logs as `[DATA-2]`. enrichment/journal_enrichment use update_item — validator runs at source ingestion time. | P1 | M (4-6 hr) | Sonnet | ✅ v3.1.6 |
| DATA-3 | **Implement weekly reconciliation job.** Weekly Lambda live, email report + S3 archive. First run: RED (bootstrap noise, zero real failures). | P3 | M (3-4 hr) | Sonnet | ✅ v3.1.3 |

#### Epic: AI Trustworthiness & Validation

| # | Task | Priority | Effort | Model | Status |
|---|------|----------|--------|-------|--------|
| AI-1 | **Add health disclaimer to all AI-generated coaching.** Footer on every email. | P0 | S (1 hr) | Sonnet | ✅ v2.95.0 |
| AI-2 | **Rename correlation tools / fix causal language in prompts.** `ai_calls.py`: causal_chain → likely_connection, TRACE THE CAUSAL CHAIN → NAME THE LIKELY CORRELATIVE PATTERN, all BoD/guidance prompts use correlative framing throughout. | P2 | S (2 hr) | Sonnet | ✅ v3.1.6 |
| AI-3 | **Add output validation for AI coaching.** `ai_output_validator.py` built with BLOCK/WARN/PASS tiers. Wired into `daily-brief` — all 4 AI outputs validated before HTML build; blocked outputs replaced with safe fallbacks; logs as `[AI-3]`. | P1 | M (4-6 hr) | **Opus** | ⚠️ Partial (daily-brief wired) |
| AI-4 | **Validate IC hypothesis engine outputs.** v1.1.0: data completeness check, hypothesis validation (fields+domains+numeric criteria+dedup), 30-day hard expiry, verdict validation, min 7d sample, 3 confirming checks for promotion. | P2 | M (3-4 hr) | **Opus** | ✅ v3.2.0 |

#### Epic: Platform Simplification

| # | Task | Priority | Effort | Model | Status |
|---|------|----------|--------|-------|--------|
| SIMP-1 | **Audit and archive low-usage MCP tools.** Usage metrics (30-day). Tools with 0 invocations flagged. Target: <100 active tools. | P2 | M (3-4 hr) | Sonnet | 🔴 |
| SIMP-2 | **Consolidate ingestion Lambdas into shared framework.** `ingestion_framework.py` written. Weather Lambda migrated (POC validated). Migration stopped after technical review: 2 of 3 Phase 2 Lambdas (strava, garmin) architecturally incompatible with per-day callback pattern. Full migration ROI doesn't justify regression risk at current scale. **Decision: framework stays in Layer for future new Lambdas; existing Lambdas stay as-is.** | P3 | — | — | ✅ Closed (deliberate) |

#### Epic: Productization Readiness

| # | Task | Priority | Effort | Model | Status |
|---|------|----------|--------|-------|--------|
| PROD-1 | **Implement Infrastructure as Code (CDK).** All 8 stacks deployed: Core (SQS+SNS+Layer), Ingestion, Compute, Email, Operational, Mcp, Monitoring, Web. CDK owns all 41 Lambda IAM roles (`custom_policies`), all EventBridge rules (`schedule=`), SQS DLQ, SNS topic, Lambda Layer. DDB+S3 deliberately unmanaged (stateful). | P2 (P0 if productizing) | L (16-24 hr) | **Opus** | ✅ v3.4.0 |
| PROD-2 | **Remove hardcoded single-user assumptions.** Complete. S3 paths user-prefixed, profile loading fixed (DDB not S3), HTML fetch paths updated, DLQ purged. | P3 | L (12-16 hr) | **Opus** | ✅ v3.3.8 |

#### Hardening Summary (updated post-Review #2, v3.1.3)

| Status | Count | Items |
|--------|-------|-------|
| ✅ **Done** | 34 | SEC-1,2,3,4,5; IAM-1,2; REL-1,2,3,4; OBS-1,2,3; COST-1,2,3; MAINT-1,2,3,4; DATA-1,2,3; AI-1,2,3,4; SIMP-2; PROD-1; PROD-2 |
| 🔴 **Open** | 1 | SIMP-1 (revisit ~2026-04-08 after 30 days of EMF usage data) |

**Next hardening priorities:** PROD-2 implementation (Sonnet), then PROD-1 CDK sessions.

**SIMP-2 lessons learned:** Architectural recommendations were made without validating per-source API shapes upfront. Strava (range-based API) and Garmin (native deps) are incompatible with the per-day callback pattern. Future framework adoption: new Lambdas fitting the per-day poll pattern should use it; existing Lambdas stay as-is.

**Large opus items remaining:** None. PROD-1 complete (v3.4.0), PROD-2 complete (v3.3.8).

---


---

## 10. CDK / IaC STATE

### cdk/app.py
```python

#!/usr/bin/env python3
"""
Life Platform CDK App — PROD-1: Infrastructure as Code

Stack architecture:
  core        → DynamoDB, S3, SQS DLQ, SNS alerts (imported existing resources)
  ingestion   → 13 ingestion Lambdas + EventBridge rules + IAM roles
  compute     → 5 compute Lambdas + EventBridge rules
  email       → 7 email/digest Lambdas + EventBridge rules
  operational → Operational Lambdas (anomaly, freshness, canary, dlq-consumer, etc.)
  mcp         → MCP Lambda + Function URLs (local + remote)
  web         → CloudFront (3 distributions) + ACM certificates
  monitoring  → CloudWatch alarms + ops dashboard + SLO alarms

Deployment:
  cdk bootstrap aws://205930651321/us-west-2
  cdk deploy LifePlatformCore
  cdk deploy LifePlatformIngestion
  ... etc

To import existing resources (first time only):
  cdk import LifePlatformCore
"""

import aws_cdk as cdk

from stacks.core_stack import CoreStack
from stacks.ingestion_stack import IngestionStack
from stacks.compute_stack import ComputeStack
from stacks.email_stack import EmailStack
# Future stacks — uncomment as implemented:
from stacks.operational_stack import OperationalStack
from stacks.mcp_stack import McpStack
from stacks.web_stack import WebStack
from stacks.monitoring_stack import MonitoringStack

app = cdk.App()

# Read context values
account = app.node.try_get_context("account") or "205930651321"
region = app.node.try_get_context("region") or "us-west-2"

env = cdk.Environment(account=account, region=region)

# ── Core infrastructure (DynamoDB, S3, SQS, SNS) ──
core = CoreStack(app, "LifePlatformCore", env=env)

# ── Future stacks ──
# Each stack receives core.table, core.bucket, core.dlq, core.alerts_topic
# as cross-stack references.
#
ingestion = IngestionStack(app, "LifePlatformIngestion", env=env,
    table=core.table, bucket=core.bucket, dlq=core.dlq,
    alerts_topic=core.alerts_topic)
# ingestion stack wired ✅
#
compute = ComputeStack(app, "LifePlatformCompute", env=env,
    table=core.table, bucket=core.bucket, dlq=core.dlq,
    alerts_topic=core.alerts_topic)
# compute stack wired ✅
#
email = EmailStack(app, "LifePlatformEmail", env=env,
    table=core.table, bucket=core.bucket, dlq=core.dlq,
    alerts_topic=core.alerts_topic)
# email stack wired ✅
#
operational = OperationalStack(app, "LifePlatformOperational", env=env,
    table=core.table, bucket=core.bucket, dlq=core.dlq,
    alerts_topic=core.alerts_topic)
# operational stack wired ✅
#
mcp = McpStack(app, "LifePlatformMcp", env=env,
    table=core.table, bucket=core.bucket)
# mcp stack wired ✅
#
web = WebStack(app, "LifePlatformWeb",
    env=cdk.Environment(account=account, region="us-east-1"))  # CloudFront requires us-east-1
# web stack wired ✅
#
monitoring = MonitoringStack(app, "LifePlatformMonitoring", env=env,
    alerts_topic=core.alerts_topic)
# monitoring stack wired ✅

app.synth()

```


### cdk/stacks/lambda_helpers.py (first 80 lines)
```python

"""
lambda_helpers.py — Shared Lambda construction patterns for CDK stacks.

Provides a helper function that creates a Lambda function with all the
standard Life Platform conventions:
  - Per-function IAM role with explicit least-privilege policies
  - DLQ configured
  - Environment variables (TABLE_NAME, S3_BUCKET, USER_ID)
  - CloudWatch error alarm
  - Handler auto-detection from source file
  - Shared Layer attachment (optional)

v2.0 (v3.4.0): Added custom_policies parameter to replace existing_role_arn.
  CDK now OWNS all IAM roles — no more from_role_arn references.
  Migration: existing_role_arn is DEPRECATED and will be removed in a future version.

Usage in a stack:
    from stacks.lambda_helpers import create_platform_lambda
    from stacks.role_policies import ingestion_policies

    fn = create_platform_lambda(
        self, "WhoopIngestion",
        function_name="whoop-data-ingestion",
        source_file="lambdas/whoop_lambda.py",
        handler="lambda_function.lambda_handler",
        table=core.table,
        bucket=core.bucket,
        dlq=core.dlq,
        custom_policies=ingestion_policies("whoop"),
        schedule="cron(0 14 * * ? *)",
        timeout_seconds=120,
    )
"""

from aws_cdk import (
    Duration,
    aws_lambda as _lambda,
    aws_iam as iam,
    aws_sqs as sqs,
    aws_events as events,
    aws_events_targets as targets,
    aws_cloudwatch as cloudwatch,
    aws_cloudwatch_actions as cw_actions,
    aws_sns as sns,
    aws_dynamodb as dynamodb,
    aws_s3 as s3,
)
from constructs import Construct


def create_platform_lambda(
    scope: Construct,
    id: str,
    function_name: str,
    source_file: str,
    handler: str,
    table: dynamodb.ITable,
    bucket: s3.IBucket,
    dlq: sqs.IQueue = None,
    alerts_topic: sns.ITopic = None,
    alarm_name: str = None,
    secrets: list[str] = None,
    schedule: str = None,
    timeout_seconds: int = 120,
    memory_mb: int = 256,
    environment: dict = None,
    shared_layer: _lambda.ILayerVersion = None,
    additional_layers: list = None,
    # ── Legacy parameter (DEPRECATED — use custom_policies instead) ──
    existing_role_arn: str = None,
    # ── Fine-grained IAM (v2.0) ──
    custom_policies: list[iam.PolicyStatement] = None,
    # ── Legacy broad-permission flags (used when neither existing_role_arn nor custom_policies) ──
    ddb_write: bool = True,
    s3_write: bool = True,
    needs_ses: bool = False,
    ses_domain: str = None,
) -> _lambda.Function:
    """Create a Lambda function with standard Life Platform conventions.


... [TRUNCATED — 157 lines omitted, 237 total]

```


### cdk/stacks/role_policies.py (first 80 lines)
```python

"""
role_policies.py — Centralized IAM policy definitions for all Life Platform Lambdas.

Each function returns a list of iam.PolicyStatement objects that exactly
replicate the existing console-created per-function IAM roles from SEC-1.

Audit source: aws iam get-role-policy on all 37 lambda-* roles (2026-03-09).
Organized by CDK stack: ingestion, compute, email, operational, mcp.

Policy principle: least-privilege per Lambda. No shared roles.
"""

from aws_cdk import aws_iam as iam

# ── Constants ──────────────────────────────────────────────────────────────
ACCT = "205930651321"
REGION = "us-west-2"
TABLE_ARN = f"arn:aws:dynamodb:{REGION}:{ACCT}:table/life-platform"
BUCKET = "matthew-life-platform"
BUCKET_ARN = f"arn:aws:s3:::{BUCKET}"
DLQ_ARN = f"arn:aws:sqs:{REGION}:{ACCT}:life-platform-ingestion-dlq"
KMS_KEY_ARN = f"arn:aws:kms:{REGION}:{ACCT}:key/444438d1-a5e0-43b8-9391-3cd2d70dde4d"
SES_IDENTITY = f"arn:aws:ses:{REGION}:{ACCT}:identity/mattsusername.com"


def _secret_arn(name: str) -> str:
    """Secrets Manager ARN with wildcard suffix for version IDs."""
    return f"arn:aws:secretsmanager:{REGION}:{ACCT}:secret:{name}*"


def _s3(*prefixes: str) -> list[str]:
    """S3 object ARNs for the given key prefixes."""
    return [f"{BUCKET_ARN}/{p}" for p in prefixes]


# ═══════════════════════════════════════════════════════════════════════════
# INGESTION STACK — 15 Lambdas
# Pattern: DDB write, S3 raw/<source>/*, source-specific secret, DLQ
# ═══════════════════════════════════════════════════════════════════════════

def _ingestion_base(
    source: str,
    secret_name: str = None,
    s3_prefix: str = None,
    ddb_actions: list[str] = None,
    extra_secret_actions: list[str] = None,
    extra_s3_read: list[str] = None,
    extra_s3_write: list[str] = None,
    extra_statements: list[iam.PolicyStatement] = None,
    no_s3: bool = False,
    no_secret: bool = False,
) -> list[iam.PolicyStatement]:
    """Build standard ingestion role policies."""
    stmts = []

    # DynamoDB
    actions = ddb_actions or ["dynamodb:PutItem", "dynamodb:GetItem", "dynamodb:UpdateItem", "dynamodb:Query"]
    stmts.append(iam.PolicyStatement(
        sid="DynamoDB",
        actions=actions,
        resources=[TABLE_ARN],
    ))

    # KMS — required for all DDB operations (table is CMK-encrypted)
    stmts.append(iam.PolicyStatement(
        sid="KMS",
        actions=["kms:Decrypt", "kms:GenerateDataKey"],
        resources=[KMS_KEY_ARN],
    ))

    # S3 write (raw data)
    if not no_s3:
        prefix = s3_prefix or f"raw/matthew/{source}/*"
        write_resources = _s3(prefix) + (_s3(*extra_s3_write) if extra_s3_write else [])
        stmts.append(iam.PolicyStatement(
            sid="S3Write",
            actions=["s3:PutObject"],
            resources=write_resources,
        ))


... [TRUNCATED — 686 lines omitted, 766 total]

```


### CDK stack files: compute_stack.py, core_stack.py, email_stack.py, ingestion_stack.py, lambda_helpers.py, mcp_stack.py, monitoring_stack.py, operational_stack.py, role_policies.py, web_stack.py


---

## 11. SOURCE CODE INVENTORY

### lambdas/ (57 .py files, 0 other files)

**Python files:** adaptive_mode_lambda.py, ai_calls.py, ai_output_validator.py, anomaly_detector_lambda.py, apple_health_lambda.py, board_loader.py, brittany_email_lambda.py, canary_lambda.py, character_engine.py, character_sheet_lambda.py, daily_brief_lambda.py, daily_insight_compute_lambda.py, daily_metrics_compute_lambda.py, dashboard_refresh_lambda.py, data_export_lambda.py, data_reconciliation_lambda.py, digest_utils.py, dlq_consumer_lambda.py, dropbox_poll_lambda.py, eightsleep_lambda.py, enrichment_lambda.py, failure_pattern_compute_lambda.py, freshness_checker_lambda.py, garmin_lambda.py, habitify_lambda.py, health_auto_export_lambda.py, html_builder.py, hypothesis_engine_lambda.py, ingestion_framework.py, ingestion_validator.py, insight_email_parser_lambda.py, insight_writer.py, item_size_guard.py, journal_enrichment_lambda.py, key_rotator_lambda.py, macrofactor_lambda.py, mcp_server.py, monday_compass_lambda.py, monthly_digest_lambda.py, notion_lambda.py, nutrition_review_lambda.py, output_writers.py, pip_audit_lambda.py, platform_logger.py, qa_smoke_lambda.py, retry_utils.py, scoring_engine.py, sick_day_checker.py, strava_lambda.py, todoist_lambda.py, weather_handler.py, weather_lambda.py, wednesday_chronicle_lambda.py, weekly_digest_lambda.py, weekly_plate_lambda.py, whoop_lambda.py, withings_lambda.py


**Subdirectories:** __pycache__, buddy, cf-auth, dashboard, requirements


### deploy/ (18 files)

**Files:** MANIFEST.md, SMOKE_TEST_TEMPLATE.sh, audit_alarms.sh, build_layer.sh, cleanup_dead_files.sh, delete_old_ingestion_secrets.sh, delete_orphan_alarms.sh, deploy_lambda.sh, finish_cost_a.sh, generate_review_bundle.py, generate_review_bundle.sh, maint3_archive_deploy.sh, migrate_ingestion_keys.sh, p3_attach_shared_utils_layer.sh, p3_build_garmin_layer.sh, p3_build_shared_utils_layer.sh, post_hygiene_v344.sh, setup_ingestion_keys.sh


### mcp/ (30 modules)

**Modules:** __init__.py, config.py, core.py, handler.py, helpers.py, labs_helpers.py, registry.py, strength_helpers.py, tools_adaptive.py, tools_board.py, tools_cgm.py, tools_character.py, tools_correlation.py, tools_data.py, tools_decisions.py, tools_habits.py, tools_health.py, tools_hypotheses.py, tools_journal.py, tools_labs.py, tools_lifestyle.py, tools_memory.py, tools_nutrition.py, tools_sick_days.py, tools_sleep.py, tools_social.py, tools_strength.py, tools_todoist.py, tools_training.py, warmer.py


---

## 12. KEY SOURCE CODE SAMPLES

### daily_brief_lambda.py — Daily Brief orchestrator — most complex Lambda
```python

"""
Daily Brief Lambda — v2.82.0 (Compute refactor: reads pre-computed metrics from daily-metrics-compute Lambda)
Fires at 10:00am PT daily (18:00 UTC via EventBridge).

v2.2 changes:
  - MacroFactor workouts integration (exercise-level detail in Training Report)
  - Smart Guidance: AI-generated from all signals (replaces static table)
  - TL;DR line: single sentence under day grade
  - Weight: weekly delta callout
  - Sleep architecture: deep % + REM % in scorecard
  - Eight Sleep field name fixes (sleep_efficiency_pct, sleep_duration_hours)
  - Nutrition Report: meal timing in AI prompt
  - 4 AI calls: BoD, Training+Nutrition, Journal Coach, TL;DR+Guidance combined

v2.77.0 extraction:
  - html_builder.py   — build_html, hrv_trend_str, _section_error_html (~1,000 lines)
  - ai_calls.py       — all 4 AI call functions + data summary builders (~380 lines)
  - output_writers.py — write_dashboard_json, write_clinical_json, write_buddy_json,
                        evaluate_rewards, get_protocol_recs, sanitize_for_demo (~700 lines)
  Lambda shrinks from 4,002 → ~1,366 lines of orchestration logic.

Sections (15):
  1.  Day Grade + TL;DR (AI one-liner)
  2.  Yesterday's Scorecard (sleep architecture detail)
  3.  Readiness Signal
  4.  Training Report (exercise-level detail from MacroFactor workouts)
  5.  Nutrition Report (meal timing in AI prompt)
  6.  Habits Deep-Dive
  7.  CGM Spotlight (UPDATED: fasting proxy, hypo flag, 7-day trend)
  8.  Gait & Mobility (NEW: walking speed, step length, asymmetry, double support)
  9.  Habit Streaks
  10. Weight Phase Tracker (weekly delta callout)
  11. Today's Guidance (AI-generated smart guidance)
  12. Journal Pulse
  13. Journal Coach
  14. Board of Directors Insight
  15. Anomaly Alert

Profile-driven: all targets read from DynamoDB PROFILE#v1. No hardcoded constants.
4 AI calls: Board of Directors, Training+Nutrition Coach, Journal Coach, TL;DR+Guidance.

v2.54.0: Board of Directors prompt dynamically built from s3://matthew-life-platform/config/board_of_directors.json
         Falls back to hardcoded _FALLBACK_BOD_PROMPT if S3 config unavailable.
"""

import json
import os
import math
import time
import boto3
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from decimal import Decimal

# -- Configuration from environment variables (with backwards-compatible defaults) --
_REGION    = os.environ.get("AWS_REGION", "us-west-2")
TABLE_NAME = os.environ.get("TABLE_NAME", "life-platform")
S3_BUCKET  = os.environ["S3_BUCKET"]
USER_ID    = os.environ["USER_ID"]
RECIPIENT  = os.environ["EMAIL_RECIPIENT"]
SENDER     = os.environ["EMAIL_SENDER"]
ANTHROPIC_SECRET = os.environ.get("ANTHROPIC_SECRET", "life-platform/api-keys")

USER_PREFIX = f"USER#{USER_ID}#SOURCE#"
PROFILE_PK  = f"USER#{USER_ID}"

# -- AWS clients ---------------------------------------------------------------
dynamodb = boto3.resource("dynamodb", region_name=_REGION)
table    = dynamodb.Table(TABLE_NAME)
ses      = boto3.client("sesv2", region_name=_REGION)
s3       = boto3.client("s3", region_name=_REGION)
secrets  = boto3.client("secretsmanager", region_name=_REGION)

# Board of Directors config loader
try:
    import board_loader
    _HAS_BOARD_LOADER = True
except ImportError:
    _HAS_BOARD_LOADER = False

... [TRUNCATED — 1488 lines omitted, 1568 total]

```


### sick_day_checker.py — Sick day cross-cutting utility
```python

"""
Sick Day Checker — shared Lambda Layer utility.

Provides a lightweight DDB check so all Lambdas can test whether a given
date has been flagged as a sick/rest day without duplicating query logic.

DDB schema:
  pk  = USER#<user_id>#SOURCE#sick_days
  sk  = DATE#YYYY-MM-DD
  fields: date, reason (optional), logged_at, schema_version

Used by:
  character_sheet_lambda      — freeze EMA on sick days
  daily_metrics_compute_lambda — store grade="sick", preserve streaks
  anomaly_detector_lambda      — suppress alert emails
  freshness_checker_lambda     — suppress stale-source alerts
  daily_brief_lambda           — show recovery banner, skip coaching

v1.0.0 — 2026-03-09
"""

from datetime import datetime, timezone
from decimal import Decimal

SICK_DAYS_SOURCE = "sick_days"


def _d2f(obj):
    """Convert Decimal → float recursively."""
    if isinstance(obj, list):    return [_d2f(i) for i in obj]
    if isinstance(obj, dict):    return {k: _d2f(v) for k, v in obj.items()}
    if isinstance(obj, Decimal): return float(obj)
    return obj


def check_sick_day(table, user_id, date_str):
    """Return sick day record dict for *date_str*, or None if not flagged.

    Safe to call from any Lambda — returns None on any error rather than raising.
    """
    pk = f"USER#{user_id}#SOURCE#{SICK_DAYS_SOURCE}"
    sk = f"DATE#{date_str}"
    try:
        resp = table.get_item(Key={"pk": pk, "sk": sk})
        item = resp.get("Item")
        return _d2f(item) if item else None
    except Exception as e:
        print(f"[WARN] sick_day_checker.check_sick_day({date_str}): {e}")
        return None


def get_sick_days_range(table, user_id, start_date, end_date):
    """Return list of sick day record dicts within a date range (inclusive).

    Returns empty list on any error.
    """
    pk = f"USER#{user_id}#SOURCE#{SICK_DAYS_SOURCE}"
    try:
        resp = table.query(
            KeyConditionExpression="pk = :pk AND sk BETWEEN :s AND :e",
            ExpressionAttributeValues={
                ":pk": pk,
                ":s":  f"DATE#{start_date}",
                ":e":  f"DATE#{end_date}",
            },
        )
        return [_d2f(i) for i in resp.get("Items", [])]
    except Exception as e:
        print(f"[WARN] sick_day_checker.get_sick_days_range({start_date}→{end_date}): {e}")
        return []


def write_sick_day(table, user_id, date_str, reason=None):
    """Write a sick day record. Idempotent — safe to call multiple times for the same date."""
    pk = f"USER#{user_id}#SOURCE#{SICK_DAYS_SOURCE}"
    sk = f"DATE#{date_str}"
    item = {
        "pk":             pk,
        "sk":             sk,
        "date":           date_str,

... [TRUNCATED — 14 lines omitted, 94 total]

```


### platform_logger.py — Structured logging module
```python

"""
platform_logger.py — OBS-1: Structured JSON logging for all Life Platform Lambdas.

Shared module. Drop-in replacement for the stdlib `logging` pattern used across
all 37 Lambdas. Every log line becomes a structured JSON object that CloudWatch
Logs Insights can query, filter, and alarm on.

USAGE (replaces `logger = logging.getLogger(); logger.setLevel(logging.INFO)`):

    from platform_logger import get_logger
    logger = get_logger("daily-brief")           # source name = lambda function name
    logger.info("Sending email", subject=subject, grade=grade)
    logger.warning("Stale data", source="whoop", age_hours=4.2)
    logger.error("AI call failed", attempt=3, error=str(e))

    # Structured log emitted to CloudWatch:
    {
      "timestamp": "2026-03-08T18:00:01.234Z",
      "level": "INFO",
      "source": "daily-brief",
      "correlation_id": "daily-brief#2026-03-08",
      "lambda": "daily-brief",
      "message": "Sending email",
      "subject": "Morning Brief | Sun Mar 8 ...",
      "grade": "B+"
    }

CORRELATION ID:
  Set once per Lambda execution via logger.set_date(date_str).
  Pattern: "{source}#{date}" — enables cross-Lambda log grouping in CWL Insights.
  Example query: `filter correlation_id like "2026-03-08"` shows ALL Lambda executions
  for that date.

MIGRATION PATTERN (for Lambdas not yet migrated):
  Old: `logger.info("Sending email: " + subject)`
  New: `logger.info("Sending email", subject=subject)`
  — keyword args become top-level JSON fields (searchable in CWL Insights)

BACKWARD COMPATIBILITY:
  PlatformLogger inherits logging.Logger so existing `logger.info(msg)` calls
  (positional only) continue to work unchanged. Migration can be incremental.

v1.0.0 — 2026-03-08 (OBS-1)
v1.0.1 — 2026-03-10 — *args %s compat for all log methods (Bug B fix)
"""

import json
import logging
import os
import sys
import time
from datetime import datetime, timezone

# ── Constants ──────────────────────────────────────────────────────────────────
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()
_LAMBDA_NAME = os.environ.get("AWS_LAMBDA_FUNCTION_NAME", "unknown")
_LAMBDA_VERSION = os.environ.get("AWS_LAMBDA_FUNCTION_VERSION", "$LATEST")

# Map stdlib level names → integers (for external callers that pass strings)
_LEVEL_MAP = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "WARN": logging.WARNING,
    "ERROR": logging.ERROR,
    "CRITICAL": logging.CRITICAL,
}


class StructuredFormatter(logging.Formatter):
    """Emit each log record as a single-line JSON object.

    Standard fields always present:
      timestamp, level, source, lambda, correlation_id, message

    Additional fields: any keyword arguments passed to the log call
    (stored in `record.extra_fields` by PlatformLogger).
    """

    def format(self, record: logging.LogRecord) -> str:

... [TRUNCATED — 308 lines omitted, 388 total]

```


### ingestion_validator.py — Ingestion validation layer
```python

"""
ingestion_validator.py — DATA-2: Shared ingestion validation layer.

Validates incoming data items BEFORE writing to DynamoDB.
Invalid records are logged and written to S3 `validation-errors/` prefix
for audit. Critical validation failures skip DDB write entirely.

USAGE:

    from ingestion_validator import validate_item, ValidationSeverity

    result = validate_item("whoop", item, date_str="2026-03-08")
    if result.should_skip_ddb:
        logger.error("Skipping DDB write", errors=result.errors)
        result.archive_to_s3(s3_client, bucket)
        return
    if result.warnings:
        logger.warning("Validation warnings", warnings=result.warnings)

    table.put_item(Item=item)  # or safe_put_item()

VALIDATION RULES:

    Each source has:
      - required_fields: list of fields that MUST be present (critical if missing)
      - typed_fields: {field: type} — warns if value fails type check
      - range_checks: {field: (min, max)} — warns if value out of expected range
      - critical_range_checks: {field: (min, max)} — SKIPS write if out of range
      - at_least_one_of: list of fields — warns if ALL are absent

    Severity levels:
      CRITICAL — skip DDB write, archive to S3, log error
      WARNING  — write proceeds, issue logged and archived

SOURCES COVERED (19):
  whoop, garmin, apple_health, macrofactor, macrofactor_workouts, strava,
  eightsleep, withings, habitify, notion, todoist, weather, supplements,
  computed_metrics, character_sheet, adaptive_mode, day_grade, habit_scores,
  computed_insights

v1.0.0 — 2026-03-08 (DATA-2)
"""

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)
REGION = os.environ.get("AWS_REGION", "us-west-2")

# ── Validation result ──────────────────────────────────────────────────────────

@dataclass
class ValidationResult:
    source: str
    date_str: str
    errors: list[str] = field(default_factory=list)     # CRITICAL — skip write
    warnings: list[str] = field(default_factory=list)   # non-blocking

    @property
    def is_valid(self) -> bool:
        return len(self.errors) == 0

    @property
    def should_skip_ddb(self) -> bool:
        return len(self.errors) > 0

    def archive_to_s3(self, s3_client, bucket: str, item: dict):
        """Write the rejected item to S3 validation-errors/ prefix for audit."""
        try:
            ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
            key = f"validation-errors/{self.source}/{self.date_str}/{ts}.json"
            payload = {
                "source": self.source,
                "date": self.date_str,
                "archived_at": datetime.now(timezone.utc).isoformat(),
                "errors": self.errors,

... [TRUNCATED — 446 lines omitted, 526 total]

```


### ai_output_validator.py — AI output safety layer
```python

"""
ai_output_validator.py — AI-3: Post-processing validation for AI coaching output.

Validates AI-generated coaching text AFTER generation, BEFORE delivery.
Catches dangerous recommendations, empty/truncated output, and advice that
conflicts with the user's known health context.

USAGE (in ai_calls.py or any Lambda after receiving AI output):

    from ai_output_validator import validate_ai_output, AIOutputType

    result = validate_ai_output(
        text=bod_insight,
        output_type=AIOutputType.BOD_COACHING,
        health_context={"recovery_score": 18, "tsb": -22},
    )

    if result.blocked:
        logger.error("AI output blocked", reason=result.block_reason)
        return result.safe_fallback   # use fallback text instead

    if result.warnings:
        logger.warning("AI output warnings", warnings=result.warnings)

    final_text = result.sanitized_text   # safe to use

VALIDATION TIERS:

    BLOCK  — output is replaced with safe_fallback. Used for:
             - Empty/None output (Lambda crash protection)
             - Dangerous exercise recs with red recovery (injury risk)
             - Severely dangerous caloric guidance (< 800 kcal)
             - Output clearly truncated mid-sentence

    WARN   — output used as-is, warning logged. Used for:
             - Aggressive training language with borderline recovery
             - High-calorie surplus recommendation (unusual for this user)
             - Generic phrases that suggest context was ignored
             - Correlation presented as causation with low-confidence signal

    PASS   — no issues detected

DISCLAIMER:
    All AI output validated by this module should still include the footer:
    "AI-generated analysis, not medical advice." (AI-1 requirement)
    This module validates logical safety, not medical accuracy.

v1.0.0 — 2026-03-08 (AI-3)
"""

import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

logger = logging.getLogger(__name__)


# ── Output types ───────────────────────────────────────────────────────────────

class AIOutputType(str, Enum):
    BOD_COACHING   = "bod_coaching"      # Board of Directors 2-3 sentence coaching
    TLDR           = "tldr"              # TL;DR one-liner
    GUIDANCE       = "guidance"          # Smart guidance bullet item
    TRAINING_COACH = "training_coach"    # Training coach section
    NUTRITION_COACH = "nutrition_coach"  # Nutrition coach section
    JOURNAL_COACH  = "journal_coach"     # Journal reflection + tactical
    CHRONICLE      = "chronicle"         # Weekly chronicle narrative
    WEEKLY_DIGEST  = "weekly_digest"     # Weekly digest coaching
    MONTHLY_DIGEST = "monthly_digest"    # Monthly digest coaching
    GENERIC        = "generic"           # Unknown — minimal checks only


# ── Validation result ──────────────────────────────────────────────────────────

@dataclass
class AIValidationResult:
    original_text: str
    output_type: AIOutputType

... [TRUNCATED — 417 lines omitted, 497 total]

```


### digest_utils.py — Shared digest utilities
```python

"""
digest_utils.py — Shared utilities for digest Lambdas (v1.0.0)

Extracted from weekly_digest_lambda.py and monthly_digest_lambda.py to eliminate
duplication, fix bugs, and ensure consistent behaviour across all digest cadences.

Consumers:
  - weekly_digest_lambda.py
  - monthly_digest_lambda.py

Contents:
  - Pure scalar helpers: d2f, avg, fmt, fmt_num, safe_float
  - dedup_activities
  - _normalize_whoop_sleep
  - List-based extractors: ex_whoop_from_list, ex_whoop_sleep_from_list, ex_withings_from_list
  - Banister: compute_banister_from_list, compute_banister_from_dict
"""

import math
from datetime import datetime, timedelta, timezone
from decimal import Decimal


# ══════════════════════════════════════════════════════════════════════════════
# PURE SCALAR HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def d2f(obj):
    """Recursively convert DynamoDB Decimal values to float."""
    if isinstance(obj, list):    return [d2f(i) for i in obj]
    if isinstance(obj, dict):    return {k: d2f(v) for k, v in obj.items()}
    if isinstance(obj, Decimal): return float(obj)
    return obj


def avg(vals):
    """Mean of a list, ignoring None values. Returns None for empty input."""
    v = [x for x in vals if x is not None]
    return round(sum(v) / len(v), 1) if v else None


def fmt(val, unit="", dec=1):
    """Format a number with optional unit; returns em-dash for None."""
    return "\u2014" if val is None else f"{round(val, dec)}{unit}"


def fmt_num(val):
    """Format a number with thousands separator; returns em-dash for None."""
    if val is None:
        return "\u2014"
    return "{:,}".format(round(val))


def safe_float(rec, field, default=None):
    """Safely extract a float from a dict record."""
    if rec and field in rec:
        try:
            return float(rec[field])
        except Exception:
            return default
    return default


# ══════════════════════════════════════════════════════════════════════════════
# ACTIVITY DEDUP  (Strava/Garmin duplicate removal)
# ══════════════════════════════════════════════════════════════════════════════

def dedup_activities(activities):
    """Remove duplicate activities within a 15-minute window.

    Keeps the richer record (higher richness score). Records without a parseable
    start_date_local are kept unconditionally. Handles Garmin->Strava auto-sync
    duplicates where the same session appears twice with different metadata.
    """
    if not activities or len(activities) <= 1:
        return activities

    def parse_start(a):
        s = a.get("start_date_local") or a.get("start_date") or ""
        try:

... [TRUNCATED — 195 lines omitted, 275 total]

```


### mcp/handler.py (first 60 lines)
```python

"""
Lambda handler and MCP protocol implementation.

Supports two transport modes:
1. Remote MCP (Streamable HTTP via Function URL) — for claude.ai, mobile, desktop
2. Local bridge (direct Lambda invoke via boto3) — legacy Claude Desktop bridge

The remote transport implements MCP Streamable HTTP (spec 2025-06-18):
- POST / — JSON-RPC request/response
- HEAD / — Protocol version discovery
- GET /  — 405 (no SSE support in Lambda)

OAuth: Minimal auto-approve flow to satisfy Claude's connector requirement.
Security is provided by the unguessable 40-char Lambda Function URL, not OAuth.
"""
import json
import logging
import base64
import uuid
import hmac
import hashlib
import time
import urllib.parse

from mcp.config import logger, __version__
from mcp.core import get_api_key, decimal_to_float
from mcp.registry import TOOLS
from mcp.warmer import nightly_cache_warmer

# ── MCP protocol constants ────────────────────────────────────────────────────
MCP_PROTOCOL_VERSION = "2025-06-18"
MCP_PROTOCOL_VERSION_LEGACY = "2024-11-05"

# Headers included in all remote MCP responses
_MCP_HEADERS = {
    "Content-Type": "application/json",
    "MCP-Protocol-Version": MCP_PROTOCOL_VERSION,
    "Cache-Control": "no-cache",
}


# ── MCP protocol handlers ─────────────────────────────────────────────────────
def handle_initialize(params):
    # Negotiate protocol version — support both current and legacy
    client_version = params.get("protocolVersion", MCP_PROTOCOL_VERSION_LEGACY)
    server_version = (MCP_PROTOCOL_VERSION
                      if client_version >= "2025"
                      else MCP_PROTOCOL_VERSION_LEGACY)

    return {
        "protocolVersion": server_version,
        "capabilities":    {"tools": {}},
        "serverInfo":      {"name": "life-platform", "version": __version__},
    }


def handle_tools_list(_params):
    return {"tools": [t["schema"] for t in TOOLS.values()]}



... [TRUNCATED — 446 lines omitted, 506 total]

```


---

## 13. PREVIOUS REVIEW GRADES


| Dimension | #1 (v2.91) | #2 (v3.1.3) | #3 (v3.3.10) | #4 (v3.4.1) |
|-----------|-----------|-----------|-------------|-------------|
| Architecture | B+ | B+ | A- | A |
| Security | C+ | B+ | B+ | A- |
| Reliability | B- | B+ | B+ | B+ |
| Operability | C+ | B- | B+ | B+ |
| Cost | A | A | A | A |
| Data Quality | B | B+ | B+ | A- |
| AI/Analytics | C+ | B- | B | B |
| Maintainability | C | B- | B | B+ |
| Production Readiness | D+ | C | B- | B |

**Review #4 top 10 remaining items:**
1. Update INCIDENT_LOG with v3.4.0/v3.4.1 incidents (5 entries)
2. Archive 19 one-time deploy/ scripts
3. Delete dead files (weather_lambda.py.archived, freshness_checker.py)
4. Add 3 ADRs (EB rule naming, CoreStack scoping, sick day design)
5. Audit needs_kms=True across role_policies.py
6. Add TTL to failure_pattern_compute records
7. Fix PlatformLogger %s formatting support
8. Update ARCHITECTURE.md header + CDK section
9. Check ingestion_habitify() api-keys secret reference
10. Add "archive deploy/" to session-end checklist


---

## 14. SCHEMA SUMMARY

## Key Structure

| Attribute | Description |
|-----------|-------------|
| `pk` | Partition key — identifies the entity type and owner |
| `sk` | Sort key — enables range queries and versioning |



## Sources

Valid source identifiers: `whoop`, `withings`, `strava`, `todoist`, `apple_health`, `hevy`, `eightsleep`, `chronicling`, `macrofactor`, `macrofactor_workouts`, `garmin`, `habitify`, `notion`, `labs`, `dexa`, `genome`, `supplements`, `weather`, `travel`, `state_of_mind`, `habit_scores`, `character_sheet`, `computed_metrics`, `platform_memory`, `insights`, `decisions`, `hypotheses`, `chronicle`

Note: `hevy` and `chronicling` are historical/archived sources — not actively ingesting. `habit_scores`, `character_sheet`, `computed_metrics`, `platform_memory`, `insights`, `decisions`, and `hypotheses` are derived/computed partitions, not raw ingested data.

Ingestion methods: API polling (scheduled Lambda), S3 file triggers (manual export), **webhook** (Health Auto Export push — also handles BP and State of Mind), **MCP tool write** (supplements), **on-demand fetch + scheduled Lambda** (weather)

---


---

## 15. DOCUMENTATION INVENTORY

**Root docs (21 files):** ARCHITECTURE.md, CHANGELOG.md, CHANGELOG_ARCHIVE.md, CHANGELOG_v341.md, COST_TRACKER.md, DATA_DICTIONARY.md, DECISIONS.md, FEATURES.md, HANDOVER_LATEST.md, INCIDENT_LOG.md, INFRASTRUCTURE.md, INTELLIGENCE_LAYER.md, MCP_TOOL_CATALOG.md, PROJECT_PLAN.md, PROJECT_PLAN_ARCHIVE.md, REVIEW_METHODOLOGY.md, REVIEW_RUNBOOK.md, RUNBOOK.md, SCHEMA.md, SLOs.md, USER_GUIDE.md


**docs/archive/ (14 files):** AUDIT_PROD2_MULTI_USER.md, AVATAR_DESIGN_STRATEGY.md, BOARD_DERIVED_METRICS_PLAN.md, DERIVED_METRICS_PLAN.md, DESIGN_PROD1_CDK.md, DESIGN_SIMP2_INGESTION.md, NOTION_ENRICHMENT_SPEC.md, NOTION_JOURNAL_SPEC.md, SCHEMA_LABS_ADDITION.md, SCOPING_LARGE_OPUS.md, SPEC_CHARACTER_SHEET.md, avatar-design-strategy.md, data-source-audit-2026-02-24.md, wednesday-chronicle-design.md


**docs/audits/ (1 files):** IAM_AUDIT_2026-03-08.md


**docs/design/ (0 files):** 


**docs/rca/ (2 files):** PIR-2026-02-28-ingestion-outage.md, RCA_2026-02-24_apple_health_pipeline.md


**docs/reviews/ (8 files):** REVIEW_2026-03-08.md, REVIEW_2026-03-08_v2.md, REVIEW_2026-03-09.md, REVIEW_2026-03-09_full.md, REVIEW_2026-03-10.md, REVIEW_2026-03-10_full.md, REVIEW_BUNDLE_2026-03-10.md, platform-review-2026-03-05.md



---


*Bundle generated 2026-03-10 by deploy/generate_review_bundle.py*
