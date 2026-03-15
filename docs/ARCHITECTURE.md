# Life Platform — Architecture

Last updated: 2026-03-15 (v3.7.41 — 89 tools, 31-module MCP package, 20 data sources, 43 Lambdas, 10 secrets, 49 alarms, 8 CDK stacks deployed)

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
│  MCP Server Lambda (89 tools, 768 MB) + Lambda Function URL │
│  ← Claude Desktop + claude.ai + Claude mobile via remote MCP│
│                                                             │
│  COMPUTE LAYER (IC intelligence features)                   │
│  character-sheet-compute · adaptive-mode-compute            │
│  daily-metrics-compute · daily-insight-compute (IC-8)       │
│  hypothesis-engine v1.2.0 (IC-18+IC-19 D3B, Sunday 12 PM PT)                 │
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
| Secrets Manager | Credential store | 11 secrets: 4 OAuth (`whoop`, `withings`, `strava`, `garmin`) + `eightsleep` + `ai-keys` (Anthropic + MCP) + `ingestion-keys` (Notion/Todoist/Habitify/Dropbox/webhook keys bundle) + `habitify` (dedicated) + `webhook-key` + `mcp-api-key` — **`api-keys` permanently deleted 2026-03-14** |
| SNS topic | Alert routing | `life-platform-alerts` |
| CloudFront (dash) | CDN + auth | `EM5NPX6NJN095` (`d14jnhrgfrte42.cloudfront.net`) → S3 `/dashboard`, Lambda@Edge auth (`life-platform-cf-auth`), alias `dash.averagejoematt.com`. **Note (R8-LT6):** Lambda@Edge auth functions are manually managed outside CDK — `web_stack.py` has zero Lambda@Edge references. Intentionally left unmanaged: Lambda@Edge requires us-east-1 deployment which complicates CDK stack boundaries. Document-only; no CDK migration planned. |
| CloudFront (blog) | CDN (public) | `E1JOC1V6E6DDYI` (`d1aufb59hb2r1q.cloudfront.net`) → S3 `/blog`, NO auth, alias `blog.averagejoematt.com` |
| CloudFront (buddy) | CDN (public) | `ETTJ44FT0Z4GO` (`d1empeau04e0eg.cloudfront.net`) → S3 `/buddy`, **NO auth** (intentionally public — Tom's accountability page, no PII), alias `buddy.averagejoematt.com`, PriceClass_100, HTTP/2+3 |
| ACM Certificate | TLS | `arn:aws:acm:us-east-1:205930651321:certificate/8e560416-...` — `dash.averagejoematt.com` (DNS-validated) |
| SES Receipt Rule Set | Inbound email routing | `life-platform-inbound` (active) — rule `insight-capture` routes `insight@aws.mattsusername.com` → S3 |
| CloudWatch | Alarms + logs | **~49 metric alarms**, all Lambdas monitored |
| CDK | Infrastructure as Code | `cdk/` — 8 stacks deployed: **Core** (SQS DLQ + SNS + Layer), Ingestion, Compute, Email, Operational, Mcp, Monitoring, Web. CDK owns all 43 Lambda IAM roles + ~50 EventBridge rules. `cdk/stacks/lambda_helpers.py` uses `Code.from_asset("../lambdas")`. DDB + S3 deliberately unmanaged (stateful). |}
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

**DST note:** All EventBridge Rule crons use fixed UTC — times shift ±1hr at DST boundaries (PDT = UTC-7 Mar–Nov; PST = UTC-8 Nov–Mar). Tables above reflect PDT (UTC-7).

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
| Weekly Correlation Compute (R8-LT9) | `weekly-correlation-compute` | `WeeklyCorrelationComputeRule` | `cron(30 18 ? * SUN *)` | Sun 11:30 AM | CDK-generated role |

**Operational & Email Lambdas:**

