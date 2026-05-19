# Life Platform — Architecture

Last updated: 2026-05-19 (v7.21.0 — 128 tools, 35-module MCP package, 19 data sources, 68 Lambdas, 9 secrets, 49 alarms, 8 CDK stacks deployed). 127 MCP tools, 26-module MCP package, 19 data sources, 73 Lambdas in us-west-2 + 4 in us-east-1 = 77 total. 12 active secrets (3 in 30-day soft-delete recovery: notion, dropbox, anthropic-api-key). ~104 CloudWatch alarms. 8 CDK stacks deployed. S3 default encryption AES256 (KMS CMK retained, scheduled for deletion 2026-06-16; ADR-053/054). SIMP-2 framework adopted by 8 of 14 ingestion Lambdas (ADR-056). Coach prediction loop closed end-to-end (ADR-055); `coach-quality-gate` now WIRED — invoked async from `ai_calls.call_coach_brief_v2` after each COACH-V2 generation. Shared layer **v51** (mirrored in `cdk/stacks/constants.py:SHARED_LAYER_VERSION`). 57 ADRs (ADR-001 → ADR-057). Total active CDK-managed IAM roles down by 5 (orphans deleted 2026-05-17: `life-platform-digest-role`, `life-platform-og-image-role`, `measurements-ingestion-role`, `pipeline-health-check-role`, `subscriber-onboarding-role`).

---

## Overview

The life platform is a personal health intelligence system built on AWS. It ingests data from twenty-six sources (thirteen scheduled + one webhook + three manual/periodic + two MCP-managed + one State of Mind via webhook), normalises everything into a single DynamoDB table, and surfaces it to Claude through a Lambda-backed MCP server. The design philosophy is: get data in automatically, store it cheaply, and make it queryable without a data engineering background.

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
│  MCP Server Lambda (127 tools, 768 MB) + Lambda Function URL │
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
│  averagejoematt.com (72 pages) · CloudFront → S3 /site      │
│  site-api Lambda (us-west-2): /api/ask · /api/board_ask     │
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
| Lambda Function URL (remote MCP) | Remote MCP HTTPS endpoint | `https://c5hljblvma4u2xd6wf6oe4clk40unthu.lambda-url.us-west-2.on.aws/` (OAuth 2.1 auto-approve + HMAC Bearer) |
| API Gateway | HTTP endpoint | `health-auto-export-api` (a76xwxt2wa) — webhook ingest |
| Secrets Manager | Credential store | **9 active secrets** at $0.40/month each = **~$3.60/month**
| SNS topic | Alert routing | `life-platform-alerts` |
| CloudFront (amj) | CDN (public) | `E3S424OXQZ8NBE` → site-api Lambda + S3 `/site`, alias `averagejoematt.com` |
| CloudFront (dash) | CDN + auth | `EM5NPX6NJN095` (`d14jnhrgfrte42.cloudfront.net`) → S3 `/dashboard`, Lambda@Edge auth, alias `dash.averagejoematt.com` |
| CloudFront (blog) | CDN (public) | `E1JOC1V6E6DDYI` (`d1aufb59hb2r1q.cloudfront.net`) → S3 `/blog`, alias `blog.averagejoematt.com` |
| CloudFront (buddy) | CDN (public) | `ETTJ44FT0Z4GO` (`d1empeau04e0eg.cloudfront.net`) → S3 `/buddy`, alias `buddy.averagejoematt.com` |
| ACM Certificate | TLS | us-east-1 — `averagejoematt.com` + all subdomains (DNS-validated via Route 53) |
| SES Receipt Rule Set | Inbound email routing | `life-platform-inbound` (active) — rule `insight-capture` routes `insight@aws.mattsusername.com` → S3 |
| SES Configuration Set | Outbound delivery telemetry | `life-platform-emails` wired to `daily-brief`, `weekly-digest`, `monthly-digest`, `partner-weekly-email` |
| CloudWatch | Alarms + logs | **~49 metric alarms**, all Lambdas monitored |
| CDK | Infrastructure as Code | `cdk/` — 8 stacks deployed. CDK owns all Lambda IAM roles + ~50 EventBridge rules. Stacks: `core_stack`, `ingestion_stack`, `email_stack`, `compute_stack`, `mcp_stack`, `operational_stack`, `web_stack`, `monitoring_stack`. |
| CloudTrail | Audit logging | `life-platform-trail` → S3. Data events enabled for `s3://matthew-life-platform/raw/` and `s3://matthew-life-platform/uploads/`. |
| AWS Budget | Cost guardrail | $20/mo cap, alerts at 25%/50%/100% |
| Concurrency quota | Account-level | **10** (default; quota raise request filed 2026-05-19 — AWS Support case 177921309700709) |

