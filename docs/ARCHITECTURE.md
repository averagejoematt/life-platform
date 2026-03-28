# Life Platform — Architecture

Last updated: 2026-03-28 (v4.3.0 — 110 tools, 25-module MCP package, 26 data sources, 61 Lambdas, 7 CDK stacks deployed)

---

## Overview

The life platform is a personal health intelligence system built on AWS. It ingests data from nineteen sources (twelve scheduled + one webhook + three manual/periodic + two MCP-managed + one State of Mind via webhook), normalises everything into a single DynamoDB table, and surfaces it to Claude through a Lambda-backed MCP server. The design philosophy is: get data in automatically, store it cheaply, and make it queryable without a data engineering background.

---

## Three-Layer Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  INGEST LAYER                                               │
│  Scheduled Lambdas (EventBridge) + S3 Triggers + Webhooks   │
│  Whoop · Withings · Strava · Eight Sleep · MacroFactor      │
│  Garmin · Apple Health · Habitify · Notion Journal          │
│  Health Auto Export (webhook — CGM/BP/SoM) · Weather        │
│  Supplements (MCP write) · Labs · DEXA · Genome (seeds)     │
└────────────────────────┬────────────────────────────────────┘
                         │ normalised records
┌────────────────────────▼────────────────────────────────────┐
│  STORE LAYER                                                │
│  S3 (raw) + DynamoDB (normalised, single-table)             │
└────────────────────────┬────────────────────────────────────┘
                         │ DynamoDB queries
┌────────────────────────▼────────────────────────────────────┐
│  SERVE LAYER                                                │
│  MCP Server Lambda (95 tools, 768 MB) + Lambda Function URL │
│  ← Claude Desktop + claude.ai + Claude mobile via remote MCP│
│                                                             │
│  COMPUTE LAYER (IC intelligence features)                   │
│  character-sheet-compute · adaptive-mode-compute            │
│  daily-metrics-compute · daily-insight-compute (IC-8)       │
│  hypothesis-engine v1.2.0 (IC-18+IC-19, Sunday 12 PM PT)   │
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
│  averagejoematt.com (12 pages) · CloudFront → S3 /site      │
│  site-api Lambda (us-east-1): /api/ask · /api/board_ask     │
│  /api/verify_subscriber · /api/vitals · /api/journey        │
│  /api/character · /api/timeline · /api/correlations         │
│  dash.averagejoematt.com → S3 /dashboard (Lambda@Edge auth) │
│  blog.averagejoematt.com → S3 /blog (Elena Voss Chronicle)  │
│  buddy.averagejoematt.com → S3 /buddy (Tom accountability)  │
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
| Secrets Manager | Credential store | 10 active secrets: 4 OAuth (`whoop`, `withings`, `strava`, `garmin`) + `eightsleep` + `ai-keys` (Anthropic + MCP) + `ingestion-keys` (Notion/Todoist/Habitify/Dropbox/webhook keys bundle) + `habitify` (dedicated) + `mcp-api-key` + `site-api-ai-key` (R17-04) — **`api-keys` permanently deleted 2026-03-14; `google-calendar` permanently deleted 2026-03-15 (ADR-030); `webhook-key` deleted 2026-03-14** |
| SNS topic | Alert routing | `life-platform-alerts` |
| CloudFront (amj) | CDN (public) | `E3S424OXQZ8NBE` (`d2qlzq81ggequb.cloudfront.net`) → site-api Lambda + S3 `/site`, alias `averagejoematt.com` |
| CloudFront (dash) | CDN + auth | `EM5NPX6NJN095` → S3 `/dashboard`, Lambda@Edge auth, alias `dash.averagejoematt.com` |
| CloudFront (blog) | CDN (public) | `E1JOC1V6E6DDYI` → S3 `/blog`, alias `blog.averagejoematt.com` |
| CloudFront (buddy) | CDN (public) | `ETTJ44FT0Z4GO` → S3 `/buddy`, alias `buddy.averagejoematt.com` |
| ACM Certificate | TLS | `arn:aws:acm:us-east-1:205930651321:certificate/e85e4b63-...` — `averagejoematt.com` (DNS-validated) |
| SES Receipt Rule Set | Inbound email routing | `life-platform-inbound` (active) — rule `insight-capture` routes `insight@aws.mattsusername.com` → S3 |
| CloudWatch | Alarms + logs | **~49 metric alarms**, all Lambdas monitored |
| CDK | Infrastructure as Code | `cdk/` — 8 stacks deployed. CDK owns all 49 Lambda IAM roles + ~50 EventBridge rules. |
| CloudTrail | Audit logging | `life-platform-trail` → S3 |
| AWS Budget | Cost guardrail | $20/mo cap, alerts at 25%/50%/100% |