| Function | Lambda | EventBridge Rule | Cron (UTC) | PT (PDT) | IAM Role |
|---|---|---|---|---|---|
| Anomaly Detector v2.1 | `anomaly-detector` | `anomaly-detector-daily` | `cron(5 16 * * ? *)` | 09:05 AM | `life-platform-email-role` |
| Cache Warmer (dedicated) | `life-platform-mcp-warmer` | CDK-managed warmer rule | `cron(0 17 * * ? *)` | 10:00 AM | CDK-generated role |
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

**Note:** As of v3.4.0 (PROD-1 CDK), all Lambdas have **CDK-owned** dedicated per-function IAM roles (43 roles, one per Lambda). All policies defined in `cdk/stacks/role_policies.py`. SEC-1 complete — no shared roles remain.

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
| Health Auto Export | `health-auto-export-webhook` | `https://a76xwxt2wa.execute-api.us-west-2.amazonaws.com/ingest` | Bearer token (`life-platform/ingestion-keys` → `health_auto_export_api_key`) |

**Three-tier source filtering (v1.1.0):**
- Tier 1 (Apple-exclusive): steps, active/basal energy, gait metrics, flights, distance, headphone audio, water intake, caffeine
- Tier 2 (cross-device): HR, RHR, HRV, respiratory rate, SpO2 — filtered to Apple Watch/iPhone sources only
- Tier 3 (skip): nutrition (MacroFactor SOT), sleep environment (Eight Sleep SOT), body comp (Withings SOT)
- **Sleep SOT (v2.55.0):** Sleep duration/staging/score/efficiency → Whoop. Eight Sleep → bed environment only.
- **Webhook v1.4.0:** Blood pressure metrics (systolic, diastolic, pulse). Individual readings in S3 `raw/blood_pressure/`.
- **Webhook v1.5.0:** State of Mind detection. Check-ins in S3 `raw/state_of_mind/`, daily aggregates in DynamoDB.

**⚠️ `apple-health-ingestion` (S3 XML trigger) is a separate legacy Lambda — NOT the webhook. Debug webhook issues in `health-auto-export-webhook` logs.**

### Failure handling

DLQ coverage: all async Lambdas → `life-platform-ingestion-dlq` (SQS). Request/response pattern Lambdas (`life-platform-mcp`, `health-auto-export-webhook`) excluded. CloudWatch metric alarms: **~49 total**, all Lambdas monitored. Alarm actions → SNS `life-platform-alerts`. 24-hour evaluation period, `TreatMissingData: notBreaching`.

**Additional failure safeguards (v3.1.3):**
- **DLQ Consumer Lambda** (`dlq-consumer`): Drains `life-platform-ingestion-dlq` on a schedule, logs failed message details to CloudWatch with structured context for triage.
- **Canary Lambda** (`life-platform-canary`): Synthetic health check — writes a test record, reads it back, deletes it. Fires every 30 min. Alarms if roundtrip fails.
- **Item size guard** (`item_size_guard.py`): Intercepts all DDB `put_item` calls in ingestion Lambdas; truncates oversized items, emits `ItemSizeWarning` CloudWatch metric before write.

### OAuth token management

Whoop, Withings, Strava, Garmin: OAuth2 with self-healing refresh tokens. Each Lambda reads secret → calls API → on expiry, refreshes → writes updated credentials back to Secrets Manager. Eight Sleep: username/password JWT, refreshed each invocation. Notion, Todoist, Habitify: static API keys bundled in `life-platform/ingestion-keys` (COST-B pattern — single secret with per-service key fields). Habitify also has a dedicated secret (`life-platform/habitify`) per ADR-014. Dropbox poll and Health Auto Export webhook also read from `ingestion-keys`. See ADR-014 for the dedicated-vs-bundled governing principle.

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

**Lambda:** `life-platform-mcp` | **Tools:** 89 | **Memory:** 768 MB | **Modules:** 31
**Local endpoint:** `https://votqefkra435xwrccmapxxbj6y0jawgn.lambda-url.us-west-2.on.aws/`
**Remote MCP:** `https://c5hljblvma4u2xd6wf6oe4clk40unthu.lambda-url.us-west-2.on.aws` — OAuth 2.1 auto-approve + HMAC Bearer (enables claude.ai + mobile)
**Auth:** `x-api-key` header check; key in `life-platform/ai-keys`
**Protocol:** JSON-RPC 2.0 / MCP spec 2025-06-18