---

## Ingest Layer

### Scheduled ingestion (EventBridge → Lambda)

Each source has its own dedicated Lambda and IAM role. EventBridge triggers fire hourly with a 10pm–4am PST maintenance window. All cron expressions use fixed UTC.

**Gap-aware backfill (v2.46.0):** All API-based ingestion Lambdas implement self-healing gap detection. On each run, the Lambda queries DynamoDB for the last N days (including today), identifies missing DATE# records, and fetches only those from the upstream API. Cost is ~$0/month — Lambdas short-circuit in <50ms when no new data exists.

**Schedule:** Hourly during active hours (4am–10pm PST) for most sources. Exceptions: Garmin at 4x daily (OAuth rate limits), Weather + Todoist at 2x daily (COST-OPT). Maintenance window: 10pm–4am PST (UTC 6–11 skipped).

**Shared Lambda Layer:** **v51** — published 2026-05-19 (V2 follow-up: wires `coach-quality-gate` async invoke after each COACH-V2 generation in `ai_calls.call_coach_brief_v2`). Includes `ai_calls.py`, `retry_utils.py`, `board_loader.py`, `output_writers.py`, `scoring_engine.py`, `secret_cache.py`, `intelligence_common.py` (P5.8 staleness signals in `build_coach_preamble`), `ingestion_framework.py` (SIMP-2 — see ADR-056), `auth_breaker.py`, `http_retry.py`, `rate_limiter.py`, `request_validator.py`, `compute_metadata.py`, `numeric.py`, `character_engine.py`, `html_builder.py`, `ai_output_validator.py`, `platform_logger.py`, `ingestion_validator.py`, `item_size_guard.py`, `digest_utils.py`, `sick_day_checker.py`, `site_writer.py`, `insight_writer.py`. **24 modules total** (`email_framework.py` DELETED in V2 cleanup — zero importers; the 7 email Lambdas were too divergent for a single framework). Rebuild with `bash deploy/build_layer.sh`. Source of truth for version: `cdk/stacks/constants.py:SHARED_LAYER_VERSION`. **Distribution:** 1 Lambda on v51, 56 on v50, 15 with no layer attached (Edge functions, webhook, freshness, dlq-consumer, etc.). Bulk v50→v51 bump deferred; only Lambdas re-deployed today are on v51.

**Secret caching (COST-OPT-1):** 15-min in-memory TTL cache via `secret_cache.py` in shared layer. Reduces Secrets Manager API calls ~90% across 12 active Lambdas.

**Prompt caching (COST-OPT-2, ADR-049):** Both `ai_calls.py` and `retry_utils.py` auto-wrap system messages as cached content blocks (`anthropic-beta: prompt-caching-2024-07-31`). 90% discount on repeated system prompt tokens. CloudWatch metrics: `AnthropicCacheWriteTokens`, `AnthropicCacheReadTokens`. Model tiering: structured/templated tasks use Haiku (`AI_MODEL` env var), narrative content stays on Sonnet. All model assignments are env-var configurable for instant rollback.

