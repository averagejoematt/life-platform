# Life Platform — Onboarding Guide

> **Status:** canonical · **Owner:** Matthew · **Verified:** 2026-05-19

> First-day mental model. For commands (AWS auth, deploy, rollback), see `docs/QUICKSTART.md`.
> Last updated: 2026-06-08 (v8.4.0 — v4 front-end live; ADR-077 phase taxonomy + ADR-078 commercial wedge; PG front-door work)
>
> **Resuming a Claude chat session?** Read `handovers/HANDOVER_LATEST.md` first — that's the canonical "what's the current state" doc. This file is the slower onboarding for a fresh contributor.

---

## What Is This Platform?

A personal health intelligence system built on AWS for a single user (Matthew). It pulls data from ~20 API/webhook/manual sources (wearables, apps, labs, manual uploads), stores everything in a single DynamoDB table, runs a deterministic computation pipeline + an 8-agent coaching layer, and exposes 64 MCP tools so Claude can answer natural-language health questions against real data.

The end result: ask Claude a question about your health, and it queries actual readings rather than relying on memory or estimates.

Public surface: `averagejoematt.com` — the v4 "The Measured Life" site (ADR-071): three doors over the engine — **Cockpit** (`/now/`, live data), **Story** (`/story/`, the writing), **Evidence** (`/evidence/`, the data archive), with a cinematic landing at `/`. The pre-v4 site is preserved verbatim at `/legacy` (private rollback). Served static from S3 + CloudFront; the engine is read-only from the front-end.

---

## High-Level Data Flow

```
19 sources (API + webhook + manual)
    │
    ▼
14 ingestion Lambdas (8 SIMP-2 framework + 6 pattern-exempt — ADR-056)
  • EventBridge cron (hourly 4am–10pm PT; Garmin 4x/day; Weather + Todoist 2x/day)
  • HAE webhook (CGM, BP, water, State of Mind — near real-time)
  • S3 triggers (apple_health XML, macrofactor CSV, measurements)
    │
    ▼
Raw JSON in S3 (`raw/{source}/{datatype}/{YYYY}/{MM}/{DD}.json`)
  + DynamoDB single-table (`life-platform`)
      PK = USER#matthew#SOURCE#{source}
      SK = DATE#YYYY-MM-DD
    │
    ▼
5 compute Lambdas (10:20–10:35 AM PT, pre-compute):
  character-sheet · adaptive-mode · daily-metrics-compute ·
  daily-insight-compute · hypothesis-engine
    │
    ▼
Coach Intelligence pipeline (deterministic math → 8 parallel LLM coaches):
  coach-computation-engine → coach-narrative-orchestrator →
  8 coach generations → coach-quality-gate (BLOCKING, N-06 #390 — regenerate-or-
  hold, sync) → coach-state-updater → coach-ensemble-digest →
  coach-prediction-evaluator (9 AM PT, daily)
    │
    ▼
7 email Lambdas (daily-brief at 17:00 UTC (10 AM PDT), weekly digests, chronicle, etc.)
  + og-image-generator (11:30 AM PT, 6 PNG share cards)
  + site-stats-refresh (writes public_stats.json)
    │
    ▼
MCP Lambda (64 tools) ← Claude Desktop + claude.ai + mobile via remote MCP
site-api Lambda (60+ endpoints, primarily read-only — ADR-037) ← averagejoematt.com
```

~94 Lambdas (CDK-defined; includes 4 us-east-1 edge/auth functions). 9 CDK stacks. Run-rate: ~$25–40/mo against an $85 enforced ceiling (ADR-063/133 — see `docs/COST_TRACKER.md`).

---

## Key Services You'll Interact With

| Service | Purpose | When you touch it |
|---------|---------|-------------------|
| **DynamoDB** (`life-platform`) | Single-table store for all source data, computed metrics, coach state | Read paths via MCP tools; writes via ingestion + compute Lambdas only |
| **S3** (`matthew-life-platform`) | Raw archives + Lambda-generated content + site assets | `raw/`, `generated/`, `site/`, `uploads/`, `config/`, `cloudtrail/` — see ADR-046 for prefix separation |
| **Lambda** (~94 CDK-defined) | All compute. Ingest, compute, coaches, email, MCP, site-api | Deploy with `deploy/deploy_lambda.sh` (single function), `deploy/deploy_fleet.sh` (shared-module change), or `cdk deploy <StackName>` (infra changes) |
| **EventBridge** | All cron schedules, fixed UTC (no DST drift) | CDK-managed only — never create rules via Console |
| **Secrets Manager** (`life-platform/*`) | All credentials | 21 active secrets. See `docs/SECRETS_MAP.md` |
| **CloudFront** (4 distributions) | CDN for `averagejoematt.com`, `dash`, `blog`, `buddy` | S3 website endpoint origins (ADR-053/054). Site syncs invalidate via CDK helpers |
| **MCP Lambda** | 64 tools across 23 domain modules in `mcp/` | The interface Claude uses to query data |
| **Anthropic API** | Coach generation + daily brief sections | Prompt caching enabled (ADR-049); Haiku for structured, Sonnet for narrative |