31-module package structure:
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

EventBridge triggers MCP Lambda at 10:00 AM PDT daily (`source: aws.events`). Pre-computes 13 tools → `CACHE#matthew` partition, 26-hour TTL. Runtime: ~90s (13 steps).

Cached tools (SIMP-1 updated, v3.7.18–19): `get_longitudinal_summary` (aggregate year + month), `get_longitudinal_summary` (records), `get_longitudinal_summary` (seasonal), `get_health` (dashboard), `get_health` (risk_profile), `get_health` (trajectory), `get_habits` (dashboard), `get_training` (load), `get_training` (periodization), `get_training` (recommendation), `get_character` (sheet), `get_cgm` (dashboard). Steps 9-13 added v3.7.19.

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
| `weekly-digest` v4.3 | Sun 9:00 AM | 7-day summary, day grade trends, Board commentary, coaching insights. |
| `nutrition-review` v1.1 | Sat 10:00 AM | Deep Saturday nutrition analysis (Sonnet, 3-expert panel). |
| `hypothesis-engine` (IC-18) | Sun 12:00 PM | Scientific method loop — generates + tests health hypotheses from longitudinal data. |

**Monthly:**
| Lambda | Day / Time (PDT) | Purpose |
|---|---|---|
| `monthly-digest` v1.1 | 1st Mon 9:00 AM | Monthly coach's letter, 30-day vs prior-30 deltas, annual goals progress. |

**Board of Directors architecture (v2.57.0):** All email Lambdas load 13 expert personas from `s3://matthew-life-platform/config/board_of_directors.json` via shared `board_loader.py` (5-min cache). Each Lambda has a config-driven builder + hardcoded fallback. Monday Compass selects 3 members dynamically: always Rodriguez (planning/decision fatigue domain) + weakest pillar expert + recovery/overdue-based third.

### IC Intelligence Features (14 of 30 live)

The IC (Intelligence Capability) system implements a compute → store → read pattern. Standalone Lambdas run before the Daily Brief, store pre-computed results to DynamoDB, and downstream consumers (Daily Brief, MCP tools) read without recomputing.

**Live features:** IC-1 (anomaly detection), IC-2 (training load), IC-3 (nutrition tracking), IC-6 (CGM correlation), IC-7 (cross-pillar trade-offs, `ai_calls.py`), IC-8 (intent vs execution gap — `daily-insight-compute`, writes to `platform_memory` partition), IC-15 (insights persistence), IC-16 (progressive context), IC-17 (readiness synthesis), IC-18 (hypothesis engine), IC-19 (N=1 experiments + IC-19 Board spec: slow drift detector, sustained anomaly tracking v2.3.0, hypothesis-experiment bridge), IC-23 (Character Sheet scoring), IC-24 (adaptive mode), IC-25 (decisions module).

**Data-gated next:** IC-4 (failure patterns, ~Apr 18), IC-5 (momentum warning, ~Apr 18), IC-26 (temporal mining, ~May), IC-27 (multi-resolution handoff, ~May).

### Local integration — mcp_bridge.py

`mcp_bridge.py` runs on the MacBook and translates Claude Desktop's stdio MCP protocol into HTTPS calls to the Lambda Function URL. API key embedded in bridge config.

---

## Data Flow Diagram

```
Whoop API
Withings API      →  OAuth Lambda  →  DynamoDB  ←──┐
Strava API                                          │
Garmin API                                          │
                                                    │
Todoist API       →  API Lambda    →  DynamoDB      │
Eight Sleep API                                     │
Habitify API                                        │
Notion API                                          │
                                                    │
MacroFactor CSV ─→  Dropbox poll → S3 ──→ Lambda →  DynamoDB
Apple Health XML →  S3 bucket  ──→  S3-trigger → DynamoDB
                                                    │
Health Auto Export → API Gateway → Webhook → DynamoDB + S3
                                                    │
                              Compute Lambdas (pre-brief)
                              character-sheet · adaptive-mode
                              daily-metrics · daily-insight
                              hypothesis-engine
                                                    │
                               MCP Lambda (89 tools)
                                                    │
                      Lambda Function URL (local) / Remote MCP URL
                                                    │
                      Claude Desktop / claude.ai / Claude mobile
```

