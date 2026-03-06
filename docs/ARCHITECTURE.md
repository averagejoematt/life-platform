# Life Platform — Architecture

Last updated: 2026-03-05 (v2.72.0 — 120 tools, 25-module MCP package, 19 data sources, 28 Lambdas, 20/22 DLQ coverage, web dashboard + blog + buddy CloudFront, Wednesday Chronicle + Character Sheet (all 4 phases), gap-aware backfill, habit intelligence, remote MCP live, sleep SOT split Whoop/Eight Sleep, Board of Directors centralization + Lambda refactor, activity dedup WHOOP+Garmin, day grade regrade mode, The Weekly Plate, Dashboard Refresh Lambda, Supplement Bridge, Social & Behavioral tools, State of Mind, Biological Age, Metabolic Health Score, Food Response Database, Defense Mechanism Detector, Data Export)

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
│  Health Auto Export (webhook — CGM/Dexcom Stelo, BP, SoM)   │
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
│  MCP Server Lambda (120 tools, 1024 MB) + Lambda Function URL│
│  ← Claude Desktop connects here via mcp_bridge.py          │
│                                                             │
│  EMAIL LAYER                                                │
│  daily-brief (10:00am) · weekly-digest (Sun 8:30am)         │
│  monthly-digest (1st Mon 8am) · anomaly-detector (8:05am)   │
│  freshness-checker (9:45am) · insight-email-parser (S3 trig)│
│  nutrition-review (Sat 9am) · chronicle (Wed 7am)           │
│  weekly-plate (Fri 6pm) · dashboard-refresh (2pm+6pm)       │
│                                                             │
│  WEB LAYER (v2.39.0)                                        │
│  CloudFront → S3 static website (OriginPath /dashboard)     │
│  index.html (daily) + clinical.html + data/clinical.json    │
│  Daily Brief writes data.json · Weekly Digest writes         │
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
| Lambda Function URL | MCP HTTPS endpoint | `https://votqefkra435xwrccmapxxbj6y0jawgn.lambda-url.us-west-2.on.aws/` (AuthType NONE — auth handled in Lambda via API key header) |
| API Gateway | HTTP endpoint | `health-auto-export-api` (a76xwxt2wa) — webhook ingest |
| Secrets Manager | Credential store | `life-platform/*` (12 secrets) |
| SNS topic | Alert routing | `life-platform-alerts` |
| CloudFront (dash) | CDN + auth | `EM5NPX6NJN095` (`d14jnhrgfrte42.cloudfront.net`) → S3 `/dashboard`, Lambda@Edge auth (`life-platform-cf-auth`), alias `dash.averagejoematt.com` |
| CloudFront (blog) | CDN (public) | `E1JOC1V6E6DDYI` (`d1aufb59hb2r1q.cloudfront.net`) → S3 `/blog`, NO auth, alias `blog.averagejoematt.com` |
| CloudFront (buddy) | CDN + auth | `ETTJ44FT0Z4GO` (`d1empeau04e0eg.cloudfront.net`) → S3 `/buddy`, Lambda@Edge auth (`life-platform-buddy-auth`), alias `buddy.averagejoematt.com`, PriceClass_100, HTTP/2+3 |
| ACM Certificate | TLS | `arn:aws:acm:us-east-1:205930651321:certificate/8e560416-...` — `dash.averagejoematt.com` (DNS-validated) |
| SES Receipt Rule Set | Inbound email routing | `life-platform-inbound` (active) — rule `insight-capture` routes `insight@aws.mattsusername.com` → S3 |
| CloudWatch | Alarms + logs | 22 metric alarms (no composite), 21 log groups |
| CloudTrail | Audit logging | `life-platform-trail` → S3 |
| AWS Budget | Cost guardrail | $20/mo cap, alerts at 25%/50%/100% |

---

## Ingest Layer

### Scheduled ingestion (EventBridge → Lambda)

Each source has its own dedicated Lambda and IAM role. EventBridge triggers fire daily. All cron expressions use fixed UTC — **PT times shift by 1 hour when DST changes**.