---

## Key Mental Models

### 1. Single-table DynamoDB (ADR-001)

Every data source writes to one table: `life-platform`.

```
PK: USER#matthew#SOURCE#<source>   (e.g. USER#matthew#SOURCE#whoop)
SK: DATE#YYYY-MM-DD
```

Coach state, ensemble digests, narrative arcs, predictions, and learning records live in dedicated PK prefixes (`COACH#`, `ENSEMBLE#`, `NARRATIVE#`, `PREDICTION#`, `LEARNING#`). No GSI by design (ADR-005). All partition writes use UTC midnight (ADR-050).

### 2. Ingest → Store → Compute → Serve, with strict ordering

EventBridge enforces the timing:

```
06:45–09:00 AM PT   Ingestion (14 Lambdas — APIs, webhooks, S3 triggers)
09:05  AM PT        Anomaly detector
10:20–10:35 AM PT   Compute (5 pre-compute Lambdas + coach pipeline)
11:00  AM PT        Daily Brief email (reads pre-computed results)
11:30  AM PT        OG image cards (reads public_stats.json)
```

If compute runs before ingestion completes, it uses yesterday's data. If the brief runs before compute, it reads stale results. Compute Lambdas degrade gracefully — a missing section won't fail the brief.

### 3. MCP tools are primarily read-only

The MCP Lambda queries DynamoDB and returns results. Writes only happen via dedicated tools (`log_supplement`, `write_platform_memory`, `log_journal_entry`, etc.). Tools never write to source ingestion partitions.

### 4. CDK owns infrastructure

Never create Lambda roles, EventBridge rules, secrets, or alarms manually. Everything goes through `cdk/stacks/`. Run `cd cdk && npx cdk deploy <StackName>` after code changes affecting IAM or scheduling.

### 5. Secrets are in Secrets Manager only

No credentials in code or environment variables. All secrets live under prefix `life-platform/` in Secrets Manager. Auto-rotation for `mcp-api-key`; auto-refresh on use for OAuth tokens.

### 6. Coaches are stateful agents, not stateless prompts (ADR-047)

The 8 coaches are persistent agents with episodic memory, voice differentiation, cross-coach awareness, and Bayesian prediction accountability. All math happens in the deterministic computation engine — the LLM never does math. The prediction loop is closed end-to-end as of ADR-055 (May 2026).

The 8 coach IDs (from `lambdas/coach_computation_engine.py:COACH_IDS`):
`dr_johansson` · `fitness_coach` · `nutrition_coach` · `mind_coach` · `sleep_coach` · `body_comp_coach` · `lifestyle_coach` · `recovery_coach`

These are the Coach Intelligence pipeline identities. The advisor *personas* used in emails/observatory (Dr. Sarah Chen, Dr. Marcus Webb, etc.) are configured separately in `s3://matthew-life-platform/config/board_of_directors.json` and bound to data domains — see `docs/BOARDS.md`.

### 7. S3 prefix separation makes site deploys safe (ADR-046)

Lambda-generated files (`public_stats.json`, OG images, journal posts) live under `generated/`. Static HTML/CSS/JS live under `site/`. `aws s3 sync site/ --delete` physically cannot touch `generated/*` — they're disjoint prefixes. Bucket policy also denies `DeleteObject` on `raw/*`, `config/*`, `uploads/*`, `generated/*` for the deploy user.

### 8. Site-website CloudFront uses S3 website endpoints + AES256 (ADR-053/054)

Don't try to migrate to KMS default encryption — S3 website endpoints can't serve KMS-encrypted objects. The CMK is retained for explicit-KMS use cases (e.g., `raw/` archives) but is **scheduled for deletion 2026-06-16** unless re-justified.

---

## Where Do I Look For X?