---

## IAM Security Model

Each Lambda has a **dedicated, least-privilege IAM role** (43 roles total as of v3.5.0, CDK-managed). No shared roles.

- **Ingestion roles (13 dedicated):** DynamoDB write, S3 write, Secrets Manager read (scoped to own secret), SQS DLQ send
- **MCP role:** DynamoDB `GetItem` + `Query` + `PutItem` + `UpdateItem` + `BatchGetItem`; S3 `GetObject` on `config/*` and `raw/matthew/cgm_readings/*`; `ListBucket` scoped to `raw/matthew/cgm_readings/` prefix; `PutObject` on `config/*` only. (**Note:** previously `BUCKET_ARN/*` — tightened to explicit prefixes v3.7.27, Yael SEC review)
- **Email/digest roles (7 dedicated):** DynamoDB read/write, `life-platform/ai-keys` secret, SES SendEmail scoped to `mattsusername.com`, S3 PutObject on `dashboard/*` and `buddy/*`
- **Compute roles (5 dedicated):** DynamoDB read/write, `life-platform/ai-keys` (IC compute Lambdas that call Anthropic)
- **Operational roles (14 dedicated):** scoped per function (e.g. canary: DDB write+read+delete only; dlq-consumer: SQS ReceiveMessage + DDB write)
- No role has `dynamodb:Scan` or cross-account permissions
- All roles CDK-owned via `role_policies.py` — no manually-created or shared roles remain

---

## Secrets Manager

**10 active secrets** at $0.40/month each = **~$4.00/month**

| Secret | Used By | Contents |
|---|---|---|
| `life-platform/whoop` | Whoop Lambda | OAuth2 access + refresh tokens (auto-updated) |
| `life-platform/withings` | Withings Lambda | OAuth2 tokens (auto-updated) |
| `life-platform/strava` | Strava Lambda | OAuth2 tokens (auto-updated) |
| `life-platform/garmin` | Garmin Lambda | garth OAuth tokens (auto-updated) |
| `life-platform/eightsleep` | Eight Sleep Lambda | Username + password (JWT refreshed each run) |
| `life-platform/ai-keys` | All email/compute/MCP Lambdas | Anthropic API key + MCP bearer token (90-day auto-rotation via `mcp-key-rotator`) |
| `life-platform/ingestion-keys` | Notion, Todoist, Habitify, Dropbox, HAE webhook | COST-B bundle: per-service key fields (`notion_api_key`, `todoist_api_key`, `habitify_api_key`, `dropbox_app_key`, `health_auto_export_api_key`) |
| `life-platform/habitify` | Habitify Lambda | Dedicated Habitify API key (also in `ingestion-keys` — see ADR-014) |
| `life-platform/webhook-key` | *(reserved)* | Dedicated HAE webhook auth key (exists but not yet primary — Lambda reads `ingestion-keys`) |
| `life-platform/mcp-api-key` | MCP Key Rotator Lambda | MCP server bearer token (90-day auto-rotation, consumed by `ai-keys`) |
| `life-platform/google-calendar` | Google Calendar Lambda | OAuth2 refresh_token + client credentials. CMK-encrypted. Auto-refreshed by Lambda. Added v3.7.21. |
| ~~`life-platform/api-keys`~~ | ~~Legacy~~ | ~~**PERMANENTLY DELETED 2026-03-14.**~~ |

---

## Cost Profile

Target: under $25/month | Current: ~$10/month