| Source | Lambda | Schedule | Type |
|---|---|---|---|
| Whoop | `whoop-data-ingestion` | Hourly (active hours) | API pull |
| Garmin | `garmin-data-ingestion` | 4x daily (cron 0 0,6,14,22) | API pull |
| Eight Sleep | `eightsleep-data-ingestion` | Hourly (active hours) | API pull |
| Withings | `withings-data-ingestion` | Hourly (active hours) | API pull |
| Habitify | `habitify-data-ingestion` | Hourly (active hours) | API pull |
| Strava | `strava-data-ingestion` | Hourly (active hours) | API pull |
| Todoist | `todoist-data-ingestion` | 2x daily | API pull |
| Notion Journal | `notion-journal-ingestion` | Hourly (active hours) | API pull |
| Weather | `weather-data-ingestion` | 2x daily | API pull |
| MacroFactor | `macrofactor-data-ingestion` | S3 trigger (Dropbox CSV) | File upload |
| Dropbox Poll | `dropbox-poll` | `rate(30 minutes)` | File poll |
| Journal Enrichment | `journal-enrichment` | Hourly | Compute |
| Activity Enrichment | `activity-enrichment` | Hourly | Compute |
| Apple Health (CGM, water, BP, SOM) | `health-auto-export-webhook` | Near real-time (webhook) | HAE push |

> **SIMP-2 cohort (8 of 14 ingestion Lambdas, ADR-056):** `whoop`, `garmin`, `strava`, `withings`, `eightsleep`, `habitify`, `todoist`, `weather`. All `import from ingestion_framework`. The 6 pattern-exempt sources are: `notion`, `macrofactor`, `apple_health`, `dropbox_poll`, `food_delivery`, `health_auto_export` (now `measurements_ingestion`).
>
> **Lambda renames + deletions in V2 cleanup (2026-05-17/19):** `weather_handler.py` → `weather_lambda.py`. `tools_calendar.py` DELETED (ADR-030 retired, Google Calendar). `podcast_scanner_lambda.py` DELETED (no AWS counterpart). `email_framework.py` DELETED from shared layer.

### Compute + Email Lambdas

| Function | Lambda | Cron (UTC) | PT (PDT) |
|---|---|---|---|
| Daily Insight Compute (IC-8) | `daily-insight-compute` | `cron(20 17 * * ? *)` | 10:20 AM |
| Daily Metrics Compute | `daily-metrics-compute` | `cron(25 17 * * ? *)` | 10:25 AM |
| Adaptive Mode Compute | `adaptive-mode-compute` | `cron(30 17 * * ? *)` | 10:30 AM |
| Character Sheet Compute | `character-sheet-compute` | `cron(35 17 * * ? *)` | 10:35 AM |
| Anomaly Detector | `anomaly-detector` | `cron(5 15 * * ? *)` | 08:05 AM |
| Daily Brief | `daily-brief` | `cron(0 17 * * ? *)` | 10:00 AM |
| Monday Compass | `monday-compass` | `cron(0 15 ? * MON *)` | Mon 08:00 AM |
| Wednesday Chronicle | `wednesday-chronicle` | `cron(0 15 ? * WED *)` | Wed 08:00 AM |
| The Weekly Plate | `weekly-plate` | `cron(0 2 ? * SAT *)` | Fri 07:00 PM |
| Weekly Digest | `weekly-digest` | `cron(0 16 ? * SUN *)` | Sun 09:00 AM |
| Nutrition Review | `nutrition-review` | `cron(0 17 ? * SAT *)` | Sat 10:00 AM |
| Monthly Digest | `monthly-digest` | `cron(0 16 ? * 1#1 *)` | 1st Mon 9:00 AM |
| Hypothesis Engine (IC-18) | `hypothesis-engine` | `cron(0 19 ? * SUN *)` | Sun 12:00 PM |
| Weekly Correlation Compute | `weekly-correlation-compute` | `cron(30 18 ? * SUN *)` | Sun 11:30 AM |
| Weekly Signal (PB-06) | `weekly-signal` | `cron(30 16 ? * SUN *)` | Sun 09:30 AM |

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

DLQ coverage: all async Lambdas → `life-platform-ingestion-dlq`. CloudWatch: **~104 alarms** total. Alarm actions → SNS `life-platform-alerts`.

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

**Lambda:** `life-platform-mcp` | **Tools:** 127 | **Memory:** 768 MB | **Runtime:** python3.12 | **Modules:** 26 (`mcp/tools_*.py` + helpers)
**Remote MCP:** `https://c5hljblvma4u2xd6wf6oe4clk40unthu.lambda-url.us-west-2.on.aws/`
**Auth:** OAuth 2.1 auto-approve + HMAC Bearer (remote). Source of truth for tool count: `grep -E '^\s*"name":\s*"[a-z_]+"' mcp/registry.py | wc -l`.