---

## Ingest Layer

### Scheduled ingestion (EventBridge → Lambda)

Each source has its own dedicated Lambda and IAM role. EventBridge triggers fire daily. All cron expressions use fixed UTC.

**Gap-aware backfill (v2.46.0):** All 6 API-based ingestion Lambdas implement self-healing gap detection. On each run, the Lambda queries DynamoDB for the last N days, identifies missing DATE# records, and fetches only those from the upstream API.

| Source | Lambda | Cron (UTC) | PT (PDT) |
|---|---|---|---|
| Whoop | `whoop-data-ingestion` | `cron(0 14 * * ? *)` | 07:00 AM |
| Garmin | `garmin-data-ingestion` | `cron(0 14 * * ? *)` | 07:00 AM |
| Notion Journal | `notion-journal-ingestion` | `cron(0 14 * * ? *)` | 07:00 AM |
| Withings | `withings-data-ingestion` | `cron(15 14 * * ? *)` | 07:15 AM |
| Habitify | `habitify-data-ingestion` | `cron(15 14 * * ? *)` | 07:15 AM |
| Strava | `strava-data-ingestion` | `cron(30 14 * * ? *)` | 07:30 AM |
| Journal Enrichment | `journal-enrichment` | `cron(30 14 * * ? *)` | 07:30 AM |
| Todoist | `todoist-data-ingestion` | `cron(45 14 * * ? *)` | 07:45 AM |
| Eight Sleep | `eightsleep-data-ingestion` | `cron(0 15 * * ? *)` | 08:00 AM |
| Activity Enrichment | `activity-enrichment` | `cron(30 15 * * ? *)` | 08:30 AM |
| MacroFactor | `macrofactor-data-ingestion` | `cron(0 16 * * ? *)` | 09:00 AM |
| Weather | `weather-data-ingestion` | `cron(45 13 * * ? *)` | 06:45 AM |
| Dropbox Poll | `dropbox-poll` | `rate(30 minutes)` | every 30m |

### Compute + Email Lambdas

| Function | Lambda | Cron (UTC) | PT (PDT) |
|---|---|---|---|
| Daily Insight Compute (IC-8) | `daily-insight-compute` | `cron(20 17 * * ? *)` | 10:20 AM |
| Daily Metrics Compute | `daily-metrics-compute` | `cron(25 17 * * ? *)` | 10:25 AM |
| Adaptive Mode Compute | `adaptive-mode-compute` | `cron(30 17 * * ? *)` | 10:30 AM |
| Character Sheet Compute | `character-sheet-compute` | `cron(35 17 * * ? *)` | 10:35 AM |
| Anomaly Detector | `anomaly-detector` | `cron(5 16 * * ? *)` | 09:05 AM |
| Daily Brief | `daily-brief` | `cron(0 18 * * ? *)` | 11:00 AM |
| Monday Compass | `monday-compass` | `cron(0 15 ? * MON *)` | Mon 08:00 AM |
| Wednesday Chronicle | `wednesday-chronicle` | `cron(0 15 ? * WED *)` | Wed 08:00 AM |
| The Weekly Plate | `weekly-plate` | `cron(0 2 ? * SAT *)` | Fri 07:00 PM |
| Weekly Digest | `weekly-digest` | `cron(0 16 ? * SUN *)` | Sun 09:00 AM |
| Nutrition Review | `nutrition-review` | `cron(0 17 ? * SAT *)` | Sat 10:00 AM |
| Monthly Digest | `monthly-digest` | `cron(0 16 ? * 1#1 *)` | 1st Mon 9:00 AM |
| Hypothesis Engine (IC-18) | `hypothesis-engine` | `cron(0 19 ? * SUN *)` | Sun 12:00 PM |
| Weekly Correlation Compute | `weekly-correlation-compute` | `cron(30 18 ? * SUN *)` | Sun 11:30 AM |