**Gap-aware backfill (v2.46.0):** All 6 API-based ingestion Lambdas (Garmin, Whoop, Eight Sleep, Strava, Withings, Habitify) implement self-healing gap detection. On each scheduled run, the Lambda queries DynamoDB for the last N days (default 7, configurable via `LOOKBACK_DAYS` env var), identifies missing DATE# records, and fetches only those from the upstream API. Normal runs with no gaps cost 1 DynamoDB query and 0 extra API calls. Rate-limit pacing (0.5–1s) between gap-day fetches prevents upstream throttling. The pattern is self-bootstrapping — existing records are the reference point, no last-sync marker needed. Sources not at risk (Apple Health webhook, MacroFactor Dropbox polling, Notion, Weather, Todoist) do not need gap detection.

| Source | Lambda | EventBridge Rule | Cron (UTC) | PT (PST) | IAM Role |
|---|---|---|---|---|---|
| Whoop | `whoop-data-ingestion` | `whoop-daily-ingestion` | `cron(0 14 * * ? *)` | 06:00 AM | `lambda-whoop-role` |
| Garmin | `garmin-data-ingestion` | `garmin-daily-ingestion` | `cron(0 14 * * ? *)` | 06:00 AM | `lambda-garmin-ingestion-role` |
| Notion Journal | `notion-journal-ingestion` | `notion-daily-ingest` | `cron(0 14 * * ? *)` | 06:00 AM | `lambda-notion-ingestion-role` |
| Withings | `withings-data-ingestion` | `withings-daily-ingestion` | `cron(15 14 * * ? *)` | 06:15 AM | `lambda-withings-role` |
| Habitify | `habitify-data-ingestion` | `habitify-daily-ingest` | `cron(15 14 * * ? *)` | 06:15 AM | `lambda-habitify-ingestion-role` |
| Strava | `strava-data-ingestion` | `strava-daily-ingestion` | `cron(30 14 * * ? *)` | 06:30 AM | `lambda-strava-role` |
| Journal Enrichment | `journal-enrichment` | `journal-enrichment-daily` | `cron(30 14 * * ? *)` | 06:30 AM | `lambda-journal-enrichment-role` |
| Todoist | `todoist-data-ingestion` | `todoist-daily-ingestion` | `cron(45 14 * * ? *)` | 06:45 AM | `lambda-todoist-role` |
| Eight Sleep | `eightsleep-data-ingestion` | `eightsleep-daily-ingestion` | `cron(0 15 * * ? *)` | 07:00 AM | `lambda-eightsleep-role` |
| Activity Enrichment | `activity-enrichment` | `activity-enrichment-nightly` | `cron(30 15 * * ? *)` | 07:30 AM | `lambda-enrichment-role` |
| MacroFactor | `macrofactor-data-ingestion` | `macrofactor-daily-ingestion` | `cron(0 16 * * ? *)` | 08:00 AM | `lambda-macrofactor-role` |
| Weather | `weather-data-ingestion` | `weather-daily-ingestion` | `cron(45 13 * * ? *)` | 05:45 AM | `lambda-weather-role` |
| Dropbox Poll | `dropbox-poll` | `dropbox-poll-schedule` | `rate(30 minutes)` | every 30m | `lambda-dropbox-poll-role` |

### Operational Lambdas (EventBridge → Lambda)

These are not data ingestion — they compute, alert, or deliver intelligence.