Cold start: ~700–800ms. Warm: 23–30ms. Cached tools: <100ms.

### IC Intelligence Features (16 of 31 live)

Compute → store → read pattern. Standalone Lambdas run before Daily Brief, store results to DynamoDB.

**Live:** IC-1 (anomaly), IC-2 (training load), IC-3 (nutrition), IC-6 (CGM correlation), IC-7 (cross-pillar), IC-8 (intent vs execution), IC-15 (insights persistence), IC-16 (progressive context), IC-17 (readiness synthesis), IC-18 (hypothesis engine), IC-19 (N=1 experiments + slow drift + sustained anomaly), IC-23 (Character Sheet), IC-24 (adaptive mode), IC-25 (decisions), IC-29 (metabolic adaptation / deficit sustainability — TDEE divergence tracking, deployed v3.7.67), IC-30 (autonomic balance score — HRV + RHR + RR + sleep quality → 4-quadrant nervous system state, deployed v3.7.67).

**Data-gated next:** IC-4 (failure patterns, ~Apr 18), IC-5 (momentum warning, ~Apr 18), IC-26 (temporal mining, ~May), IC-27 (multi-resolution handoff, ~May).

### Site API Lambda (us-west-2)

**Lambda:** `life-platform-site-api` | **Stack:** LifePlatformOperational | **Region:** us-west-2 (R17-09 migration)
**Function URL:** Routed through CloudFront (E3S424OXQZ8NBE). Lambda confirmed in us-west-2 (verified via AWS CLI 2026-03-30).
**IAM:** Primarily read-only — `dynamodb:GetItem, Query, PutItem` + `kms:Decrypt` + `s3:GetObject` on `site/config/*`. Limited writes for interactive features (votes, follows, checkins).

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

**Rate limiting:** In-memory sliding window (module-level dicts `_ask_rate_store`, `_board_rate_store`). Vote/follow rate limits use DynamoDB atomic counters with TTL. Role is primarily read-only with limited writes for interactive features (votes, follows, checkins).

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

### Coach Intelligence Layer (v6.0.0)

Eight domain-specific AI coaches generate daily analyses through a multi-stage pipeline. Each coach has a persistent voice, relationship state, and confidence model stored in DynamoDB. The coach pipeline replaces the legacy `ai_expert_analyzer_lambda.py` (deprecated).

**Coaches (8):**

| Coach ID | Name | Domain |
|----------|------|--------|
| `sleep_coach` | Dr. Lisa Park | Sleep & circadian rhythm |
| `nutrition_coach` | Dr. Marcus Webb | Nutrition & metabolism |
| `training_coach` | Dr. Sarah Chen | Training & exercise |
| `mind_coach` | Dr. Nathan Reeves | Mental health & mindfulness |
| `physical_coach` | Dr. Victor Reyes | Physical health & body composition |
| `glucose_coach` | Dr. Amara Patel | Glucose regulation & CGM |
| `labs_coach` | Dr. James Okafor | Lab biomarkers & blood work |
| `explorer_coach` | Dr. Henning Brandt | Cross-domain patterns & experiments |

**Pipeline Lambdas (8):**

| Function | Lambda | Purpose |
|----------|--------|---------|
| Computation Engine | `coach-computation-engine` | EWMA metrics, seasonal adjustments, anomaly detection per coach domain |
| Narrative Orchestrator | `coach-narrative-orchestrator` | Generates coach prose with voice spec, thread continuity, and epistemological framing |
| State Updater | `coach-state-updater` | Updates relationship state, confidence scores, and learning records |
| Ensemble Digest | `coach-ensemble-digest` | Cross-coach synthesis, disagreement detection, influence graph |
| Prediction Evaluator | `coach-prediction-evaluator` | Scores past predictions, calibrates confidence |
| History Summarizer | `coach-history-summarizer` | Compresses old threads into COMPRESSED#latest |
| Quality Gate | `coach-quality-gate` | **WIRED** as of v51 (2026-05-19) — invoked async from `ai_calls.call_coach_brief_v2` after each COACH-V2 generation. Validates output quality (hallucination, voice drift, repetition) before downstream writes. |
| Observatory Renderer | `coach-observatory-renderer` | Renders coach analysis for /api/coach_analysis endpoint (replaces ai_expert_analyzer) |