### File-triggered ingestion (S3 → Lambda)

| Source | Lambda | S3 Trigger Path |
|---|---|---|
| MacroFactor | `macrofactor-data-ingestion` | `uploads/macrofactor/*.csv` |
| Apple Health | `apple-health-ingestion` | `imports/apple_health/*.xml` |
| Insight Email | `insight-email-parser` | `raw/inbound_email/*` ObjectCreated |

### Webhook ingestion (API Gateway → Lambda)

| Source | Lambda | Endpoint |
|---|---|---|
| Health Auto Export | `health-auto-export-webhook` | `https://a76xwxt2wa.execute-api.us-west-2.amazonaws.com/ingest` |

### Failure handling

DLQ coverage: all async Lambdas → `life-platform-ingestion-dlq`. CloudWatch: **~49 alarms** total. Alarm actions → SNS `life-platform-alerts`.

Additional safeguards: DLQ Consumer Lambda, Canary Lambda (synthetic health check every 30 min), item size guard.

---

## Store Layer

### DynamoDB — normalised data

Table: `life-platform` (us-west-2) | Single-table | On-demand | Deletion protection | PITR (35-day) | TTL on `ttl`

```
PK: USER#matthew#SOURCE#<source>
SK: DATE#YYYY-MM-DD
```

**Key partitions:** whoop · day_grade · habit_scores · character_sheet · computed_metrics · platform_memory · insights · hypotheses · PROFILE#v1 · CACHE#matthew (TTL 26h)

---

## Serve Layer

### MCP Server

**Lambda:** `life-platform-mcp` | **Tools:** 95 | **Memory:** 768 MB | **Modules:** 31
**Remote MCP:** `https://c5hljblvma4u2xd6wf6oe4clk40unthu.lambda-url.us-west-2.on.aws`
**Auth:** `x-api-key` header check + OAuth 2.1/HMAC Bearer for remote MCP

31-module package — see local project structure below.

Cold start: ~700–800ms. Warm: 23–30ms. Cached tools: <100ms.

### IC Intelligence Features (16 of 31 live)

Compute → store → read pattern. Standalone Lambdas run before Daily Brief, store results to DynamoDB.

**Live:** IC-1 (anomaly), IC-2 (training load), IC-3 (nutrition), IC-6 (CGM correlation), IC-7 (cross-pillar), IC-8 (intent vs execution), IC-15 (insights persistence), IC-16 (progressive context), IC-17 (readiness synthesis), IC-18 (hypothesis engine), IC-19 (N=1 experiments + slow drift + sustained anomaly), IC-23 (Character Sheet), IC-24 (adaptive mode), IC-25 (decisions), IC-29 (metabolic adaptation / deficit sustainability — TDEE divergence tracking, deployed v3.7.67), IC-30 (autonomic balance score — HRV + RHR + RR + sleep quality → 4-quadrant nervous system state, deployed v3.7.67).

**Data-gated next:** IC-4 (failure patterns, ~Apr 18), IC-5 (momentum warning, ~Apr 18), IC-26 (temporal mining, ~May), IC-27 (multi-resolution handoff, ~May).