| If I want to find... | Look here |
|----------------------|-----------|
| Why a decision was made | `docs/DECISIONS.md` (78 ADRs, ADR-001 → ADR-078) |
| How to deploy / roll back | `docs/QUICKSTART.md` + `docs/RUNBOOK.md` |
| What field a source writes to | `docs/SCHEMA.md` |
| Full system inventory (Lambdas, alarms, secrets, KMS) | `docs/ARCHITECTURE.md` |
| Cost guardrails + recent spend | `docs/COST_TRACKER.md` |
| How to run an audit / review | `docs/REVIEW_METHODOLOGY.md` |
| PII classification + retention | `docs/DATA_GOVERNANCE.md` |
| AI persona definitions | `docs/BOARDS.md` (3 boards: Personal, Technical, Product) |
| MCP tool list | `docs/MCP_TOOL_CATALOG.md` |
| Latest session context | `handovers/HANDOVER_LATEST.md` |
| V2 audit findings + outcomes | `docs/archive/V2_AUDIT_PLAN.md` |
| Incident write-ups | `docs/INCIDENT_LOG.md` + `docs/rca/` |
| Operator-grade procedures (alarms, runbooks) | `docs/OPERATOR_GUIDE.md` + `docs/RUNBOOK.md` |
| Schema for a single S3 prefix or table partition | `docs/SCHEMA.md` |
| SLOs + error budgets | `docs/SLOs.md` |

---

## The Data Sources (19)

| Category | Sources |
|----------|---------|
| Wearables | Whoop (recovery, HRV, sleep), Eight Sleep (bed environment), Garmin (steps, body battery), Withings (weight, body composition) |
| Fitness | Strava (activities, training load) |
| Nutrition | MacroFactor (calories, macros, food log via Dropbox CSV) |
| Health tracking | Apple Health via Health Auto Export webhook (CGM, blood pressure, gait, steps, State of Mind) |
| Productivity | Todoist (tasks), Notion (journal) |
| Lifestyle | Habitify (habits), Weather (Open-Meteo) |
| Manual/periodic | Labs (blood work), DEXA (body comp scan), Genome (SNPs), Supplements, Measurements (S3 trigger), Food Delivery (quarterly CSV) |
| Derived | Day grade, Habit scores, Character sheet, Computed metrics |

V2 outcome (2026-05-17): SIMP-2 ingestion framework now adopted by 8 Lambdas; 6 pattern-exempt (Notion, MacroFactor, Apple Health, HAE, Dropbox, Food Delivery) per ADR-056 with documented per-source rationale.

---

## Session Handover Protocol

Every development session ends with a handover file written to `handovers/`. Ask Claude:

> "Write a session handover"

The handover captures: version bump, what changed, what's pending, and context for the next session. This is how context is preserved across Claude's session limits. Handovers live at `handovers/YYYY-MM-DD-session<N>-<slug>.md`; the latest is referenced from `handovers/HANDOVER_LATEST.md`.

---

## Where Things Go Wrong

| Symptom | Likely cause | Fix |
|---------|-------------|-----|
| Withings data gap | OAuth token expired | `python3 setup/fix_withings_oauth.py` |
| Garmin gap | OAuth rate-limited (429) — known weakness | Wait for backoff, then re-auth manually |
| Daily Brief missing sections | Compute Lambda failed upstream | CloudWatch logs for `daily-metrics-compute` |
| MacroFactor data stale | CSV not dropped to Dropbox folder | Export from MacroFactor → drop to Dropbox |
| MCP tool timeout | Query too broad or cold start | Narrow date range; wait for warm container |
| CDK deploy fails with IAM error | Policy change blocked by CI lint | Check `tests/test_iam_secrets_consistency.py` |
| Freshness checker alarm firing | Source hasn't updated in >48h | Check source Lambda logs; may need manual backfill |
| Site shows stale gauges | `public_stats.json` not refreshed | Check `daily-brief` + `site-stats-refresh` logs |
| Coach output looks degraded | `coach-quality-gate` flagged it | Check `COACH#<id>` `OUTPUT#` records for revision flags |

---

## Architecture Review Cadence

Reviews are run from `docs/REVIEW_METHODOLOGY.md`. The platform is at audit V2 (2026-05-17, 76 findings, ~33 shipped). V2 outcomes are captured in `docs/archive/V2_AUDIT_PLAN.md` and formally closed in **ADR-057**. Reviews stored in `docs/reviews/` and `docs/v2-audits/`. `python3 deploy/generate_review_bundle.py` produces the pre-compiled bundle Claude needs to conduct a fresh review.

---

## Glossary