| Function | Lambda | EventBridge Rule | Cron (UTC) | PT (PST) | IAM Role |
|---|---|---|---|---|---|
| Anomaly Detector v2.1 | `anomaly-detector` | `anomaly-detector-daily` | `cron(5 16 * * ? *)` | 08:05 AM | `lambda-anomaly-detector-role` |
| Cache Warmer | `life-platform-mcp` | `life-platform-nightly-warmer` | `cron(0 17 * * ? *)` | 09:00 AM | `lambda-mcp-server-role` |
| Whoop Recovery Refresh | `whoop-data-ingestion` | `whoop-recovery-refresh` | `cron(30 17 * * ? *)` | 09:30 AM | `lambda-whoop-role` |
| Freshness Checker | `life-platform-freshness-checker` | `life-platform-freshness-check` | `cron(45 17 * * ? *)` | 09:45 AM | `lambda-freshness-checker-role` |
| Daily Brief | `daily-brief` | `daily-brief-schedule` | `cron(0 18 * * ? *)` | 10:00 AM | `lambda-weekly-digest-role` |
| Weekly Digest | `weekly-digest` | `weekly-digest-sunday` | `cron(0 16 ? * SUN *)` | Sun 8:00 AM | `lambda-weekly-digest-role` |
| Monthly Digest | `monthly-digest` | `monthly-digest-schedule` | `cron(0 16 ? * 1#1 *)` | 1st Mon 8:00 AM | `lambda-weekly-digest-role` |
| Character Sheet Compute | `character-sheet-compute` | `character-sheet-compute` | `cron(35 17 * * ? *)` | 09:35 AM | `lambda-character-sheet-role` |
| Nutrition Review | `nutrition-review` | `nutrition-review-schedule` | `cron(0 17 ? * SAT *)` | Sat 9:00 AM | `lambda-weekly-digest-role` |
| Wednesday Chronicle | `wednesday-chronicle` | `wednesday-chronicle` | `cron(0 15 ? * WED *)` | Wed 7:00 AM | `lambda-weekly-digest-role` |
| The Weekly Plate | `weekly-plate` | `weekly-plate-schedule` | `cron(0 2 ? * SAT *)` | Fri 6:00 PM | `lambda-weekly-digest-role` |
| Dashboard Refresh (2 PM) | `dashboard-refresh` | `dashboard-refresh-afternoon` | `cron(0 22 * * ? *)` | 2:00 PM | `lambda-dashboard-refresh-role` |
| Dashboard Refresh (6 PM) | `dashboard-refresh` | `dashboard-refresh-evening` | `cron(0 2 * * ? *)` | 6:00 PM | `lambda-dashboard-refresh-role` |
| MCP Key Rotator | `mcp-key-rotator` | Secrets Manager rotation | 90-day auto | — | `lambda-key-rotator-role` |

**Note:** `daily-brief`, `weekly-digest`, `monthly-digest`, `nutrition-review`, `wednesday-chronicle`, and `weekly-plate` all share the `lambda-weekly-digest-role`. This role has DynamoDB read/write, Secrets Manager (anthropic key), and SES SendEmail scoped to `mattsusername.com`.

### File-triggered ingestion (S3 → Lambda)

Two sources use file uploads. Dropping a file in the correct S3 path triggers the Lambda automatically:

| Source | Lambda | S3 Trigger Path | IAM Role |
|---|---|---|---|
| MacroFactor | `macrofactor-data-ingestion` | `s3://matthew-life-platform/uploads/macrofactor/*.csv` (auto-detects nutrition vs workout CSV) | `lambda-macrofactor-role` |
| Apple Health | `apple-health-ingestion` | `s3://matthew-life-platform/imports/apple_health/*.xml` | `lambda-apple-health-role` |

### Event-driven Lambdas (S3 trigger, no schedule)

| Function | Lambda | Trigger | IAM Role |
|---|---|---|---|
| Insight Email Parser | `insight-email-parser` | S3 `raw/inbound_email/*` ObjectCreated | `lambda-insight-email-parser-role` |

**Insight Email Parser:** Processes inbound email replies to Life Platform emails. SES receives email at `insight@aws.mattsusername.com` → stores in S3 `raw/inbound_email/` → Lambda extracts reply text (strips quoted original, signatures) → saves insight to `USER#matthew#SOURCE#insights` with auto-tagging → sends confirmation email. Security: ALLOWED_SENDERS whitelist (`awsdev@mattsusername.com`, `mattsthrowaway@protonmail.com`). ✅ Fully live as of 2026-02-27 (DNS MX + SES receipt rule + domain verification complete).

**Note:** MacroFactor has both a scheduled EventBridge rule (8:00 AM PT) and an S3 trigger. The Dropbox poll Lambda checks for new CSV exports every 30 minutes and copies them to S3, which then triggers ingestion. The scheduled rule provides a daily safety net.

### Webhook ingestion (API Gateway → Lambda)

Health Auto Export iOS app pushes Apple Health data (including CGM/Dexcom Stelo blood glucose) to a webhook endpoint every 4 hours.

| Source | Lambda | Endpoint | Auth |
|---|---|---|---|
| Health Auto Export | `health-auto-export-webhook` | `https://a76xwxt2wa.execute-api.us-west-2.amazonaws.com/ingest` | Bearer token (Secrets Manager: `life-platform/health-auto-export`) |

**Full request path:** Health Auto Export app → `POST /ingest` → API Gateway (HTTP API `a76xwxt2wa`, route `POST /ingest`) → `health-auto-export-webhook` Lambda → DynamoDB `update_item` + S3 raw archive.