### Site API Lambda (us-east-1)

**Lambda:** `life-platform-site-api` | **Stack:** LifePlatformWeb | **Region:** us-east-1
**Function URL:** `https://lxhjl2qvq2ystwp47464uhs2jti0hpdcq.lambda-url.us-east-1.on.aws/`
**IAM:** Read-only — `dynamodb:GetItem, Query` + `kms:Decrypt` + `s3:GetObject` on `site/config/*`

**Routes served via CloudFront → site-api:**
- `GET /api/vitals` — weight, HRV, recovery (TTL 300s)
- `GET /api/journey` — weight trajectory, goal date (TTL 3600s)
- `GET /api/character` — pillar scores, level (TTL 900s)
- `GET /api/timeline` — weight history + events
- `GET /api/correlations` — pre-computed correlation pairs
- `GET /api/weight_progress` — 180-day weight series
- `GET /api/experiments` — N=1 experiment list
- `GET /api/current_challenge` — weekly challenge ticker
- `POST /api/ask` — AI Q&A (Haiku 4.5), 3 anon / 20 subscriber q/hr
- `POST /api/board_ask` — 6-persona board AI (Haiku 4.5), 5/hr IP limit
- `GET /api/verify_subscriber?email=` — HMAC token for subscriber gate (24hr)
- `POST /api/subscribe` — email subscriber capture

**Rate limiting:** In-memory sliding window (module-level dicts `_ask_rate_store`, `_board_rate_store`). No DDB writes — role is read-only by design (Yael directive, v3.7.82).

### Email / Intelligence cadence

| Lambda | Time (PDT) | Purpose |
|---|---|---|
| `anomaly-detector` | 9:05 AM daily | 15 metrics, CV-based Z thresholds |
| `daily-brief` | 11:00 AM daily | 18-section brief, 4 Haiku calls |
| `monday-compass` | Mon 8:00 AM | Forward-looking planning + Todoist |
| `wednesday-chronicle` | Wed 8:00 AM | Elena Voss narrative, blog + email |
| `weekly-plate` | Fri 7:00 PM | Food magazine column |
| `weekly-digest` | Sun 9:00 AM | 7-day summary, Board commentary |
| `nutrition-review` | Sat 10:00 AM | Deep Sonnet nutrition analysis |
| `hypothesis-engine` | Sun 12:00 PM | IC-18 hypothesis generation |

---

## IAM Security Model

Each Lambda has a **dedicated, least-privilege IAM role** (49 roles total as of v3.7.80, CDK-managed). No shared roles.

- **Ingestion roles (13):** DDB write, S3 write, Secrets read, SQS DLQ
- **MCP role:** DDB CRUD + S3 `config/*` + `raw/matthew/cgm_readings/*`
- **Email/digest roles (7):** DDB read/write, ai-keys, SES, S3 write
- **Compute roles (5):** DDB read/write, ai-keys
- **Operational roles (14):** scoped per function
- **Site API role:** DDB read-only (`GetItem, Query`), `kms:Decrypt`, S3 `site/config/*`, Secrets read (`site-api-ai-key` only) — **NO PutItem, NO Scan**
- No role has `dynamodb:Scan` or cross-account permissions

---

## Secrets Manager

**9 active secrets** at $0.40/month each = **~$3.60/month**