**Pipeline flow:** Computation Engine -> Narrative Orchestrator -> Quality Gate -> State Updater -> (async) Ensemble Digest + Prediction Evaluator + History Summarizer. Results stored to `COACH#` and `ENSEMBLE#` DynamoDB partitions and served via `/api/coach_analysis`.

**Observatory integration:** `observatory-v3.js` calls `/api/coach_analysis?coach=<id>` first, with automatic fallback to legacy `/api/ai_analysis?expert=<key>` if the new endpoint is unavailable.

**S3 config:** Voice specifications at `config/coaches/*.json` (8 files), influence graph at `config/coaches/influence_graph.json`, computation params at `config/computation/ewma_params.json` + `config/computation/seasonal_adjustments.json`, narrative arcs at `config/narrative/arc_definitions.json`.

**Deprecated:** `ai_expert_analyzer_lambda.py` — replaced by `coach-observatory-renderer`. Legacy `/api/ai_analysis` endpoint still functional as fallback.

---

## IAM Security Model

Each Lambda has a **dedicated, least-privilege IAM role**, all CDK-managed. No shared roles.

**V2 cleanup (2026-05-17):** 5 orphan roles deleted (had no Lambda attached):
- `life-platform-digest-role`
- `life-platform-og-image-role`
- `measurements-ingestion-role`
- `pipeline-health-check-role`
- `subscriber-onboarding-role`

Active role categories (approx counts):
- **Ingestion roles (14):** DDB write, S3 write, Secrets read, SQS DLQ
- **MCP role:** DDB CRUD + S3 `config/*` + `raw/matthew/cgm_readings/*` + `life-platform/todoist` read
- **Email/digest roles (7):** DDB read/write, ai-keys, SES, S3 write
- **Compute roles (5–7):** DDB read/write, ai-keys
- **Coach Intelligence roles (8):** DDB read/write on COACH#/ENSEMBLE#/NARRATIVE# partitions, S3 read on config/coaches/*, ai-keys
- **Operational roles (14+):** scoped per function
- **Site API role:** DDB primarily read-only (`GetItem, Query`) + limited `PutItem` for interactive features (votes, follows, checkins), `kms:Decrypt`, S3 `site/config/*`, Secrets read (`site-api-ai-key` only) — **NO Scan**
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
| `life-platform/eightsleep-client` | Eight Sleep Lambda — client credential alongside user creds |
| `life-platform/ai-keys` | 24 Lambdas — Anthropic API key (main pool) |
| `life-platform/ingestion-keys` | Notion, Todoist, Habitify, Dropbox, HAE webhook — COST-B bundle (now sole source for Notion + Dropbox after V2 dedicated-secret deletion) |
| `life-platform/habitify` | Habitify Lambda — dedicated key (ADR-014) |
| `life-platform/todoist` | MCP write tools — Todoist API token (TD-23, added to MCP IAM 2026-05-02) |
| `life-platform/mcp-api-key` | MCP Key Rotator — bearer token (90-day auto-rotation) |
| `life-platform/site-api-ai-key` | Site API Lambda — dedicated Anthropic key (R17-04, isolated from main ai-keys) |
| ~~`life-platform/notion`~~ | **SOFT-DELETED 2026-05-17** (30-day recovery; consumer migrated to `ingestion-keys`) |
| ~~`life-platform/dropbox`~~ | **SOFT-DELETED 2026-05-17** (30-day recovery; consumer migrated to `ingestion-keys`) |
| ~~`life-platform/anthropic-api-key`~~ | **SOFT-DELETED 2026-05-16** (orphan, no consumer in source) |
| ~~`life-platform/webhook-key`~~ | **HARD-DELETED 2026-03-14** |
| ~~`life-platform/google-calendar`~~ | **HARD-DELETED 2026-03-15 (ADR-030)** |
| ~~`life-platform/api-keys`~~ | **HARD-DELETED 2026-03-14** |

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
| CloudWatch (~104 alarms + logs) | ~$2.50 |
| Anthropic API (Haiku + Sonnet, with prompt caching — ADR-049) | ~$8-12 |
| **Total** | **~$18-23** |