Data flow: **Dexcom Stelo → Apple HealthKit → Health Auto Export app (background, 4h) → API Gateway → Lambda → DynamoDB + S3**

**Three-tier source filtering (v1.1.0):**
- Tier 1 (Apple-exclusive): steps, active/basal energy, gait metrics, flights, distance, headphone audio, water intake, caffeine — all readings ingested
- Tier 2 (cross-device): HR, RHR, HRV, respiratory rate, SpO2 — filtered to Apple Watch/iPhone sources only (field suffix `_apple`)
- Tier 3 (skip): nutrition (MacroFactor SOT), sleep environment (Eight Sleep SOT — bed temp/toss & turns), body comp (Withings SOT)
  - **Note (v2.55.0):** Sleep *duration/staging/score/efficiency* SOT moved to Whoop. Eight Sleep remains SOT for bed environment only. See DATA_DICTIONARY.md for full field mapping.

The Lambda merges data into existing `apple_health` DynamoDB records using `update_item` (won't overwrite XML export fields). Individual 5-minute CGM readings are archived in S3 at `raw/cgm_readings/YYYY/MM/DD.json`. Raw webhook payloads are archived at `raw/health_auto_export/YYYY/MM/DD_HHmmss.json`.

**Webhook v1.4.0:** Added blood pressure metrics (systolic, diastolic, pulse) to Tier 1 METRIC_MAP. Individual BP readings stored in S3 `raw/blood_pressure/YYYY/MM/DD.json` for AM/PM analysis.

**Webhook v1.5.0:** Added State of Mind payload detection. How We Feel app writes State of Mind to HealthKit → HAE pushes as a separate Data Type automation → Lambda detects, stores individual check-ins in S3 `raw/state_of_mind/YYYY/MM/DD.json`, aggregates daily metrics (valence avg/min/max, check-in counts, top labels/associations) to DynamoDB `state_of_mind` source.

**⚠️ Note:** `apple-health-ingestion` is a separate, legacy Lambda triggered by S3 XML uploads. It does NOT receive webhook data. When debugging webhook issues, check `health-auto-export-webhook` logs, not `apple-health-ingestion`.

### Failure handling

Lambdas route async failures to `life-platform-ingestion-dlq` (SQS). DLQ coverage: 20 of 22 Lambdas (all data ingestion, enrichment, and scheduled operational Lambdas). Only `life-platform-mcp` and `health-auto-export-webhook` are excluded (request/response pattern, not async). IAM roles for digest/operational Lambdas have `sqs-dlq-send` inline policy granting `sqs:SendMessage`.

CloudWatch metric alarms: 21 total, monitoring Errors metric on each Lambda. Alarm actions route to SNS topic `life-platform-alerts`. Alarms use a 24-hour evaluation period with `TreatMissingData: notBreaching`.

There is no composite alarm — individual alarms fire independently.

### OAuth token management

Whoop, Withings, Strava, and Garmin use OAuth2 with refresh tokens. The pattern is: each Lambda reads its secret from Secrets Manager, calls the API with the current access token, and if the token has expired it uses the refresh token to get a new pair — then writes the updated credentials back to Secrets Manager before returning. This means tokens are self-healing across normal daily runs.

Eight Sleep uses username/password auth (refreshed each invocation). Notion, Habitify, and Todoist use static API keys.

---

## Store Layer

### S3 — raw data

Raw API responses are stored in `matthew-life-platform` partitioned by source and date. This is a backup/audit layer; the MCP server reads S3 only for CGM data (`raw/cgm_readings/*`).

**S3 static website hosting** is enabled on the bucket for the web dashboard. The bucket policy allows public `GetObject` on the `dashboard/*` prefix only — all other objects remain private. `BlockPublicPolicy` is disabled (required for website hosting); `BlockPublicAcls` and `IgnorePublicAcls` remain enabled.

```
s3://matthew-life-platform/
  dashboard/
    index.html                         ← daily dashboard (public read, CloudFront cached)
    clinical.html                      ← clinical summary (public read, CloudFront cached)
    data.json                          ← written by Daily Brief Lambda (public read)
    clinical.json                      ← written by Weekly Digest Lambda (public read)
  config/
    board_of_directors.json           ← 12-member expert panel config (read by 5 email Lambdas via board_loader.py)
    character_sheet.json               ← Character Sheet config: pillar weights, tiers, XP bands, cross-pillar effects (read by character_engine.py)
    profile.json                       ← user profile (targets, habits, phases)
  raw/
    whoop/2026/02/22/response.json
    withings/2026/02/22/response.json
    cgm_readings/2026/02/25.json       ← MCP reads this for glucose tools
    health_auto_export/2026/02/25_*.json
    inbound_email/<ses-message-id>       ← SES inbound emails (triggers insight-email-parser)
    state_of_mind/2026/02/27.json        ← How We Feel check-ins (webhook v1.5.0)
    blood_pressure/2026/02/25.json       ← Individual BP readings (webhook v1.4.0)
    ...
  uploads/
    macrofactor/*.csv                  ← triggers macrofactor Lambda
  imports/
    apple_health/*.xml                 ← triggers apple-health Lambda
```

Dashboard URLs:
- CloudFront: `https://dash.averagejoematt.com/` (primary, Lambda@Edge cookie auth)
- S3 direct: `http://matthew-life-platform.s3-website-us-west-2.amazonaws.com/dashboard/`

Blog URLs:
- CloudFront: `https://blog.averagejoematt.com/` (public, no auth)
- S3 direct: `http://matthew-life-platform.s3-website-us-west-2.amazonaws.com/blog/`
- ACM cert: `arn:aws:acm:us-east-1:205930651321:certificate/952ddf18-d073-4d04-a0b7-42c7f5150dc2`
- Content: `blog/index.html`, `blog/week-NN.html`, `blog/style.css`, `blog/about.html`
- DynamoDB: `USER#matthew#SOURCE#chronicle` partition stores installments for continuity

### DynamoDB — normalised data

Table: `life-platform` (us-west-2)  
Design: **Single-table** with composite keys  
Billing: On-demand (pay-per-request)  
Deletion protection: enabled  
PITR: enabled (35-day rolling recovery)  
TTL: enabled on `ttl` attribute (used by cache partition)

All data, regardless of source, lives in one table. The key structure encodes the user, source, and date:

```
PK (partition key):  USER#matthew#SOURCE#<source>
SK (sort key):       DATE#YYYY-MM-DD
```

Example keys:
```
PK: USER#matthew#SOURCE#whoop     SK: DATE#2026-02-22   → Whoop recovery record
PK: USER#matthew#SOURCE#withings  SK: DATE#2026-02-22   → Withings weight record
PK: USER#matthew#SOURCE#strava    SK: DATE#2026-02-22   → Strava day aggregate
PK: USER#matthew#SOURCE#journal   SK: DATE#2026-02-22#ENTRY#<uuid>  → Journal entry
PK: USER#matthew#SOURCE#day_grade SK: DATE#2026-02-22   → Day grade + components
PK: USER#matthew#SOURCE#habit_scores SK: DATE#2026-02-22 → Tier-weighted habit scores
PK: USER#matthew                  SK: PROFILE#v1        → User profile/settings
PK: CACHE#matthew                 SK: TOOL#<cache_key>  → MCP pre-computed cache (TTL)
```

No GSI by design — all access patterns are served by PK+SK queries.

**⚠️ 400KB item size limit:** Monitor Strava activities, MacroFactor food_log, and Apple Health records which nest arrays inside day items.

See `SCHEMA.md` for the full field-level definitions per source.

---

## Serve Layer

### MCP Server

**Lambda:** `life-platform-mcp`  
**Tools:** 105 live  
**Memory:** 1024 MB (doubled from 512 MB in v2.33.0 for 2x CPU allocation)  
**Endpoint:** Lambda Function URL — `https://votqefkra435xwrccmapxxbj6y0jawgn.lambda-url.us-west-2.on.aws/`  
**Auth:** AuthType NONE at AWS level; authentication handled in Lambda code via `x-api-key` header check (key stored in Secrets Manager `life-platform/mcp-api-key`)  
**Protocol:** JSON-RPC 2.0 over HTTP (MCP 2024-11-05)

The MCP server is a stateless Lambda backed by a 23-module Python package (`mcp/`). The entry point `mcp_server.py` imports `mcp.handler` which routes requests to 20 domain-specific tool modules. Shared configuration (table name, bucket, user ID, version) lives in `mcp/config.py`; DynamoDB helpers, date parsing, and cache logic live in `mcp/utils.py`. Cold start is approximately 700–800ms; warm invocations are typically 23–30ms for simple tools. 12 tools check DynamoDB cache on default queries and return pre-computed results in <100ms.

**Remote MCP (v2.44.0):** Streamable HTTP transport (MCP spec 2025-06-18) via Lambda Function URL `c5hljblvma4u2xd6wf6oe4clk40unthu.lambda-url.us-west-2.on.aws` with OAuth auto-approve + HMAC Bearer token validation. Enables claude.ai and Claude mobile access.

**IAM role:** `lambda-mcp-server-role` — DynamoDB `GetItem`, `Query`, and `PutItem` (no `Scan`, no `DeleteItem`). S3 `GetObject` on `raw/cgm_readings/*` for glucose tools. `PutItem` is required because the MCP Lambda doubles as the nightly cache warmer — it writes pre-computed results to the `CACHE#matthew` partition on EventBridge invocations. There is no separate warmer Lambda.

### Cache warmer

An EventBridge rule triggers the MCP Lambda at 09:00 AM PT (17:00 UTC) daily with a special payload (`source: aws.events`). The warmer pre-computes twelve tool results and writes them to the `CACHE#matthew` DynamoDB partition with a 26-hour TTL. Measured runtime: ~7 seconds (well within 300s timeout).

**Original 6 (v2.14.0):**
- `get_aggregated_summary` (5-year, yearly view)
- `get_aggregated_summary` (2-year, monthly view)
- `get_personal_records`
- `get_seasonal_patterns`
- `get_health_dashboard`
- `get_habit_dashboard`

**Added in v2.33.0:**
- `get_readiness_score` — cache key: `readiness_score_YYYY-MM-DD`
- `get_health_risk_profile` — cache key: `health_risk_profile_all`
- `get_body_composition_snapshot` — cache key: `body_comp_snapshot_latest`
- `get_energy_balance` — cache key: `energy_balance_YYYY-MM-DD`
- `get_day_type_analysis` — cache key: `day_type_analysis_YYYY-MM-DD`
- `get_movement_score` — cache key: `movement_score_YYYY-MM-DD`

Tools 7-12 have inline cache-get checks: default queries return cached results instantly, custom date ranges bypass cache. The warmer passes `_skip_cache: True` to force fresh computation.

### Email cadence

Four Lambdas deliver proactive intelligence on a schedule:

| Lambda | Schedule (PT) | Purpose | IAM Role |
|---|---|---|---|
| `anomaly-detector` v2.1 | Daily 8:05 AM | Adaptive threshold anomaly detection (15 metrics / 7 sources). Per-metric CV-based Z thresholds (1.5/1.75/2.0 SD), day-of-week normalization (steps/tasks/habits), minimum absolute change filters. **Travel-aware (v2.1.0):** checks travel partition before alerting; if traveling, still detects and records but suppresses alert email with `severity: travel_suppressed`. Writes DynamoDB record with threshold transparency | `lambda-anomaly-detector-role` |
| `daily-brief` v2.54 | Daily 10:00 AM | 18-section brief: readiness, day grade + TL;DR, scorecard, weight phase, training, nutrition, **habits (tier-weighted intelligence)**, **supplements**, CGM spotlight (fasting proxy + 7d trend), gait & mobility, **weather context**, **travel banner**, **blood pressure**, guidance, journal pulse/coach, BoD insight, anomaly alert. 4 Haiku AI calls. **Writes `dashboard/data.json` to S3 + persists `habit_scores`** | `lambda-weekly-digest-role` |
| `weekly-digest` v4.3 | Sunday 8:00 AM | 7-day summary across all sources, day grade trends, Board of Advisors commentary (Haiku) | `lambda-weekly-digest-role` |
| `monthly-digest` v1.1 | 1st Monday 8:00 AM | Monthly coach's letter, 30-day vs prior-30-day deltas, annual goals progress bars | `lambda-weekly-digest-role` |

**Board of Directors prompt architecture (v2.57.0):** All 5 email Lambdas (daily-brief, weekly-digest, monthly-digest, nutrition-review, wednesday-chronicle) load expert persona definitions from `s3://matthew-life-platform/config/board_of_directors.json` via a shared `board_loader.py` utility bundled in each zip. Each Lambda has a `_build_*_from_config()` function that assembles prompts dynamically, with hardcoded `_FALLBACK_*` constants as safety net. The `board_loader` module caches the S3 config for 5 minutes to avoid repeated reads within a single invocation.

### Freshness checker

`life-platform-freshness-checker` runs daily at 9:45 AM PT. Checks data freshness across all sources and sends an SES alert email + SNS escalation if any source is stale beyond its threshold.

### Local integration — mcp_bridge.py

`mcp_bridge.py` is the local adapter that runs on the MacBook and lets Claude Desktop connect to the MCP server. It translates Claude Desktop's stdio MCP protocol into HTTPS calls to the Lambda Function URL. The API key is embedded in the bridge configuration.

---

## Data Flow Diagram

```
Whoop API
Withings API       →  OAuth Lambda  →  DynamoDB  ←──┐
Strava API                                           │
Garmin API                                           │
                                                     │
Todoist API        →  API Lambda    →  DynamoDB      │
Eight Sleep API                                      │
Habitify API                                         │
Notion API                                           │
                                                     │
MacroFactor CSV ──→  Dropbox poll → S3 ──→ Lambda →  DynamoDB
Apple Health XML ─→  S3 bucket  ──→  S3-trigger Lambda → DynamoDB
                                                     │
Health Auto Export →  API Gateway → Webhook Lambda → DynamoDB + S3
                                                     │
                                               MCP Lambda (105 tools)
                                                     │
                                               Lambda Function URL (HTTPS)
                                                     │
                                               mcp_bridge.py (local)
                                                     │
                                               Claude Desktop
```

---

## IAM Security Model

Each Lambda has a dedicated, least-privilege IAM role (20 roles for 22 Lambdas — 3 email Lambdas share one role):

- **Ingestion roles:** DynamoDB write to `life-platform` table, S3 write to `matthew-life-platform`, Secrets Manager read limited to their specific secret ARN, SQS SendMessage to DLQ
- **MCP role:** DynamoDB `GetItem` + `Query` + `PutItem` (for cache warmer writes), S3 `GetObject` on `raw/cgm_readings/*` — no `Scan`, no `DeleteItem`
- **Email role** (`lambda-weekly-digest-role`): DynamoDB read/write, Secrets Manager (anthropic key), SES SendEmail scoped to `mattsusername.com` domain identity, S3 PutObject on `dashboard/*` (inline policy `dashboard-s3-write`, added v2.38.0). Weekly Digest writes `dashboard/clinical.json` using same policy.
- **Anomaly detector role:** DynamoDB read/write, Secrets Manager (anthropic key), SES SendEmail scoped to `mattsusername.com` domain identity
- No role has `dynamodb:Scan` or cross-account permissions

---

## Secrets Manager

12 secrets at $0.40/month each = **$4.80/month** (largest single cost driver):

| Secret | Used By |
|---|---|
| `life-platform/whoop` | Whoop Lambda (OAuth2) |
| `life-platform/withings` | Withings Lambda (OAuth2) |
| `life-platform/strava` | Strava Lambda (OAuth2) |
| `life-platform/garmin` | Garmin Lambda (OAuth2) |
| `life-platform/eightsleep` | Eight Sleep Lambda (username/password) |
| `life-platform/todoist` | Todoist Lambda (API key) |
| `life-platform/habitify` | Habitify Lambda (API key) |
| `life-platform/notion` | Notion Lambda (API key) |
| `life-platform/dropbox` | Dropbox poll Lambda (OAuth2) |
| `life-platform/health-auto-export` | Webhook Lambda (bearer token) |
| `life-platform/anthropic` | Email Lambdas (Haiku API key) |
| `life-platform/mcp-api-key` | MCP server (client auth) |

---

## Cost Profile

Target: under $25/month  
Current: ~$5/month ($0.63 MTD as of 2026-02-25)

Primary cost drivers:
- **Secrets Manager:** $4.80/month (12 secrets × $0.40) — largest line item
- **Lambda invocations:** ~600/month (12 ingestion × 30 days + operational + MCP on-demand + Dropbox poll ~1440/month + insight-email event-driven)
- **DynamoDB:** Pay-per-request mode, minimal reads/writes
- **S3:** ~2.3 GB stored (raw archives)
- **CloudWatch:** 20 log groups, 30-day retention
- **CloudTrail:** Logging to S3 (free tier)

AWS Budget alerts at $5 (25%), $10 (50%), and $20 (100%) to `awsdev@mattsusername.com`.

---

## Local Project Structure

```
~/Documents/Claude/life-platform/
  # ── Root: MCP server + bridge only ───────────────────────
  mcp_server.py                   ← MCP Lambda entry point (thin wrapper, imports mcp/)
  mcp_bridge.py                   ← Local MCP adapter for Claude Desktop
  mcp/                            ← MCP server package (23 modules)
    __init__.py
    handler.py                    ← Request router
    config.py                     ← Shared constants, __version__, USER_ID
    utils.py                      ← DynamoDB helpers, date parsing, cache layer
    tools_sleep.py ... (18 domain modules)
    tools_character.py                ← Character Sheet tools (get_character_sheet, get_pillar_detail, get_level_history)
  .gitignore

  # ── Documentation (all .md files) ────────────────────────
  docs/
    ARCHITECTURE.md               ← This file
    SCHEMA.md                     ← DynamoDB field definitions per source
    RUNBOOK.md                    ← Operational procedures
    CHANGELOG.md                  ← Version history
    PROJECT_PLAN.md               ← Roadmap and backlog
    USER_GUIDE.md                 ← How to use the MCP tools effectively
    FEATURES.md                   ← Non-technical + technical feature showcase
    MCP_TOOL_CATALOG.md           ← All 72 tools with params, cache, dependencies
    DATA_DICTIONARY.md            ← Every metric → SOT source, overlap, gaps
    COST_TRACKER.md               ← Budget tracking and cost decisions
    INCIDENT_LOG.md               ← Operational incident history
    HANDOVER_LATEST.md            ← Pointer to most recent handover
    CHANGELOG_ARCHIVE.md          ← Changelog entries before v2.20
    PROJECT_PLAN_ARCHIVE.md       ← Completed project plan items
    archive/                      ← Completed spec docs (6 files)
    rca/                          ← Root cause analyses

  # ── Lambdas: source + deployment packages ─────────────────
  lambdas/
    whoop_lambda.py / .zip        ← OAuth ingestion (12 similar per source)
    board_loader.py               ← Shared utility: loads Board of Directors config from S3 (bundled in 5 email Lambda zips)
    character_engine.py             ← Character Sheet scoring engine: 7 pillar scorers, EMA smoothing, level/tier transitions, XP, cross-pillar effects (bundled in MCP Lambda zip)
    daily_brief_lambda.py / .zip  ← Daily readiness email (18 sections) + dashboard JSON
    dashboard/                     ← Static web dashboard (index.html + sample data.json)
    weekly_digest_v2_lambda.py    ← Sunday weekly digest (v4.3)
    monthly_digest_lambda.py      ← Monthly coach's letter (v1.1)
    nutrition_review_lambda.py    ← Saturday nutrition review (v1.1, Sonnet)
    wednesday_chronicle_lambda.py ← Wednesday chronicle (v1.1, Sonnet, Elena Voss)
    anomaly_detector_lambda.py    ← Multi-source anomaly detection
    mcp_server.zip                ← Deployment package for MCP Lambda
    freshness_checker_lambda.py    ← Data freshness monitoring
    ...                           ← 24 Lambdas total

  # ── Operational scripts ────────────────────────────────────
  deploy/                         ← ~60 deploy_*.sh scripts
  backfill/                       ← ~20 backfill + migration + replay scripts
  patches/                        ← ~30 historical patch scripts
  seeds/                          ← 7 data seed scripts (labs, genome, DEXA, profile)
  setup/                          ← ~12 auth + infrastructure setup scripts
  tests/                          ← 5 test scripts
  scripts/                        ← .command shortcuts (deploy, verify, logs, cache)

  # ── Session history ────────────────────────────────────────
  handovers/                      ← 53+ session handover notes

  # ── Data drop folders (watched by launchd) ─────────────────
  datadrops/
    apple_health_drop/            ← Drop Apple Health .zip exports here
    macrofactor_drop/             ← Drop MacroFactor .csv exports here
    habits_drop/                  ← Drop Chronicling .csv exports here
    bloodtest_drop/               ← Lab result uploads
    dexa_drop/                    ← DEXA scan uploads
    functionhealth_drop/          ← Function Health exports
    physicals_drop/               ← GP physical documents
    genome/                       ← Genome data
    apple_health_export/          ← Unzipped Apple Health export.xml

  # ── Local automation ───────────────────────────────────────
  ingest/                         ← launchd drop-folder processor
  archive/legacy-scripts/         ← Old p40 scripts
```