| Secret | Used By |
|---|---|
| `life-platform/whoop` | Whoop Lambda — OAuth2 tokens |
| `life-platform/withings` | Withings Lambda — OAuth2 tokens |
| `life-platform/strava` | Strava Lambda — OAuth2 tokens |
| `life-platform/garmin` | Garmin Lambda — garth OAuth tokens |
| `life-platform/eightsleep` | Eight Sleep Lambda — username + password |
| `life-platform/ai-keys` | All email/compute/MCP Lambdas — Anthropic API key + MCP bearer |
| `life-platform/ingestion-keys` | Notion, Todoist, Habitify, Dropbox, HAE webhook — COST-B bundle |
| `life-platform/habitify` | Habitify Lambda — dedicated key (ADR-014) |
| `life-platform/mcp-api-key` | MCP Key Rotator — bearer token (90-day auto-rotation) |
| `life-platform/site-api-ai-key` | Site API Lambda — dedicated Anthropic key (R17-04, isolated from main ai-keys) |
| ~~`life-platform/webhook-key`~~ | **DELETED 2026-03-14** |
| ~~`life-platform/google-calendar`~~ | **DELETED 2026-03-15 (ADR-030)** |
| ~~`life-platform/api-keys`~~ | **DELETED 2026-03-14** |

---

## Cost Profile

Target: under $25/month | Current: ~$13/month

| Driver | Monthly Cost |
|---|---|
| Secrets Manager (9 active secrets) | ~$3.60 |
| Lambda invocations (~2,000/mo) | ~$0.50 |
| DynamoDB (on-demand) | ~$1.00 |
| S3 (~2.5 GB + requests) | ~$0.50 |
| CloudFront (4 distributions) | ~$1.50 |
| CloudWatch (49 alarms + logs) | ~$2.00 |
| Anthropic API (Haiku + Sonnet) | ~$4.00 |
| **Total** | **~$13** |

---

## Local Project Structure

```
~/Documents/Claude/life-platform/
  mcp_server.py                   ← MCP Lambda entry point
  mcp_bridge.py                   ← Local MCP adapter (Claude Desktop → Lambda HTTPS)
  mcp/                            ← MCP server package (32 modules)
    handler.py, config.py, utils.py, core.py, helpers.py, warmer.py
    labs_helpers.py, strength_helpers.py, registry.py
    tools_sleep, tools_health, tools_training, tools_nutrition, tools_habits
    tools_cgm, tools_labs, tools_journal, tools_lifestyle, tools_social
    tools_strength, tools_correlation, tools_character, tools_board
    tools_decisions, tools_adaptive, tools_hypotheses, tools_memory
    tools_data, tools_todoist

  lambdas/
    # 13 ingestion Lambdas (whoop, withings, strava, garmin, habitify,
    #   eightsleep, macrofactor, notion, todoist, weather, apple_health,
    #   health_auto_export, dropbox_poll)
    # 2 enrichment (enrichment_lambda, journal_enrichment)
    # 7 email/digest (daily_brief, weekly_digest_v2, monthly_digest,
    #   nutrition_review, wednesday_chronicle, weekly_plate, monday_compass)
    # 5 compute (character_sheet, adaptive_mode, daily_metrics_compute,
    #   daily_insight_compute, hypothesis_engine)
    # 9 operational (anomaly_detector, dashboard_refresh, freshness_checker,
    #   insight_email_parser, data_export, qa_smoke, key_rotator, mcp_server,
    #   site_api_lambda — public web API, us-east-1, CDK LifePlatformWeb)
    board_loader.py               ← Shared: Board of Directors config loader
    ai_calls.py                   ← Shared: AI call utilities
    insight_writer.py             ← Shared: Insights ledger writer
    output_writers.py             ← Shared: S3/DDB output utilities
    scoring_engine.py             ← Shared: Day grade scoring

  site/                           ← 12-page static website (averagejoematt.com)
    index.html                    ← Homepage
    story/, live/, journal/       ← Journey pages
    platform/, character/         ← Technical pages
    ask/, board/                  ← Interactive AI tools
    experiments/, explorer/       ← Data pages
    biology/, about/              ← Context pages
    subscribe.html                ← Email capture
    assets/css/, assets/js/       ← Design system (tokens.css, base.css, reveal.js)

  docs/                           ← All documentation
  deploy/                         ← ~120 deploy scripts
  cdk/                            ← 8 CDK stacks
  tests/                          ← 853+ passing tests, 8 CI linters
  handovers/                      ← Session handover notes
```