| Term | Meaning |
|------|---------|
| **MCP** | Model Context Protocol — Claude's native tool interface. The MCP Lambda exposes 64 tools that Claude calls to query health data. |
| **IC** | Intelligence Capability — the platform's computed health features (IC-1 through IC-30). |
| **DLQ** | Dead Letter Queue — failed async Lambda invocations. Drained every 6 hours by `dlq-consumer`. |
| **SOT** | Source of Truth — which device/service owns each health domain (e.g., Whoop owns sleep). See `mcp/config.py`. |
| **PITR** | Point-in-Time Recovery — DynamoDB's 35-day rolling backup. |
| **CDK** | AWS Cloud Development Kit — Python IaC. 8 stacks in `cdk/stacks/`. |
| **P40** | Protocol 40 — the 65-habit personal framework tracked via Habitify. 9 P40 groups with T0/T1/T2 tier weighting. |
| **Character Sheet** | Gamified scoring aggregating 7 health pillars into a level 1-100 with RPG tiers (Foundation → Elite). |
| **Board of Directors** | Three boards: Personal (14 advisors), Technical (12), Product (8). All configured in S3 (Personal) or code (Tech/Product). See `docs/BOARDS.md`. |
| **Day Grade** | Daily score 0-100, A-F letter, computed from sleep, nutrition, exercise, habits, hydration, glucose. |
| **Coach Intelligence** | 8 persistent AI coaching agents with episodic memory, voice differentiation, cross-coach awareness, and Bayesian prediction accountability (ADR-047, ADR-055). |
| **COACH# partition** | DynamoDB partition (`COACH#<coach_id>`) storing each coach's outputs, voice state, learning log, and thread registry. |
| **ENSEMBLE# digest** | Cross-coach summary written after all 8 coaches generate (`ENSEMBLE#YYYY-MM-DD`). |
| **NARRATIVE# arc** | Multi-day story arcs and thematic assignments managed by the narrative orchestrator. |
| **PREDICTION# / LEARNING#** | Outcome verdicts and audit records for coach predictions (closed loop per ADR-055). |
| **SIMP-2** | Shared ingestion framework (`lambdas/ingestion_framework.py`) adopted by 8 of 14 ingestion Lambdas (ADR-056). |
| **Voice spec** | Structural definition of a coach's tone, vocabulary, sentence patterns. |
| **Computation engine** | Lambda (`coach-computation-engine`) that runs all deterministic math before coach generation. |
| **Narrative orchestrator** | Lambda (`coach-narrative-orchestrator`) — showrunner that assigns themes and sequences generation. |
| **Quality gate** | Lambda (`coach-quality-gate`) — invoked synchronously from `ai_calls._run_coach_v2_pipeline` after each COACH-V2 generation; blocking (regenerate-or-hold) as of N-06 (#390). |
| **Prediction evaluator** | Lambda (`coach-prediction-evaluator`) — scores past predictions against outcomes daily at 9 AM PT. |

---

## Key Architecture Assumptions (true but not obvious)

1. **Single-user platform.** All DynamoDB keys are `USER#matthew#...`. IAM roles, secrets, schedules — everything assumes one user. Do not generalize without reading ADR-001 + ADR-057 (the "Phase 6 multi-user" decision was formally deferred).
2. **Site-api is primarily read-only (ADR-037).** Limited writes for interactive features only (votes, follows, checkins, suggestions, user-submitted findings).
3. **`public_stats.json` is the website heartbeat.** Home, story, mission, observatory pages all read from this one S3 file, written by daily-brief at 11 AM PT. Daily brief failure = stale website data.
4. **All EventBridge crons are fixed UTC.** Schedules don't drift with DST. PT times in docs are for humans only.
5. **Pipeline ordering is strict.** Ingestion → Anomaly → Compute → Brief → OG. Changing schedules without preserving order produces stale results.
6. **Budget is $15/month target, $20 AWS Budget cap.** Current actual ~$13/month after V2 cost optimization (~$3.65/mo saved per Phase 5).
7. **Coaches are stateful entities with persistent memory and cross-coach awareness over 12 months.** All math happens in the deterministic computation engine — the LLM never does math.
8. **The KMS CMK (`alias/life-platform-s3`) is scheduled for deletion 2026-06-16.** Re-justify or let it expire — see ADR-053.

---

## Read These Next

1. `docs/QUICKSTART.md` — set up AWS, run tests, deploy a Lambda, check daily-brief output, roll back
2. `docs/ARCHITECTURE.md` — the full system catalog (every Lambda, alarm, secret, IAM role)
3. `docs/DECISIONS.md` — start with ADR-001, ADR-046, ADR-047, ADR-053, ADR-055, ADR-056, ADR-057
4. `docs/RUNBOOK.md` — daily operations + troubleshooting
5. `docs/SCHEMA.md` — DynamoDB field-by-field reference
6. `docs/BOARDS.md` — AI persona panels (Personal, Technical, Product)
7. `docs/DATA_GOVERNANCE.md` — PII tiers + retention
8. `docs/REVIEW_METHODOLOGY.md` — how to run an audit

---

**Verified:** 2026-05-19