| Driver | Monthly Cost |
|---|---|
| Secrets Manager (10 active secrets) | ~$4.00 |
| Lambda invocations (~2,000/mo) | ~$0.50 |
| DynamoDB (on-demand, low RCU/WCU) | ~$1.00 |
| S3 (~2.5 GB stored + requests) | ~$0.50 |
| CloudFront (3 distributions) | ~$1.00 |
| CloudWatch (35 alarms + logs) | ~$2.00 |
| Anthropic API (Haiku + Sonnet) | ~$3.00 |
| **Total** | **~$10** |

AWS Budget alerts at $5 (25%), $10 (50%), $20 (100%) → `awsdev@mattsusername.com`.

---

## Local Project Structure

```
~/Documents/Claude/life-platform/
  mcp_server.py                   ← MCP Lambda entry point
  mcp_bridge.py                   ← Local MCP adapter (Claude Desktop stdio → Lambda HTTPS)
  mcp/                            ← MCP server package (31 modules)
    handler.py, config.py, utils.py, core.py, helpers.py, warmer.py
    labs_helpers.py, strength_helpers.py, registry.py
    tools_sleep, tools_health, tools_training, tools_nutrition, tools_habits
    tools_cgm, tools_labs, tools_journal, tools_lifestyle, tools_social
    tools_strength, tools_correlation, tools_character, tools_board
    tools_decisions, tools_adaptive, tools_hypotheses, tools_memory
    tools_data, tools_todoist

  docs/
    ARCHITECTURE.md               ← This file
    SCHEMA.md                     ← DynamoDB schema + SOT domains + metric overlap + data gaps
    PLATFORM_GUIDE.md             ← Feature guide + query examples + troubleshooting
    ONBOARDING.md                 ← Start here — mental models + quick reference
    DATA_FLOW_DIAGRAM.md          ← 7 Mermaid diagrams of system flows
    RUNBOOK.md                    ← Operational procedures + schedule
    CHANGELOG.md                  ← Version history
    PROJECT_PLAN.md               ← Roadmap and backlog
    MCP_TOOL_CATALOG.md           ← All 89 tools with params, cache, deps
    COST_TRACKER.md               ← Budget tracking
    INCIDENT_LOG.md               ← Operational incident history
    HANDOVER_LATEST.md            ← Pointer to most recent handover

  lambdas/
    # 13 ingestion Lambdas (whoop, withings, strava, garmin, habitify,
    #   eightsleep, macrofactor, notion, todoist, weather, apple_health,
    #   health_auto_export, dropbox_poll)
    # 2 enrichment (enrichment_lambda, journal_enrichment)
    # 7 email/digest (daily_brief, weekly_digest_v2, monthly_digest,
    #   nutrition_review, wednesday_chronicle, weekly_plate, monday_compass)
    # 5 compute (character_sheet, adaptive_mode, daily_metrics_compute,
    #   daily_insight_compute, hypothesis_engine)
    # 8 operational (anomaly_detector, dashboard_refresh, freshness_checker,
    #   insight_email_parser, data_export, qa_smoke, key_rotator, mcp_server)
    board_loader.py               ← Shared: Board of Directors config loader (S3, 5-min cache)
    character_engine.py           ← Shared: Character Sheet scoring engine
    ai_calls.py                   ← Shared: AI call utilities (IC-7 cross-pillar)
    insight_writer.py             ← Shared: Insights ledger writer (IC-15)
    html_builder.py               ← Shared: Email HTML builder
    output_writers.py             ← Shared: S3/DDB output utilities
    scoring_engine.py             ← Shared: Day grade scoring

  deploy/                         ← ~120 deploy scripts
  backfill/                       ← Backfill + migration scripts
  patches/                        ← Historical patch scripts
  seeds/                          ← Data seed scripts (labs, genome, DEXA, profile)
  setup/                          ← Auth + infrastructure setup scripts
  tests/                          ← Smoke tests + validation scripts
  config/
    project_pillar_map.json       ← Todoist project → pillar mapping (Monday Compass)
  scripts/                        ← .command shortcuts (deploy, verify, logs, cache)
  handovers/                      ← 55+ session handover notes
  datadrops/                      ← Drop folders (watched by launchd)
```