---

## Local Project Structure

```
~/Documents/Claude/life-platform/
  mcp_server.py                   ← MCP Lambda entry point
  mcp_bridge.py                   ← Local MCP adapter (Claude Desktop → Lambda HTTPS)
  mcp/                            ← MCP server package (26 tool modules + helpers)
    handler.py, config.py, utils.py, core.py, helpers.py, labs_helpers.py
    strength_helpers.py, registry.py, warmer.py
    tools_sleep, tools_health, tools_training, tools_nutrition, tools_habits
    tools_cgm, tools_labs, tools_journal, tools_lifestyle, tools_social
    tools_strength, tools_correlation, tools_character, tools_board
    tools_decisions, tools_adaptive, tools_hypotheses, tools_memory
    tools_data, tools_todoist, tools_protocols, tools_challenges,
    tools_sick_days, tools_food_delivery, tools_measurements,
    tools_coach_intelligence
    # tools_calendar.py DELETED V2 (ADR-030 retired Google Calendar)

  lambdas/
    # 16 ingestion (whoop, withings, strava, garmin, habitify,
    #   eightsleep, macrofactor, notion, todoist, weather, apple_health,
    #   health_auto_export, dropbox_poll, food_delivery, measurements,
    #   journal_enrichment, activity_enrichment)
    # 11 email/digest (daily_brief, weekly_digest, monthly_digest,
    #   nutrition_review, wednesday_chronicle, weekly_plate, monday_compass,
    #   anomaly_detector, evening_nudge, chronicle_email_sender,
    #   subscriber_onboarding)
    # 12 compute (character_sheet, adaptive_mode, daily_metrics_compute,
    #   daily_insight_compute, hypothesis_engine, weekly_correlation_compute,
    #   acwr_compute, sleep_reconciler, circadian_compliance,
    #   ai_expert_analyzer [deprecated], journal_analyzer, field_notes)
    # 8 coach intelligence (coach_computation_engine, coach_narrative_orchestrator,
    #   coach_state_updater, coach_ensemble_digest, coach_prediction_evaluator,
    #   coach_history_summarizer, coach_quality_gate, coach_observatory_renderer)
    # 21 operational (freshness_checker, dashboard_refresh, data_export,
    #   qa_smoke, key_rotator, mcp_server, insight_email_parser,
    #   site_api_lambda — public web API, us-west-2,
    #   site_stats_refresh, challenge_generator, og_image_generator,
    #   email_subscriber, pipeline_health_check, chronicle_approve,
    #   canary, dlq_consumer, data_reconciliation, pip_audit,
    #   partner_email, mcp_warmer)
    # 2 Lambda@Edge (cf-auth, buddy-auth)
    board_loader.py               ← Shared: Board of Directors config loader
    ai_calls.py                   ← Shared: AI call utilities (prompt caching, model selection)
    retry_utils.py                ← Shared: Anthropic retry + caching for bundled Lambdas
    insight_writer.py             ← Shared: Insights ledger writer
    output_writers.py             ← Shared: S3/DDB output utilities
    scoring_engine.py             ← Shared: Day grade scoring
    secret_cache.py               ← Shared: 15-min TTL secret cache (COST-OPT)
    site_writer.py                ← Shared: Public stats S3 writer

  site/                           ← static website (averagejoematt.com, ~72 pages)
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
  tests/                          ← 1075+ passing tests, 8 CI linters
  handovers/                      ← Session handover notes
```

---

**Verified:** 2026-05-19 — full audit (V2 audit + follow-up). Lambda counts via `aws lambda list-functions`; layer version via `aws lambda list-layer-versions` and `cdk/stacks/constants.py:37`; MCP tool count via `grep -E '^\s*"name":' mcp/registry.py | wc -l`; SIMP-2 cohort via `grep -l 'from ingestion_framework import' lambdas/*_lambda.py`; alarm count via `aws cloudwatch describe-alarms`; secret list via `aws secretsmanager list-secrets`.
