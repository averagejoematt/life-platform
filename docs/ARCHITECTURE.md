# Life Platform — Architecture

> **Status:** canonical · **Owner:** Matthew · **Verified:** 2026-10-17

Last updated: 2026-10-23 (v8.6.0 — 89 tools, 81-module MCP package, 20 data sources, 108 Lambdas, 26 secrets, 137 alarms, 10 CDK stacks deployed).

> **v4 "The Measured Life" front-end is live** (ADR-071) — `averagejoematt.com` is a static S3 + CloudFront site over the unchanged engine, with **Home + five doors** (v5 IA): the cockpit (`/cockpit/`, live data), the data (`/data/`, the evidence archive — old `/evidence/*` slugs 301), the coaching, the protocols, and the story (`/story/`, the writing hub); the pre-v4 site is preserved verbatim at `/legacy`. Shared code ships **bundled inside every function** (#781/ADR-131 — the shared layer is retired; see [CONVENTIONS.md §1](CONVENTIONS.md)). **162 ADRs** (ADR-001 → ADR-164 — full index auto-generated in [DECISIONS.md](DECISIONS.md)). The count line above is auto-maintained by `deploy/sync_doc_metadata.py` (pre-commit hook) — edit `PLATFORM_FACTS` there, not by hand.

---

## Overview

The life platform is a personal health intelligence system built on AWS. It ingests data from ~twenty sources (the per-source method, cadence and paused state are the `method`/`stale_hours`/`paused` facets in `lambdas/ingestion/source_registry.py` — the breakdown is not hand-restated here), normalises everything into a single DynamoDB table, and surfaces it to Claude through a Lambda-backed MCP server. The design philosophy is: get data in automatically, store it cheaply, and make it queryable without a data engineering background.

---

## Three-Layer Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  INGEST LAYER                                               │
│  Scheduled Lambdas (EventBridge) + S3 Triggers + Webhooks   │
│  Whoop · Withings · Strava (Garmin watch via Strava)        │
│  Eight Sleep · MacroFactor · Habitify · Notion Journal      │
│  Health Auto Export (webhook — Apple Health: CGM/BP/SoM) ·  │
│  Weather · Hevy · Todoist · social feeds                    │
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
│  MCP Server Lambda (89 tools, 768 MB) + Lambda Function URL │
│  ← Claude Desktop + claude.ai + Claude mobile via remote MCP│
│                                                             │
│  COMPUTE LAYER (IC intelligence features)                   │
│  character-sheet-compute · adaptive-mode-compute            │
│  daily-metrics-compute · daily-insight-compute (IC-8)       │
│  hypothesis-engine v1.2.0 (IC-18+IC-19, Sunday 12 PM PT)   │
│  compute → store → read pattern: runs before Daily Brief    │
│                                                             │
│  EMAIL LAYER                                                │
│  monday-compass (Mon 8am) · daily-brief (10am)              │
│  wednesday-chronicle (Wed 8am) · weekly-plate (Fri 7pm)     │
│  weekly-digest (Sun 9am) · monthly-digest (1st Mon 9am)     │
│  nutrition-review (Sat 10am) · anomaly-detector (8:05am)    │
│  freshness-checker (9:45am) · insight-email-parser (S3 trig)│
│                                                             │
│  WEB LAYER — v4 "The Measured Life" (ADR-071)              │
│  averagejoematt.com · CloudFront E3S424OXQZ8NBE → S3 /site  │
│  Five doors (v5 IA): /cockpit/ (Cockpit) · /data/ ·         │
│    /coaching/ · /protocols/ · /story/ · / (landing)         │
│  Old site preserved at /legacy (private; 301s via the       │
│    v4-redirects CF function from redirects.map)             │
│  site-api Lambda (read-only): /api/ask · /api/board_ask ·   │
│    /api/pulse · /api/journey · /api/workouts · /api/labs …  │
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
| S3 bucket (backup) | Cross-region replica of the irreplaceable zone | `matthew-life-platform-raw-backup` (**us-east-2**) — receives `raw/*` by S3 replication (DIL-027/#3042). Versioned, public-access-blocked, `RETAIN`, its own delete-protection Deny; delete markers are **not** replicated. CDK-owned in `backup_stack.py`; the source-side replication rule is out-of-IaC (`deploy/s3_replication.json`, see MANAGED_WHERE_LEDGER). Same account — see the DIL-027 priced residual |
| SQS queue | Dead-letter queue | `life-platform-ingestion-dlq` |
| Lambda Function URL (remote MCP) | Remote MCP HTTPS endpoint | `<not committed — SEC-02 #780; read live: aws lambda get-function-url-config --function-name life-platform-mcp --region us-west-2>` (OAuth 2.1 auto-approve + HMAC Bearer) |
| API Gateway | HTTP endpoint | `health-auto-export-api` (`p6clybdkkc`, CDK-owned; the older `a76xwxt2wa` is the retired orphan — `tests/test_teardown_hae_orphan_api.py`) — webhook ingest |
| Secrets Manager | Credential store | **26 active secrets** at $0.40/month each = **~$10.40/month**
| SNS topic | Alert routing | `life-platform-alerts` (urgent) + `life-platform-alerts-digest` (batched daily by `alert-digest-lambda` per ADR-050) |
| CloudFront (amj) | CDN (public) | `E3S424OXQZ8NBE` → site-api Lambda + S3 `/site`, alias `averagejoematt.com` |
| CloudFront (dash) | CDN + auth | `EM5NPX6NJN095` (`d14jnhrgfrte42.cloudfront.net`) → S3 `/dashboard`, Lambda@Edge auth, alias `dash.averagejoematt.com` |
| CloudFront (blog) | CDN (public) | `E1JOC1V6E6DDYI` (`d1aufb59hb2r1q.cloudfront.net`) → S3 `/blog`, alias `blog.averagejoematt.com` |
| CloudFront (buddy) | CDN (public) | `ETTJ44FT0Z4GO` (`d1empeau04e0eg.cloudfront.net`) → S3 `/buddy`, alias `buddy.averagejoematt.com` |
| ACM Certificate | TLS | us-east-1 — `averagejoematt.com` + all subdomains (DNS-validated via Route 53) |
| SES Receipt Rule Set | Inbound email routing | `life-platform-inbound` (active) — rule `insight-capture` routes `insight@aws.mattsusername.com` → S3 |
| SES Configuration Set | Outbound delivery telemetry | `life-platform-emails` wired to `daily-brief`, `weekly-digest`, `monthly-digest`, `partner-weekly-email` |
| CloudWatch | Alarms + logs | **~137 metric alarms**. Per-Lambda `ingestion-error-*` first-error alarms are retired across ingestion (2026-05-29), compute + email (#790/ADR-116, 2026-07-07 — 48 alarms) in favour of the shared `life-platform-ingestion-dlq` digest path (`life-platform-ingestion-dlq-messages` + `life-platform-dlq-depth-warning`). |
| CDK | Infrastructure as Code | `cdk/` — 10 stacks. CDK owns all Lambda IAM roles + every EventBridge schedule rule (the count is `model/platform_model.json` `meta.counts.schedules` — read it there, it is not restated here so a branch adding a schedule cannot strand it between the committed and the regenerated model; the live account holds more rules than CDK declares). Stacks: `core_stack`, `ingestion_stack`, `email_stack`, `compute_stack`, `mcp_stack`, `operational_stack`, `serve_stack` (public serving path: site-api + site-api-ai — #793, split via `cdk refactor` 2026-07-08), `web_stack`, `monitoring_stack`, `backup_stack` (DIL-027/#3042 — the `raw/` cross-region replica bucket + replication role, **us-east-2**; the only stack outside us-west-2 other than `web_stack`'s us-east-1). |
| CloudTrail | Audit logging | `life-platform-trail` → S3. Data events enabled for `s3://matthew-life-platform/raw/` and `s3://matthew-life-platform/uploads/`. |
| AWS Budget | Cost guardrail | **$215/mo all-in cap** (ADR-063; base $75 -> $85 -> $150 -> $215, surge-to-$252 rule per ADR-133), alerts at 50%/70%/85%/100%. Enforced via `cost_governor_lambda` (every 8h) → SSM `/life-platform/budget-tier` → `budget_guard.py` gates AI features by AUDIENCE band (ADR-125; ground truth = `_FEATURE_CUTOFF`): 1=internal/dev AI (ensemble, chronicle editor, the coherence/reader-truth/visual QA passes), 2=reader narratives (coach commentary, State of Matthew, chronicle, nudges), 3=hard cutoff — the public ask endpoints and the daily brief's AI, the two surfaces that degrade LAST, enforced in `bedrock_client.invoke()`. |
| Concurrency quota | Account-level | **100** (raised 2026-05-19 from the account default of 10 — AWS Support case 177921309700709) |

---

## Ingest Layer

### Scheduled ingestion (EventBridge → Lambda)

Each source has its own dedicated Lambda and IAM role. Cadence is per source (its `schedule=` in `cdk/stacks/ingestion_stack.py`, mirrored as the registry facet); the `INGEST_HOURLY` helper skips the overnight-PT window for the sources that use it. All cron expressions use fixed UTC, with one exception: `daily-brief` runs on an EventBridge Scheduler schedule in `America/Los_Angeles` (#4284).

**Gap-aware backfill (v2.46.0):** All API-based ingestion Lambdas implement self-healing gap detection. On each run, the Lambda queries DynamoDB for the last N days (including today), identifies missing DATE# records, and fetches only those from the upstream API. Cost is ~$0/month — Lambdas short-circuit in <50ms when no new data exists.

**Schedule:** see the table below and `source_registry.py` for the live cadence. Garmin's direct function is **retired** (#4640, ADR-074 amendment — activities arrive through Strava); Weather runs 2x daily, Todoist 1x daily (COST-OPT).

**Shared modules — ONE bundle, no layer (#781/ADR-131, 2026-07-06):** the shared layer (`life-platform-shared-utils`) is **retired**. Shared modules ship **inside every function's code bundle**, staged by `deploy/build_bundle.py` (the whole `lambdas/` tree + `food_vocabulary.json`; the MCP shape adds `mcp_server.py` + `mcp/`). Since ADR-146 (#1653) there are **no loose modules at the `lambdas/` root** — shared engine code is packaged by domain (`common/` infrastructure, `ai/` inference, `experiment/` scientific apparatus, plus `coach/ health/ training/ content/ privacy/`), and the bundle stages that tree at the zip root, so a handler reads `from common import constants`. Key shared modules (each lives in its domain package — `lambdas/ai/ai_calls.py`, `lambdas/common/secret_cache.py`, `lambdas/ingestion/ingestion_framework.py`, `lambdas/health/scoring_engine.py`, …; `find lambdas -name <module>.py`): `ai_calls.py` (god-module split 2026-06-08 → `ai_calls.py` (AI-call layer: `call_anthropic` + coaches + board) / `ai_context.py` (prompt-context + scoring builders) / `ai_summaries.py` (data-summary builders); `ai_calls` re-exports both for backward compat), `retry_utils.py`, **`bedrock_client.py`** (ADR-062 — all Claude calls funnel here, IAM auth via `bedrock:InvokeModel`), **`budget_guard.py`** (ADR-063 — `allow(feature)` gates AI by SSM tier), `board_loader.py`, `output_writers.py`, `scoring_engine.py`, `secret_cache.py`, `intelligence_common.py`, `ingestion_framework.py` (SIMP-2 per ADR-056), `auth_breaker.py`, `http_retry.py`, `rate_limiter.py`, `request_validator.py`, `compute_metadata.py`, `constants.py` (genesis date + baseline), `phase_filter.py` (default-deny by phase), `numeric.py`, `character_engine.py`, `html_builder.py`, `ai_output_validator.py`, `platform_logger.py`, `ingestion_validator.py`, `item_size_guard.py`, `digest_utils.py`, `sick_day_checker.py`, `site_writer.py`, `insight_writer.py`. A shared-module change reaches the fleet via `deploy/deploy_fleet.sh` or `cdk deploy --all` (CI fleet-deploys automatically on unmapped `lambdas/` changes). Invariant: **zero functions reference the old layer** (CI plan job + integration test I2). Dependency layers with real third-party packages (garth, Pillow) are NOT the shared layer and remain. See `docs/CONVENTIONS.md` §1.

**Secret caching (COST-OPT-1):** 15-min in-memory TTL cache via `secret_cache.py` (bundled shared module). Reduces Secrets Manager API calls ~90% across 12 active Lambdas.

**Prompt caching (COST-OPT-2, ADR-049):** Both `ai_calls.py` and `retry_utils.py` auto-wrap system messages as cached content blocks (`anthropic-beta: prompt-caching-2024-07-31`). 90% discount on repeated system prompt tokens — **but only above the model's minimum cacheable prefix, and a `cache_control` block is not evidence of caching**: below the floor the API accepts the marker and silently ignores it (no error, no warning, `cache_read_input_tokens` stays 0). Floors are per-model, non-monotonic across generations, and identical on Bedrock and the first-party API — **Haiku 4.5's is 4,096 tok, 4x Sonnet 4.6's 1,024**, so the cheap tier model tiering routes structured tasks to is also the hardest to cache. The registry, and the per-caller record of which callers cache vs. were measured and deliberately declined, is `lambdas/ai/prompt_cache.py` (`MIN_CACHEABLE_PREFIX_TOKENS`, `CACHING_DECISIONS`). CloudWatch metrics: `AnthropicCacheWriteTokens`, `AnthropicCacheReadTokens`, plus `PromptCacheNoOp` (#2888 — asked for caching, wire reported none). Model tiering: structured/templated tasks use Haiku (`AI_MODEL` env var), narrative content stays on Sonnet. All model assignments are env-var configurable for instant rollback.

| Source | Lambda | Schedule | Type |
|---|---|---|---|
| Whoop | `whoop-data-ingestion` | Several times daily (see registry) | API pull |
| Garmin | (none) | Retired 2026-10-11 (#4640, ADR-074 amendment) — watch activities arrive through Strava | via Strava |
| Eight Sleep | `eightsleep-data-ingestion` | 4x daily (mornings) | API pull |
| Withings | `withings-data-ingestion` | 4x daily | API pull |
| Habitify | `habitify-data-ingestion` | Hourly (active hours) | API pull |
| Strava | `strava-data-ingestion` | Hourly (active hours) | API pull |
| Todoist | `todoist-data-ingestion` | 1x daily (14:00 UTC) | API pull |
| Notion Journal | `notion-journal-ingestion` | 3x daily | API pull |
| Weather | `weather-data-ingestion` | 2x daily | API pull |
| MacroFactor | `macrofactor-data-ingestion` | S3 trigger (Dropbox CSV) | File upload |
| Dropbox Poll | `dropbox-poll` | `rate(2 hours)` | File poll |
| Journal Enrichment | `journal-enrichment` | Daily 14:30 UTC | Compute |
| Activity Enrichment | `activity-enrichment` | Daily 15:30 UTC | Compute |
| Apple Health (CGM, water, BP, SOM) | `health-auto-export-webhook` | Near real-time (webhook) | HAE push |

> **SIMP-2 framework (ADR-056/060):** `lambdas/ingestion/ingestion_framework.py` (`IngestionConfig` + `run_ingestion`). ADR-056 recorded 8 adopters and 7 pattern-exempt functions; the census has moved since (the social-feed ingesters `bluesky`/`mastodon`/`youtube` and the enrichment Lambdas joined the stack, Garmin's direct function was retired), so the live set is the `ingestion_stack` entries in `model/platform_model.json` and the adopters are `grep -l run_ingestion lambdas/ingestion/*_lambda.py`. The long-standing pattern-exempt functions are `notion`, `macrofactor`, `dropbox-poll`, `food-delivery-ingestion`, `health-auto-export-webhook` (HAE near-real-time) and `measurements-ingestion` (a separate Lambda from the HAE webhook); `hevy-backfill` (hourly, all 24 hours — ADR-060; #3720) uses the framework's `run_ingestion`. (`apple_health` direct ingestion is RETIRED — ADR-103/#474; HAE is the Apple Health path now. Not every function is EventBridge-scheduled: macrofactor/food-delivery-ingestion/measurements-ingestion are S3-triggered, HAE is webhook-triggered. Live cadence + paused state per source: `lambdas/ingestion/source_registry.py`.)
>
> **Lambda renames + deletions in V2 cleanup (2026-05-17/19):** `weather_handler.py` → `weather_lambda.py`. `tools_calendar.py` DELETED (ADR-030 retired, Google Calendar). `podcast_scanner_lambda.py` DELETED (no AWS counterpart). `email_framework.py` DELETED from shared layer.

### Compute + Email Lambdas

The headline set; the full inventory (every function, handler, schedule, alarm) is `model/platform_model.json` / `docs/DEPENDENCY_GRAPH.md`.

| Function | Lambda | Cron (UTC) | PT (PDT) |
|---|---|---|---|
| Daily Insight Compute (IC-8) | `daily-insight-compute` | `cron(45 16 * * ? *)` | 09:45 AM |
| Daily Metrics Compute | `daily-metrics-compute` | `cron(40 16 * * ? *)` | 09:40 AM |
| Adaptive Mode Compute | `adaptive-mode-compute` | `cron(35 16 * * ? *)` | 09:35 AM |
| Character Sheet Compute | `character-sheet-compute` | `cron(30 16 * * ? *)` | 09:30 AM |
| Anomaly Detector | `anomaly-detector` | `cron(5 15 * * ? *)` | 08:05 AM |
| Daily Brief | `daily-brief` | `cron(0 10 * * ? *)` America/Los_Angeles (zoned, #4284) | 10:00 AM |
| Monday Compass | `monday-compass` | `cron(0 15 ? * MON *)` | Mon 08:00 AM |
| Wednesday Chronicle | `wednesday-chronicle` | `cron(0 15 ? * WED *)` | Wed 08:00 AM |
| The Weekly Plate | `weekly-plate` | `cron(0 2 ? * SAT *)` | Fri 07:00 PM |
| Weekly Digest | `weekly-digest` | `cron(0 16 ? * SUN *)` | Sun 09:00 AM |
| Nutrition Review | `nutrition-review` | `cron(0 17 ? * SAT *)` | Sat 10:00 AM |
| Monthly Digest | `monthly-digest` | `cron(0 16 ? * 1#1 *)` | 1st Mon 9:00 AM |
| Hypothesis Engine (IC-18) | `hypothesis-engine` | `cron(0 19 ? * SUN *)` | Sun 12:00 PM |
| Weekly Correlation Compute | `weekly-correlation-compute` | `cron(30 18 ? * SUN *)` | Sun 11:30 AM |
| Weekly Signal (PB-06) | `weekly-signal` | `cron(30 16 ? * SUN *)` | Sun 09:30 AM |
| Hevy Routine Cron (ADR-066) | `hevy-routine-cron` | `cron(30 13 ? * SUN *)` *(rule starts disabled)* | Sun 06:30 AM |

### Hevy Routine Write-Loop (ADR-066, 2026-05-31)

Closes the **program → perform → adapt** loop with Hevy. One write path, two front doors:

```
coaching / generation logic
        │
        ▼
  routine-spec IR  ◄── system of record (ROUTINE# DDB partition)
        │
        ▼
   hevy_compiler   ◄── sole owner of Hevy wire format (one module)
        │
        ▼
 create_routine / update_routine_with_guard  →  Hevy
```

- **Front door 1 — chat:** `manage_hevy_routine` MCP fat tool (9 actions: draft / dry_run / commit / list / get / archive / floor / re_entry / adherence).
- **Front door 2 — cron:** `hevy-routine-cron` Lambda, EventBridge rule `enabled=False` at birth + SSM `/life-platform/hevy/cron_enabled=false` (belt-and-suspenders).
- **Shared modules (bundled, `lambdas/training/` + `lambdas/health/adherence_calc.py`):** `routine_ir`, `hevy_compiler`, `hevy_write_client`, `hevy_template_cache`, `routine_repo`, `routine_generator`, `adherence_calc`.
- **Subtract-only autoregulation** until N≥30 readiness validation passes (PREREQS §C). Add-load SSM (`/life-platform/hevy/autoreg_add_load_enabled`) defaults `false`.
- **Conflict guard:** GET-before-PUT compares `updated_at`; refuses to clobber in-app edits.
- **Hevy API surprises:** no DELETE (archive = rename + folder-move), no webhooks (Phase 2 adherence polls `/v1/workouts/events`), no documented rate limits (client-side ≤1 req/s throttle).

### Reading / Mind Pillar data layer (ADR-097, Phase A)

A new source-of-truth domain (`reading`) on the shared table, using top-level pks (`BOOK#`, `READING#`) rather than the `USER#…#SOURCE#` convention. Data layer in `lambdas/reading/` (`reading_store`, `reading_keys`, `reading_visibility`, `reading_enrich`, `cover_placeholder` — bundled with the `lambdas/` asset like all shared code, #781). Two **additive GSIs** (the first on `life-platform`, amending ADR-005): **GSI1** sparse recall-due, **GSI2** reading state/time. Public/private split enforced server-side via the `reading_visibility.project_public` allowlist. All reading records are `CROSS_PHASE` (survive experiment resets).

| Function | Lambda | Trigger |
|---|---|---|
| Cover pipeline | `reading-cover-pipeline` | on-demand (Open Library → Google Books → designed placeholder; caches to `generated/covers/`, never hot-links) |

Later phases (B–E): MCP tools + rules-based recommender, the `/mind/` page, the read→debrief→recall loop, and the Constellation (`docs/specs/CLAUDE_CODE_PROMPT_READING_MIND_v1.md`).

### File-triggered ingestion (S3 → Lambda)

| Source | Lambda | S3 Trigger Path |
|---|---|---|
| MacroFactor | `macrofactor-data-ingestion` | `uploads/macrofactor/*.csv` |
| Insight Email | `insight-email-parser` | `raw/inbound_email/*` ObjectCreated |

> Apple Health's own XML ingestion is **retired** (ADR-103/#474 — the function no longer exists in AWS or in CDK): the Health Auto Export webhook below is the Apple Health path.

### Webhook ingestion (API Gateway → Lambda)

| Source | Lambda | Endpoint |
|---|---|---|
| Health Auto Export | `health-auto-export-webhook` | `https://p6clybdkkc.execute-api.us-west-2.amazonaws.com/ingest` |

### Failure handling

DLQ coverage: every async-invoked Lambda routes terminal failures to `life-platform-ingestion-dlq` EXCEPT these, whose CDK construct passes no DLQ at all — `life-platform-delete-user-data`, `life-platform-dlq-consumer`, `life-platform-mcp-warmer`, `life-platform-remediation-dispatcher`, `telegram-coach-worker` (#3500 owns closing the gap; the set is derived from CDK and diffed against this sentence by `scripts/doc_facts_infra.py`). Alarm actions route to SNS `life-platform-alerts`.

CloudWatch carries **~137 metric alarms** (CDK-declared; the count is auto-discovered by `deploy/sync_doc_metadata.py` and the inventory is regenerated into `docs/MONITORING.md`).

Additional safeguards — one per line so each cadence is a checkable claim (`scripts/doc_facts_infra.py` diffs both the
`rate(...)` literal and the prose interval against the CDK schedule):

- `life-platform-dlq-consumer` — drains the DLQ on `rate(6 hours)`, i.e. every 6 hours
- `life-platform-canary` — synthetic DDB+S3+MCP round-trip on `rate(4 hours)`, i.e. every 4 hours
- item size guard — `item_size_guard.py`, the 400KB DynamoDB write ceiling

Two OTHER canaries exist and are not the one above: `life-platform-ai-quality-canary` runs `cron(20 16 ? * MON,WED,FRI *)`,
and `life-platform-mcp-canary-15min` is a hand-made EventBridge rule (not a CDK-declared schedule) firing every 15 minutes.

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

**Lambda:** `life-platform-mcp` | **Tools:** 89 | **Memory:** 768 MB | **Runtime:** python3.12 | **Modules:** 81 (`mcp/tools_*.py` + helpers)
**Remote MCP:** `<not committed — SEC-02 #780; read live: aws lambda get-function-url-config --function-name life-platform-mcp --region us-west-2>`
**Auth:** OAuth 2.1 auto-approve + HMAC Bearer (remote). Source of truth for tool count: AST parse of top-level `TOOLS` dict keys via `deploy/sync_doc_metadata.py::_auto_discover_tool_count` (see CLAUDE.md — `grep '"name":'` over-counts nested schema fields).

Cold start: ~700–800ms. Warm: 23–30ms. Cached tools: <100ms.

### IC Intelligence Features (16 of 31 live)

Compute → store → read pattern. Standalone Lambdas run before Daily Brief, store results to DynamoDB.

**Live:** IC-1 (anomaly), IC-2 (training load), IC-3 (nutrition), IC-6 (CGM correlation), IC-7 (cross-pillar), IC-8 (intent vs execution), IC-15 (insights persistence), IC-16 (progressive context), IC-17 (readiness synthesis), IC-18 (hypothesis engine), IC-19 (N=1 experiments + slow drift + sustained anomaly), IC-23 (Character Sheet), IC-24 (adaptive mode), IC-25 (decisions), IC-29 (metabolic adaptation / deficit sustainability — TDEE divergence tracking, deployed v3.7.67), IC-30 (autonomic balance score — HRV + RHR + RR + sleep quality → 4-quadrant nervous system state, deployed v3.7.67).

**One calorie target (#5095, epic #5091):** every surface that states or grades a calorie target — scoring, the character sheet, the daily brief, the weekly / monthly / nutrition-review / partner emails, the insight and hypothesis engines, the coach's domain facts, `get_nutrition view=macros`, the energy view's `calorie_target_platform` and the nutrition critics — reads `health.calorie_target.resolve(day)`: the week's titration record (`…SOURCE#nutrition_titration` / `WEEK#<iso-monday>`, written weekly by the #5096 titration engine, `health.titration`, on the nightly pre-draft's titration leg; a resolve inside a Lambda reads it through a cached default reader) else the charter's `nutrition.calories` block (`config/training_charter.json`; ~1,500 kcal, owner ruling 2026-10-23 R1), with its source and provenance; the energy floors are WARNINGS (`floor_warnings`), never a clamp, and a record written before the re-target (`records_from_version`) is not read. The generated 1,500 kcal constant is retired and `tests/test_calorie_target_one_resolver_5095.py` guards the set. TDEE (ADR-152, `health.tdee`) stays MAINTENANCE context, never a target. **The weekly titration (#5096):** `health.titration.decide` reads the shared 14-day loss rate against the charter rate band (the landing schedule from the landing down, the clinical cap applied), counts consecutive out-of-band weekly reads, honours the 14-day spacing and steps-before-food, and moves the target down by at most the charter's `nutrition.titration.max_step_kcal`; above the band ceiling it holds and warns (`above_ceiling_action` `warn`, owner ruling 2026-10-23: food is never pushed up on its own); insufficient data holds. The owner sees the decision in the Saturday nutrition-review email; a week with no record is the calibration sweep's dead-man.

**Training-day fuel (#5101, epic #5091; owner rulings 2026-10-23 on R1, #5212 and the #5091 follow-ups):** the same resolver takes a `day_type` seam (`lifting | rest | travel | unknown`, from `calorie_target.classify_day_type`: a travel disruption or charter window, else the per-date training calendar, else unknown). The calendar is `training.training_calendar` (#5191): the split's sequence alone never types a date, so the calendar types the Mon–Sun Pacific week from the charter's `split.lifting_days_per_wk` and the week's credited program sessions (`session_sequence.completed_sessions`), laying the sessions still owed on the remaining dates (nominal lifting weekdays first) and typing every other date rest, so a rest-day postponement moves a session inside the week without changing its count. The plan (`training_calendar.plan_fuel`) and the weekly food panel read it; an unread Hevy record keeps `unknown` at the base with `if_lifting_day`/`if_rest_day` as conditional readings, and the typed block carries `week_days` / `week_mean_kcal` (the base plus the lifting uplift over the week; `week_balance_held` = no day under its base). `nutrition.training_day` in the charter holds the lifting-day uplift (+150 kcal, owner ruling 2026-10-23: rest days are NOT paid back below the target, so the week averages above the base by design — 1,650 lifting / 1,500 rest), the carbohydrate split (protein and fat held, fat never under its floor, carbohydrate moves) and the pre/post session targets (scaled to fit the 1,650 kcal lifting day's 96 g of carbohydrate); travel and unknown days stay at the base. Owner-only: the plan's `constraint_block.training_day_fuel` (no stored field, no public surface). `tests/test_training_day_fuel_5101.py`.

**Data-gated next:** IC-4 (failure patterns, ~Apr 18), IC-5 (momentum warning, ~Apr 18), IC-26 (temporal mining, ~May), IC-27 (multi-resolution handoff, ~May).

### Site API Lambda (us-west-2)

**Lambda:** `life-platform-site-api` | **Stack:** LifePlatformServe (#793 — split from Operational, `serve_stack.py`) | **Region:** us-west-2 (R17-09 migration)
**Function URL:** Routed through CloudFront (E3S424OXQZ8NBE). Lambda confirmed in us-west-2 (verified via AWS CLI 2026-03-30).
**IAM:** Primarily read-only — `dynamodb:GetItem, Query, PutItem` + `kms:Decrypt` + `s3:GetObject` on `site/config/*`. Limited writes for interactive features (votes, follows, checkins).

**Source layout** (P1.1 Phase B split the original 7,949-line monolith; #1654 split the facades): `lambdas/web/site_api_lambda.py` holds `lambda_handler` plus the `ROUTES`/`_SIMPLE_ROUTES` dispatch (the endpoint set is `ROUTES`); `site_api_common.py` the shared helpers (`_ok`, `_error`, `_query_source`, CORS, request-id state, the response cache); and ~40 sibling `site_api_<domain>.py` modules own the handlers by domain — e.g. `site_api_observatory.py`, `site_api_status.py`, `site_api_pulse.py`, `site_api_discovery.py`, `site_api_budget.py`, `site_api_foresight.py`, `site_api_social.py`, `site_api_body.py`, `site_api_journey.py`, `site_api_character.py`, `site_api_sleep.py`, `site_api_biomarkers.py`, the `site_api_coach_*.py` family (profile · stance · ledger · narrative), `site_api_nutrition.py`, `site_api_habits.py`, `site_api_edition.py`, `site_api_data.py` (guarded by `tests/test_site_api_data_split.py`). Several are thin **facades** (`site_api_intelligence.py`, `site_api_vitals.py`, `site_api_coach.py`) that delegate to a sibling and keep the router bindings stable. The list is `ls lambdas/web/site_api_*.py`; line counts are deliberately not stated (they rotted within weeks). Each module's docstring names the `/api/*` routes it owns.

All of these ship together via the standard `Code.from_asset("../lambdas")` zip. `/api/ask` + `/api/board_ask` are served by the separate `life-platform-site-api-ai` Lambda (ADR-036).

**Routes served via CloudFront → site-api:**
- `GET /api/vitals` — weight, HRV, recovery (TTL 300s)
- `GET /api/journey` — weight trajectory, goal date (TTL 3600s)
- `GET /api/character` — pillar scores, level, per-pillar `score_delta`/`xp_earned` (Day-Grade Replay). Reads the **latest available** `character_sheet` `DATE#` record + its prior (compute writes the prior day at ~16:30 UTC, so the freshest record is routinely 1-2 days old; a today/yesterday-only window 503'd ~16h/day — fixed 2026-06-05). TTL 900s.
- `GET /api/source_freshness` — per-source pipeline status (fresh/stale/behavioral-stale/paused), feeds the `/evidence/pipeline/` topic (TTL 300s)
- `GET /api/timeline` — weight history + events
- `GET /api/correlations` — pre-computed correlation pairs
- `GET /api/weight_progress` — 180-day weight series
- `GET /api/experiments` — N=1 experiment list
- `GET /api/current_challenge` — weekly challenge ticker
- `POST /api/ask` (served by `life-platform-site-api-ai`) — AI Q&A (Haiku 4.5), 3 anon / 20 subscriber q/hr
- `POST /api/board_ask` — board AI, up to the full 7-coach roster in parallel (Haiku 4.5), 7/hr IP fan-out budget (#3419)
- `GET /api/verify_subscriber?email=` — HMAC token for subscriber gate (24hr)
- `POST /api/subscribe` — email subscriber capture (served by the `email-subscriber` Lambda, not site-api)

**Rate limiting:** DynamoDB-backed per-IP atomic counters (`lambdas/common/rate_limiter.py`, since Phase 2.1 — survives warm-container distribution). The module-level dicts `_ask_rate_store`/`_board_rate_store` are the in-memory fail-open fallback only (used if the DDB limiter is unavailable). Vote/follow rate limits also use DynamoDB atomic counters with TTL. Role is primarily read-only with limited writes for interactive features (votes, follows, checkins).

### Email / Intelligence cadence

Schedules are fixed UTC (no DST drift) except `daily-brief`, which is zoned to America/Los_Angeles (#4284); the PDT column is the UTC-7 rendering. The cron
column is diffed against `cdk/stacks/*.py` by `scripts/check_doc_facts.py` (#1205), so a
schedule change that skips this table reds CI.

| Lambda | Schedule (UTC) | Time (PDT) | Purpose |
|---|---|---|---|
| `anomaly-detector` | `cron(5 15 * * ? *)` | 8:05 AM daily | 15 metrics, CV-based Z thresholds |
| `daily-brief` | `cron(0 10 * * ? *)` America/Los_Angeles (zoned, #4284) | 10:00 AM daily | 18-section brief, 4 Haiku calls |
| `monday-compass` | `cron(0 15 ? * MON *)` | Mon 8:00 AM | Forward-looking planning + Todoist |
| `wednesday-chronicle` | `cron(0 15 ? * WED *)` | Wed 8:00 AM | Elena Voss narrative, blog + email |
| `weekly-plate` | `cron(0 2 ? * SAT *)` | Fri 7:00 PM | Food magazine column |
| `weekly-digest` | `cron(0 16 ? * SUN *)` | Sun 9:00 AM | 7-day summary, Board commentary |
| `nutrition-review` | `cron(0 17 ? * SAT *)` | Sat 10:00 AM | Deep Sonnet nutrition analysis |
| `hypothesis-engine` | `cron(0 19 ? * SUN *)` | Sun 12:00 PM | IC-18 hypothesis generation |

### Coach Intelligence Layer (v6.0.0)

The operational coaches generate daily analyses through a multi-stage pipeline. Each coach has a persistent voice, relationship state, and confidence model stored in DynamoDB. The coach pipeline replaces the legacy `ai_expert_analyzer_lambda.py` (deprecated).

**The roster is data, not prose** (coaching-team v2, ADR-153): the identities are `config/personas.json`; `lambdas/coach/persona_registry.py` derives the id lists (`OPERATIONAL_COACH_IDS`, `CONSULTING_COACH_IDS`, `CHAT_COACH_IDS`, `RETIRED_COACH_IDS`, `LEAD_PERSONA_ID`), and `tests/test_persona_registry.py` is the contract. The paved path to change it is [ADD_A_COACH.md](ADD_A_COACH.md); the people behind each seat are in [BOARDS.md](BOARDS.md). At this verification the operational ids are `sleep_coach`, `nutrition_coach`, `mind_coach`, `physical_coach`, `glucose_coach` (consulting), `labs_coach` (consulting) and `explorer_coach`; `pattern_coach`, `career_coach` and the lead `eli_marsh` are the chat tier; `training_coach` is retired (the Performance seat absorbed it at the cycle-13 genesis).

**Pipeline Lambdas (the core set; `compute_stack` also carries `coach-daily-reflection`, `coach-memoir`, `coach-vision`, `inter-coach-dialogue` and `voice-fidelity-harness`):**

| Function | Lambda | Purpose |
|----------|--------|---------|
| Computation Engine | `coach-computation-engine` | EWMA metrics, seasonal adjustments, anomaly detection per coach domain |
| Narrative Orchestrator | `coach-narrative-orchestrator` | Generates coach prose with voice spec, thread continuity, and epistemological framing |
| State Updater | `coach-state-updater` | Updates relationship state, confidence scores, and learning records |
| Ensemble Digest | `coach-ensemble-digest` | Cross-coach synthesis, disagreement detection, influence graph |
| Prediction Evaluator | `coach-prediction-evaluator` | Scores past predictions, calibrates confidence |
| History Summarizer | `coach-history-summarizer` | Compresses old threads into COMPRESSED#latest |
| Quality Gate | `coach-quality-gate` | **BLOCKING** as of N-06 (#390, 2026-07-05) — invoked synchronously from `ai_calls._run_coach_v2_pipeline` after each COACH-V2 generation. A sub-threshold draft is regenerated once (`_enforce_quality_gate`); still-failing drafts are held (no publish) instead of shipping. Was advisory-only (async, report discarded) v51 (2026-05-19) → N-06; see ADR-107. |
| Observatory Renderer | `coach-observatory-renderer` | Renders coach analysis for /api/coach_analysis endpoint (replaces ai_expert_analyzer) |

**Pipeline flow:** Computation Engine -> Narrative Orchestrator -> Quality Gate -> State Updater -> (async) Ensemble Digest + Prediction Evaluator + History Summarizer. Results stored to `COACH#` and `ENSEMBLE#` DynamoDB partitions and served via `/api/coach_analysis`.

**Observatory integration:** `observatory-v3.js` calls `/api/coach_analysis?coach=<id>` first, with automatic fallback to legacy `/api/ai_analysis?expert=<key>` if the new endpoint is unavailable.

**S3 config:** Voice specifications at `config/coaches/<coach_id>.json` (+ `*_stance.json` stance specs and `_shared_standard.json`), influence graph at `config/coaches/influence_graph.json`, computation params at `config/computation/ewma_params.json` + `config/computation/seasonal_adjustments.json`, narrative arcs at `config/narrative/arc_definitions.json`.

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

Role categories (counts are deliberately not stated — they are the per-stack `role_policies_*.py` modules in `cdk/stacks/` and the functions in `model/platform_model.json`):
- **Ingestion roles:** DDB write, S3 write, Secrets read, SQS DLQ (`role_policies_ingestion.py`)
- **MCP role:** DDB CRUD + S3 `config/*` + `raw/matthew/cgm_readings/*` + `life-platform/todoist` read
- **Email/digest roles:** DDB read/write, ai-keys, SES, S3 write (`role_policies_email.py`)
- **Compute roles:** DDB read/write, ai-keys (`role_policies_compute.py`)
- **Coach Intelligence roles:** DDB read/write on COACH#/ENSEMBLE#/NARRATIVE# partitions, S3 read on config/coaches/*, ai-keys
- **Operational roles:** scoped per function (`role_policies_operational.py`)
- **Site API role:** DDB primarily read-only (`GetItem, Query`) + limited `PutItem` for interactive features (votes, follows, checkins), `kms:Decrypt`, S3 `site/config/*`, Secrets read (`site-api-ai-key` only) — **NO Scan**
- **`dynamodb:Scan` is granted, deliberately, to exactly three operational roles** (`cdk/stacks/role_policies_operational.py`, re-exported by the `role_policies.py` facade): `life-platform-data-export` and `life-platform-data-reconciliation` (whole-table reads are their job) and `life-platform-delete-user-data` (it must find every item belonging to a user). No serving, ingest, compute or coach role has it. The un-audited fallback branch in `lambda_helpers.py` also lists Scan, but no deployed function reaches it — every function passes either `custom_policies=` or an explicit `role=`.
- No role has cross-account permissions

---

## Secrets Manager

**26 active secrets** at $0.40/month each = **~$10.40/month**

The count and the table below must agree, and the count's `live-verified` stamp must be under 90 days old — both enforced by `scripts/check_doc_facts.py` (#1957). Re-verify against AWS with `python3 deploy/sync_doc_metadata.py --refresh-secrets` (read-only), then `--apply` to propagate. Per-secret consumers, rotation procedures and the retire ledger live in [SECRETS_MAP.md](SECRETS_MAP.md).

| Secret | Used By |
|---|---|
| `life-platform/whoop` | Whoop Lambda — OAuth2 tokens |
| `life-platform/withings` | Withings Lambda — OAuth2 tokens |
| `life-platform/strava` | Strava Lambda — OAuth2 tokens |
| `life-platform/garmin` | RETIRED (#4640) — no consumer; owner-attended delete pending |
| `life-platform/eightsleep` | Eight Sleep Lambda — username + password |
| `life-platform/eightsleep-client` | Eight Sleep Lambda — client credential alongside user creds |
| `life-platform/ai-keys` | Legacy direct-API fallback across the intelligence/email Lambdas — Anthropic API key (Bedrock/IAM is the primary path, ADR-062) |
| `life-platform/ingestion-keys` | Notion, Todoist, Habitify, Dropbox, HAE webhook — COST-B bundle (sole source for Dropbox) |
| `life-platform/habitify` | Habitify Lambda — dedicated key (ADR-014) |
| `life-platform/todoist` | MCP write tools — Todoist API token (TD-23, added to MCP IAM 2026-05-02) |
| `life-platform/notion` | **LIVE** — referenced by `life-platform-freshness-checker` + `pipeline-health-check`; journal ingestion reads the bundle. Retire-candidate, unresolved: see `docs/SECRETS_MAP.md` |
| `life-platform/hevy` | Hevy ingestion — read API key (ADR-060) |
| `life-platform/hevy-write` | MCP routine tools — Hevy write key |
| `life-platform/mcp-api-key` | MCP Key Rotator — bearer token (90-day auto-rotation) |
| `life-platform/site-api-ai-key` | Site API Lambda — dedicated Anthropic key (R17-04, isolated from main ai-keys) |
| `life-platform/site-api-origin-secret` | CloudFront ↔ site-api origin verification header (CDK-injected) |
| `life-platform/subscriber-token-secret` | Site API — HMAC signing for subscriber tokens |
| `life-platform/ritual-token-secret` | Site API + `evening-nudge` — HMAC signing for ritual links |
| `life-platform/github-dispatch-token` | `life-platform-remediation-dispatcher` — repo-scoped PAT |
| `life-platform/github-billing` | `deploy/sentinel_quota.py` — Actions-minutes quota probe (user-scoped PAT) |
| `life-platform/google-tts` | Podcast pipeline — TTS credentials (ADR-087) |
| `life-platform/pexels` | Editorial image fetcher — free-tier API key |
| `life-platform/youtube` | `youtube-social-ingestion` — owner-provisioned channel id |
| `life-platform/bluesky` | Syndication — handle + scoped app password (`docs/RUNBOOK_SYNDICATION.md`) |
| `life-platform/digest` | `milestone-digest` — operator-configured recipient list (kept out of git) |
| `life-platform/telegram` | Telegram coach chat (#2364) — per-bot tokens, chat-id allow-list, webhook secret |
| ~~`life-platform/dropbox`~~ | **DELETED** — window closed 2026-05; the `ingestion-keys` bundle is authoritative |
| ~~`life-platform/anthropic-api-key`~~ | **DELETED** — window closed 2026-05 (orphan, no consumer in source) |
| ~~`life-platform/webhook-key`~~ | **HARD-DELETED 2026-03-14** |
| ~~`life-platform/google-calendar`~~ | **HARD-DELETED 2026-03-15 (ADR-030)** |
| ~~`life-platform/api-keys`~~ | **HARD-DELETED 2026-03-14** |

**Not yet created (owner-provisioned, deliberately absent from the table above — the
count is live-verified and this secret does not exist in AWS yet):**
`life-platform/continuity-contacts` — the Permanence Contract's continuity contacts
(#1400, `docs/PERMANENCE_CONTRACT.md` clause P7). Real people's addresses, so it never
enters git. Until it exists the switch is disarmed but honest: transition notices go to
the operator address and the run reports `contacts_configured: false`. Add it to the
table and bump `secret_count` when it is created.

`life-platform/ip-hash-salt` — the salt for the reader `ip_hash` on every site-api
engagement door (#3620, security ROW4): `/api/nudge`, `/api/submit_finding`,
`/api/board_question`, `/api/predict`, `/api/ritual_log`, `/api/verify_subscriber`.
Read at runtime through `common/secret_cache` (15-min TTL) by
`web/site_api_social_engage._salted_ip_hash`, and granted to the site-api role by the
`IpHashSalt` statement in `cdk/stacks/role_policies_serve.py`. A random value, created
by the owner — never in git, because a salt committed to a PUBLIC repo is strictly
worse than none (it reads as a fix). **Until it exists those six doors answer 503**,
which is the fix working: there is deliberately no unsalted fallback, since the
fallback would keep writing a reversible digest into S3, a DynamoDB sort key and
CloudWatch on exactly the days the control was broken. Add it to the table and bump
`secret_count` when it is created.

---

## Cost Profile

Target: within the **$215/mo all-in budget ceiling** (ADR-063; surge-to-$252 per ADR-133). The canonical spend ledger is [COST_TRACKER.md](COST_TRACKER.md) (Monthly Actuals + the monthly close, measured from Cost Explorer); the **live** tier is never stated here — read it from SSM `/life-platform/budget-tier`, which `life-platform-cost-governor` rewrites every 8h.

There is deliberately **no per-driver cost table here**: a hand-maintained copy understated CloudWatch ~6x and the monthly total ~2x before it was removed (#3371). The per-driver breakdown lives in [COST_TRACKER.md](COST_TRACKER.md)'s monthly close, measured from Cost Explorer under a 45-day freshness gate — read it there.

---

## Local Project Structure

```
~/dev/life-platform/
  mcp_server.py                   ← MCP Lambda entry point
  mcp_bridge.py                   ← Local MCP adapter (Claude Desktop → Lambda HTTPS)
  mcp/                            ← MCP server package (38 tool modules + helpers)
    handler.py, config.py, utils.py, core.py, helpers.py, registry.py, warmer.py, …
    tools_<domain>.py               ← one module per tool domain (`ls mcp/tools_*.py`);
                                      tools are wired in registry.py's TOOLS dict
    # tools_calendar.py DELETED V2 (ADR-030 retired Google Calendar)

  lambdas/                          ← packaged by domain (ADR-146); no loose root modules
    ingestion/  compute/  emails/  web/  operational/  intelligence/  reading/   ← handlers
    common/  ai/  experiment/  coach/  health/  training/  content/  privacy/      ← shared code
    cf-auth/ (Lambda@Edge) · dashboard/ · fonts/ · requirements/ (dependency layers)
    # function inventory by stack: model/platform_model.json (never restated here)
    # e.g. ai/ai_calls.py (AI-call layer) · common/retry_utils.py · common/secret_cache.py ·
    #      health/scoring_engine.py · content/output_writers.py · content/site_writer.py ·
    #      coach/board_loader.py · content/insight_writer.py

  site/                           ← static website (averagejoematt.com)
    index.html                    ← Home
    cockpit/ data/ coaching/ protocols/ story/   ← the five doors (v5 IA)
    method/ gear/ mind/ journal/ privacy/ subscribe*  ← footer-tier + reader pages
    next/ kit/                    ← the preview path and the v8 component kit
    legacy/                       ← pre-v4 site, private rollback (never linked)
    assets/                       ← css/js design system (tokens.css, …)
    # pages are generated: scripts/v4_build_*.py → change the generator, then regenerate

  docs/                           ← All documentation
  deploy/                         ← deploy, restart-pipeline and doc-sync scripts (deploy_fleet.sh, cdk_deploy.sh, …)
  cdk/                            ← 10 CDK stacks
  tests/                          ← the pytest suite (live count: docs/TESTING.md); structural/CI gates in tests/ and scripts/check_*.py
  handovers/                      ← The live session pointer (HANDOVER_LATEST.md); history on the session-archive branch
```

---

**Verified:** 2026-10-17 — re-verified against the tree (#1348): coach roster, ingestion census, site-api layout, local structure, HAE API id (live read-only `apigatewayv2 get-apis`), CloudFront/SES/SQS/CloudTrail/SNS names and the concurrency quota (100, live read-only). Lambda/tool/alarm/ADR counts via `deploy/sync_doc_metadata.py` discoverers (AST); secret list via `aws secretsmanager list-secrets`. NOT re-verified in this pass: the IC feature census, the Hevy write-loop prose, the daily-brief "18-section / 4 Haiku calls" description, and the Experiment Phase Filtering call-site tally. The retired-layer version check is gone — the invariant is now zero layer references (CI plan job + I2).


### Experiment Phase Filtering

**Default deny pilot.** Every Query/Scan that fans-in via `_query_source` (site-api)
or `query_source` (mcp/core) automatically appends a FilterExpression that hides
`phase=pilot` records. Items without a `phase` attribute pass through (cross-phase
identity records, plus historical writes that pre-date ADR-058).

Direct `table.query` call sites that bypass the chokepoints are individually
wrapped in `intelligence_common.py` and in the spec-named site-api endpoints
(`handle_timeline`, `handle_correlations`). ~110 secondary call sites remain
unwrapped — most operate on post-genesis date ranges where pilot exposure is
not a concern. Tracked as a follow-up sweep.

Callers can pass `include_pilot=True` to bypass the filter (research / audit use).
