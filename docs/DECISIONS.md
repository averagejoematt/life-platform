# Life Platform — Architecture Decision Records (ADR)

> Permanent log of significant architectural, design, and operational decisions.
> Each ADR captures the decision, context, alternatives considered, and outcome.
> Last updated: 2026-06-03 (v8.3.0 — + Garmin retired & budget-guard/AI-cost trim; ADR-074/075)
> 94 ADRs total (ADR-001 → ADR-094). (Index table below covers ADR-001–057; newer ADRs are appended as detail sections in order.)

---

## How to Use This Document

When a significant decision is made — a design pattern chosen, an approach rejected, a tradeoff accepted — add a record here. The goal is to answer future-you's question: "Why did we do it this way?"

**Add a record when:**
- A data model pattern is chosen over alternatives
- A service is adopted or rejected (e.g., "why not Step Functions?")
- A cost/performance tradeoff is made deliberately
- A security boundary is drawn
- A feature is deliberately NOT built (non-decisions are as important as decisions)
- An approach is tried and abandoned with lessons learned

---

## ADR Index

| # | Title | Status | Date |
|---|-------|--------|------|
| ADR-001 | Single-table DynamoDB design | ✅ Active | 2026-02-23 |
| ADR-002 | Lambda Function URL over API Gateway for MCP | ✅ Active | 2026-02-23 |
| ADR-003 | MCP over REST API for Claude integration | ✅ Active | 2026-02-24 |
| ADR-004 | Source-of-truth domain ownership model | ✅ Active | 2026-02-25 |
| ADR-005 | No GSI on DynamoDB table | ⚠️ Amended by ADR-097 | 2026-02-25 |
| ADR-006 | DynamoDB on-demand billing over provisioned | ✅ Active | 2026-02-25 |
| ADR-007 | Lambda memory 1024 MB over provisioned concurrency | ✅ Active | 2026-02-26 |
| ADR-008 | No VPC — public Lambda endpoints with auth | ✅ Active | 2026-02-27 |
| ADR-009 | CloudFront + S3 static site over server-rendered dashboard | ✅ Active | 2026-02-27 |
| ADR-010 | Reserved concurrency over WAF | ✅ Active | 2026-02-28 |
| ADR-011 | Whoop as sleep SOT over Eight Sleep | ✅ Active | 2026-03-01 |
| ADR-012 | Board of Directors as S3 config, not code | ✅ Active | 2026-03-01 |
| ADR-013 | Shared Lambda Layer for common modules | ✅ Active | 2026-03-05 |
| ADR-014 | Secrets Manager consolidation — dedicated vs. bundled principle | ✅ Active | 2026-03-05 |
| ADR-015 | Compute→Store→Read pattern for intelligence features | ✅ Active | 2026-03-06 |
| ADR-016 | platform_memory DDB partition over vector store | ✅ Active | 2026-03-07 |
| ADR-017 | No fine-tuning — prompt + context engineering instead | ✅ Active | 2026-03-07 |
| ADR-018 | CDK for IaC over Terraform | ✅ Active | 2026-03-09 |
| ADR-019 | SIMP-2 ingestion framework: adopt for new Lambdas, skip migration of existing | ✅ Active | 2026-03-09 |
| ADR-020 | MCP tool functions BEFORE TOOLS={} dict | ✅ Active | 2026-02-26 |
| ADR-021 | EventBridge rule naming convention (CDK) | ✅ Active | 2026-03-10 |
| ADR-022 | CoreStack scoping — shared infrastructure vs. per-stack resources | ✅ Active | 2026-03-10 |
| ADR-023 | Sick day checker as shared utility, not standalone Lambda | ✅ Active | 2026-03-10 |
| ADR-024 | DLQ consumer: schedule-triggered vs SQS event source mapping | ✅ Active | 2026-03-14 |
| ADR-025 | composite_scores vs computed_metrics: consolidate into computed_metrics | ✅ Active | 2026-03-14 |
| ADR-026 | Local MCP endpoint: AuthType NONE + in-Lambda API key check (accepted) | ✅ Active | 2026-03-14 |
| ADR-027 | MCP two-tier structure: stable core → Layer, volatile tools → Lambda zip | ✅ Active | 2026-03-14 |
| ADR-028 | Integration tests as quality gate: test-in-AWS after every deploy | ✅ Active | 2026-03-14 |
| ADR-029 | MCP monolith: retain single Lambda, revisit at 100+ calls/day | ✅ Active | 2026-03-15 |
| ADR-030 | Google Calendar integration: retired — no viable zero-touch data path | ✅ Active | 2026-03-15 |
| ADR-031 | MCP Lambda deploy: always use full zip build (guard in deploy_lambda.sh) | ✅ Active | 2026-03-15 |
| ADR-032 | S3 bucket policy: Deny DeleteObject on data prefixes for deploy user | ✅ Active | 2026-03-16 |
| ADR-033 | Safe S3 sync: wrapper function with dryrun gate and root-block | ✅ Active | 2026-03-16 |
| ADR-034 | Website content consistency architecture (component system + constants) | ✅ Active | 2026-03-24 |
| ADR-035 | SIMP-1 tool consolidation: view-dispatchers over standalone tools | ✅ Active | 2026-03-09 |
| ADR-036 | 3-layer status monitoring architecture | ✅ Active | 2026-03-29 |
| ADR-037 | Site API read-only constraint | ✅ Active | 2026-02-27 |
| ADR-038 | In-memory rate limiting over DynamoDB counters — backstopped by WAF | ✅ Active | 2026-03-20 |
| ADR-039 | CSS/JS cache: content-hash filenames with 1-year immutable TTL | ⚠️ Extended by ADR-098 | 2026-03-29 |
| ADR-040 | Board of Directors: fictional advisors over real public figures | ✅ Active | 2026-03-26 |
| ADR-041 | Food delivery data: Delivery Index abstraction for privacy | ✅ Active | 2026-03-28 |
| ADR-042 | OG image generation: Lambda + Pillow over external services | ✅ Active | 2026-03-28 |
| ADR-043 | Challenge/Protocol/Experiment taxonomy: three behavioral tiers | ✅ Active | 2026-03-26 |
| ADR-044 | Measurements ingestion via S3 trigger over EventBridge cron | ✅ Active | 2026-03-29 |
| ADR-045 | SIMP-1 Phase 2: Accept 115 MCP tools as operating state | ✅ Active | 2026-03-30 |
| ADR-046 | S3 prefix separation: static vs generated content | ✅ Active | 2026-04-05 |
| ADR-047 | Coach Intelligence architecture: stateless prompts → stateful agents | ✅ Active | 2026-04-06 |
| ADR-048 | Observatory integration: Coach Intelligence replaces expert analyzer | ✅ Active | 2026-04-06 |
| ADR-049 | COST-OPT-2: prompt caching + strategic model downgrades | ✅ Active | 2026-04-09 |
| ADR-050 | TD-19: UTC as the platform-wide DDB partition convention | ✅ Active | 2026-05-03 |
| ADR-051 | WR-48: stale-source alerts + Anthropic canary (observability hardening) | ✅ Active | 2026-05-03 |
| ADR-052 | Two-tier alerting: urgent SNS + daily-batched digest | ✅ Active | 2026-05-16 |
| ADR-053 | S3 KMS rollback to AES256 — CloudFront website endpoint incompatibility | ✅ Active | 2026-05-17 |
| ADR-054 | CloudFront origins: S3 website endpoint over REST+OAC (status quo) | ✅ Active | 2026-05-17 |
| ADR-055 | Coach prediction loop closure: 4-step chain | ✅ Active | 2026-05-17 |
| ADR-056 | SIMP-2 ingestion framework: 8 sources migrated, 6 pattern-exempt | ✅ Active | 2026-05-17 |
| ADR-057 | V2 audit items formally closed with rationale | ✅ Active | 2026-05-17 |
| ADR-097 | Two GSIs for the reading domain (amends ADR-005) | ✅ Active | 2026-06-29 |
| ADR-098 | Content-hash the full JS module graph, not just HTML refs (extends ADR-039) | ✅ Active | 2026-07-03 |

---

## ADR-001 — Single-Table DynamoDB Design

**Status:** Active  
**Date:** 2026-02-23  
**Context:** Needed a data store for health data from 10+ sources. Options: one table per source, multi-table relational schema, or single-table design.

**Decision:** Single-table DynamoDB with composite PK: `USER#<id>#SOURCE#<source>` / SK: `DATE#YYYY-MM-DD`.

**Reasoning:** Single-table enables atomic cross-source reads in one query. On-demand pricing means no idle capacity waste on a 1-user system. Health data is time-series by nature — date-based SK enables efficient range queries. Relational joins for health analytics (e.g., "Whoop + Strava for last 30 days") would require application-side joins anyway.

**Alternatives considered:**
- One table per source: clean isolation but N round-trips for cross-source queries. Operational overhead scales with source count.
- Relational (RDS): ACID compliance not needed for health analytics. Cold starts, connection pools, VPC complexity for a Lambda-native platform — overkill.

**Outcome:** Single-table. No GSI by design — see ADR-005.

---

## ADR-002 — Lambda Function URL over API Gateway for MCP

**Status:** Active  
**Date:** 2026-02-23  
**Context:** MCP server needs an HTTPS endpoint that Claude can call. Options: API Gateway (HTTP or REST) or Lambda Function URL.

**Decision:** Lambda Function URL.

**Reasoning:** Function URLs have zero cold-start overhead from the routing layer (API GW adds ~5ms). No per-request API GW pricing ($3.50/million vs $0 for Function URL). The MCP endpoint doesn't need API GW features (no custom authorizers, no usage plans, no WAF — see ADR-010/TB7-26). Auth is handled in-Lambda via API key header.

**Alternatives considered:**
- REST API Gateway: richer feature set (WAF, throttling, usage plans) at $3.50/million extra. Not needed.
- HTTP API Gateway: cheaper than REST API GW but still adds routing overhead and per-request cost.

**Outcome:** Function URL. Currently using two: local (auth via x-api-key) and remote MCP (OAuth 2.1 + HMAC Bearer).

---

## ADR-003 — MCP over REST API for Claude Integration

**Status:** Active  
**Date:** 2026-02-24  
**Context:** Claude needs programmatic access to health data. Options: custom REST API Matthew queries manually, direct DynamoDB access, or MCP server.

**Decision:** MCP (Model Context Protocol) server with 88 typed tools.

**Reasoning:** MCP is Claude's native tool interface — no custom prompt engineering needed to invoke tools. Structured tool schemas with type validation prevent hallucinated queries. Tools can encapsulate complex DynamoDB queries behind clean interfaces. The MCP ecosystem enables claude.ai, Claude desktop, and mobile clients with the same codebase.

**Alternatives considered:**
- Custom REST API: requires manual prompt engineering on every query ("call /api/sleep?date=..."). Brittle.
- Direct DynamoDB queries in prompts: no structured schema enforcement. Claude has to construct queries from memory.

**Outcome:** MCP server. Currently 88 tools across 31 modules.

---

## ADR-004 — Source-of-Truth Domain Ownership Model

**Status:** Active  
**Date:** 2026-02-25  
**Context:** Multiple devices track overlapping metrics (e.g., Whoop + Garmin both track HR, sleep; Apple Health aggregates everything). Without a clear SOT model, tools return conflicting data.

**Decision:** Explicit SOT assignment per health domain in `config.py::_DEFAULT_SOURCE_OF_TRUTH`. One source owns each domain; others are secondary.

**Reasoning:** User trusts different devices for different things (Whoop for sleep/recovery, Garmin for stress/body battery, Apple Health for steps/CGM). Conflicting numbers confuse coaching AI. A single authoritative source per domain produces consistent coaching.

**Key assignments:** Sleep → Whoop (v2.55.0, ADR-011). Steps → Apple Health. Stress → Garmin. Nutrition → MacroFactor. Strength → Hevy. Journal → Notion.

**Outcome:** SOT model is live in `config.py` and enforced by MCP tools.

---

## ADR-005 — No GSI on DynamoDB Table

**Status:** Active  
**Date:** 2026-02-25  
**Context:** DynamoDB single-table design. Should we add Global Secondary Indexes for cross-source queries?

**Decision:** No GSI. All access patterns served by PK+SK queries only.

**Reasoning:** Every query so far is `pk = USER#matthew#SOURCE#X AND sk BETWEEN date1 AND date2`. GSIs add ~$0.10/GB/month per index and write amplification (each GSI is a separate write). For a 1-user system with ~100MB total data, the cost and complexity are not justified. If cross-source date queries are needed, the application layer can run N queries in parallel.

**Alternatives considered:**
- GSI on date: enables "all sources on date X" query. But this pattern isn't needed — the Daily Brief always fetches source-by-source.
- Sort key by source: restructures the PK entirely, making source-range queries efficient but date-range queries harder.

**Outcome:** No GSI. Revisit if table grows beyond 10GB or new access patterns emerge.

---

## ADR-006 — DynamoDB On-Demand Billing over Provisioned

**Status:** Active  
**Date:** 2026-02-25  
**Context:** DynamoDB billing mode: on-demand (pay per RCU/WCU) vs provisioned (pay for reserved capacity).

**Decision:** On-demand billing.

**Reasoning:** Traffic is bursty — 0 reads between midnight and 7 AM, then 50-100 reads during the morning pipeline, then near-zero until the next session. Provisioned capacity would idle at ~95% during off-hours. On-demand is more expensive per-read at high volume but cheaper overall for low-volume bursty workloads. At current scale (~$1/month DDB cost), provisioned savings would be pennies.

**Outcome:** On-demand. Switch to provisioned if monthly cost exceeds $5 from DDB alone.

---

## ADR-007 — Lambda Memory 1024 MB over Provisioned Concurrency

**Status:** Active  
**Date:** 2026-02-26  
**Context:** MCP server Lambda has cold starts of ~700-800ms. Options: higher memory (speeds cold start proportionally), provisioned concurrency (eliminates cold start), or status quo.

**Decision:** 1024 MB memory, no provisioned concurrency.

**Reasoning:** Provisioned concurrency costs ~$0.015/GB-hour — at 1024 MB, that's ~$11/month for a single always-warm Lambda. Cold starts are ~700-800ms on an interactive tool that's used occasionally. Matthew's workflow already tolerates the latency. The warm cache (13 tools pre-computed) means most tool calls complete in <100ms. Paying $11/month to shave 700ms from cold starts is not justified.

**Alternatives considered:**
- Provisioned concurrency: eliminates cold starts entirely. ~$11/month.
- SnapStart (Java only): not applicable.
- Increase memory to 2048 MB: halves cold start to ~350ms, doubles cost per invocation. Marginal improvement.

**Outcome:** 1024 MB, no provisioned concurrency. Revisit if usage pattern shifts to high-frequency interactive sessions.

---

## ADR-008 — No VPC — Public Lambda Endpoints with Auth

**Status:** Active  
**Date:** 2026-02-27  
**Context:** Should the Life Platform Lambdas run inside a VPC for network isolation?

**Decision:** No VPC. Public Lambda endpoints with application-level auth.

**Reasoning:** VPC adds ~200-500ms cold start penalty (ENI attachment). DynamoDB and Secrets Manager are accessed via VPC endpoints or public endpoints — adding VPC means adding VPC endpoints ($7.30/endpoint/month) to maintain performance. The platform has no multi-tenant exposure risk; the only sensitive data is Matthew's own health data, protected by Lambda auth and IAM. VPC complexity for a 1-user personal platform is disproportionate to the risk.

**Security posture without VPC:** Lambda endpoints protected by API key + HMAC. IAM roles with least-privilege per Lambda (SEC-1). DynamoDB KMS-encrypted. All traffic over HTTPS. CloudTrail logging. These controls are appropriate for the threat model.

**Outcome:** No VPC. Revisit if platform ever becomes multi-tenant or processes clinical-grade regulated health data.

---

## ADR-009 — CloudFront + S3 Static Site over Server-Rendered Dashboard

**Status:** Active  
**Date:** 2026-02-27  
**Context:** The platform needs a web dashboard for visual health data display. Options: server-rendered (Lambda + API GW), SPA (React/Vite + S3 + CloudFront), or simple static HTML + S3 + CloudFront.

**Decision:** Static HTML files generated by the Daily Brief Lambda, served via S3 + CloudFront with Lambda@Edge auth.

**Reasoning:** The dashboard is read-only (no user input) and updates once daily via the Daily Brief Lambda which writes `data.json`. No real-time interactivity needed — daily health metrics don't change between 11 AM and next morning. Static files served from S3 are essentially free ($0.50/month), have zero cold starts, and require no running server. Lambda@Edge provides auth without a dedicated auth service.

**Alternatives considered:**
- Server-rendered (Lambda): requires always-on or cold-start-tolerant API, adds auth complexity. No benefit for daily-cadence data.
- React SPA: build pipeline, node_modules, deployment complexity. No real benefit over vanilla JS for this use case.

**Outcome:** Static HTML (written by Daily Brief Lambda) + S3 + CloudFront. Dashboard at `dash.averagejoematt.com`.

---

## ADR-010 — Reserved Concurrency over WAF for MCP Endpoint

**Status:** Active  
**Date:** 2026-02-28  
**Context:** How to protect the MCP Lambda from runaway invocations or abuse?

**Decision:** Reserved concurrency limit (soft cap) + application-level API key auth. No WAF.

**Reasoning:** WAF (WebACL) cannot associate with Lambda Function URLs — only ALB, API GW, AppSync, Cognito, App Runner, Verified Access (confirmed TB7-26, 2026-03-13). Reserved concurrency of 10 means at most 10 concurrent executions; any beyond that get throttled by Lambda itself. The MCP endpoint is auth-protected — unauthenticated requests fail immediately. For a personal platform, WAF overhead is not justified.

**Note (TB7-26):** WAF was attempted in v3.7.9. AWS WebACL was created, association attempted, failed with "not a supported resource type", WebACL rolled back. ADR-010 confirmed as the correct architecture for this constraint.

**Outcome:** Reserved concurrency = 10. Application-level HMAC Bearer auth on remote MCP. No WAF.

---

## ADR-011 — Whoop as Sleep SOT over Eight Sleep

**Status:** Active  
**Date:** 2026-03-01  
**Context:** Both Whoop and Eight Sleep track sleep. Their scores frequently disagree. The Daily Brief, coaching AI, and scorecard all need a single authoritative sleep score.

**Decision:** Whoop is the SOT for sleep quality, duration, efficiency, staging, and recovery. Eight Sleep is the SOT for sleep environment only (bed temperature, HRV from pod, room conditions).

**Reasoning:** Whoop measures the sleeper (wrist-worn: HR, HRV, respiratory rate, movement). Eight Sleep measures the environment (mattress: movement, temperature, ambient HR). Whoop's sleep staging algorithm is purpose-built; Eight Sleep's sleep score is derived from environmental signals. Whoop recovery score has validated clinical correlation with HRV. When the two disagree, Whoop's data is more physiologically grounded.

**Eight Sleep retains SOT for:** `bed_temperature_c`, `mattress_temperature_c`, `environment_humidity`, and HR as a secondary cross-device signal.

**Outcome:** `_DEFAULT_SOURCE_OF_TRUTH["sleep"] = "whoop"`. Eight Sleep data ingested but not used as primary sleep score.

---

## ADR-012 — Board of Directors as S3 Config, Not Code

**Status:** Active  
**Date:** 2026-03-01  
**Context:** The 13-member AI persona panel (Board of Directors) was initially hardcoded in `daily_brief_lambda.py`. As the panel evolved (new members, changed contribution descriptions), code deploys were needed for persona changes.

**Decision:** Board of Directors configuration lives in `s3://matthew-life-platform/config/board_of_directors.json`. Lambdas read it via `board_loader.py` at runtime.

**Reasoning:** Persona changes are content decisions, not engineering decisions. Separating config from code means Matthew can update a board member's contribution description without a Lambda deploy. The S3 file is the single source of truth for which personas appear in which Lambda (daily_brief, weekly_digest, etc.) and with what role.

**Fallback:** If S3 read fails, `board_loader.py` returns `None` and Lambdas fall back to a hardcoded default panel (defensive coding pattern).

**Outcome:** `board_of_directors.json` in S3 config/. Consumed by `board_loader.py` in the Lambda Layer. All email Lambdas use it.

---

## ADR-013 — Shared Lambda Layer for Common Modules

**Status:** Active  
**Date:** 2026-03-05  
**Context:** `platform_logger.py`, `insight_writer.py`, `sick_day_checker.py`, `board_loader.py`, `retry_utils.py` are used across many Lambdas. Without a Layer, each Lambda bundles its own copy → stale copies when modules are updated.

**Decision:** `life-platform-shared-utils` Lambda Layer containing shared modules. All Lambdas reference the Layer; `deploy_lambda.sh` zips only the Lambda-specific source file.

**Reasoning:** Layer updates propagate to all consumers on next deployment (via `cdk deploy` or Lambda update). No stale module copies. Zip sizes smaller. The P0 incident of 2026-03-09 (13 Lambdas failing because platform_logger added `set_date()` and all had stale bundled copies) directly motivated this ADR.

**Current layer version:** `life-platform-shared-utils:4`

**Outcome:** Layer in use. `deploy_lambda.sh` automatically attaches the current layer version.

---

## ADR-014 — Secrets Manager: Dedicated vs. Bundled Principle

**Status:** Active  
**Date:** 2026-03-05  
**Context:** Some credentials serve multiple Lambdas (e.g., Notion + Todoist + Habitify all need API keys). Should each service get its own Secrets Manager secret, or should related keys be bundled?

**Decision:** Bundle only when the same set of credentials is consumed by the same Lambda set. Dedicated secrets when the consumer set diverges.

**Governing principle:** The cost of a dedicated secret ($0.40/month) is justified when it enables independent rotation, access control, or consumer isolation. Bundling is acceptable when all consumers have identical access needs and the bundle's scope is stable.

**Application:**
- `ingestion-keys`: Notion + Todoist + Habitify + Dropbox + HAE webhook key — bundled because all are consumed by ingestion Lambdas
- `habitify`: dedicated despite also appearing in `ingestion-keys` — because the Habitify Lambda is a separate consumer set (ADR-014 was the outcome of auditing this)
- `ai-keys`: Anthropic + MCP key — bundled because both consumed by email Lambdas

**Outcome:** 11 active secrets structured per this principle. `api-keys` (legacy over-broad bundle) permanently deleted 2026-03-14.

---

## ADR-015 — Compute→Store→Read Pattern for Intelligence Features

**Status:** Active  
**Date:** 2026-03-06  
**Context:** IC intelligence features need pre-processed data before the Daily Brief runs. Options: compute inline during Daily Brief, pre-compute in a separate Lambda, or cache in DynamoDB.

**Decision:** Dedicated compute Lambdas run before the Daily Brief, write results to DynamoDB, and the Brief reads the pre-computed output.

**Pattern:** `daily-insight-compute` (9:42 AM) → writes `SOURCE#computed_insights` → `daily-brief` (11:00 AM) reads it.

**Reasoning:** Computing inline during the Brief (already 4 AI calls, 120s+ runtime) risks timeout. Pre-computing separates concerns: compute Lambdas can retry independently, the Brief always reads from stable DDB state. The pattern also enables multiple consumers (Weekly Digest, Monday Compass all read `computed_metrics`).

**Outcome:** Compute → Store → Read is the standard IC pattern. Applied to: character sheet, daily metrics, daily insights, weekly correlations, adaptive mode, composite scores.

---

## ADR-016 — platform_memory DDB Partition over Vector Store

**Status:** Active  
**Date:** 2026-03-07  
**Context:** IC features need persistent memory (failure patterns, intention tracking, coaching calibration). Options: vector store (Pinecone, pgvector), dedicated memory Lambda, or DynamoDB structured records.

**Decision:** DynamoDB `SOURCE#platform_memory` partition with structured records. No vector store.

**Reasoning:** The platform's memory needs are structured, not semantic. "What happened last week" is a date-range query, not a similarity search. Vector stores add cost ($70-200/month for managed services), latency (network call to external service), and operational complexity. DynamoDB structured records can represent all needed memory types (milestones, intention tracking, failure patterns) as typed fields. AI prompts receive compact formatted blocks, not raw embeddings.

**Alternatives considered:**
- Pinecone / pgvector: semantic similarity search. Overkill — we always know what memory category we need, so fuzzy search provides no value.
- Fine-tuning: ruled out in ADR-017.
- In-context only (no persistence): coaching context resets daily, no compounding.

**Outcome:** DynamoDB memory partition. Currently live for milestone_architecture and intention_tracking categories.

---

## ADR-017 — No Fine-Tuning — Prompt + Context Engineering Instead

**Status:** Active  
**Date:** 2026-03-07  
**Context:** Claude has generic health coaching knowledge. Should we fine-tune a model on Matthew's data for more personalized coaching?

**Decision:** No fine-tuning. Personalization via structured context injection and prompt engineering.

**Reasoning:** Fine-tuning encodes knowledge at training time — it can't be updated with new data without re-training. Matthew's health data changes daily. A fine-tuned model from Week 1 would be wrong by Week 8. Context injection (profile.json, habit registry, journey week, recent metrics) provides current, accurate personalization on every call. Fine-tuning cost ($20-100/run minimum) is not justified when prompt engineering produces equivalent personalization with live data.

**Outcome:** IC system is entirely prompt-based. All "memory" is structured context injected into prompts. ADR-016 documents the memory storage approach.

---

## ADR-018 — CDK for IaC over Terraform

**Status:** Active  
**Date:** 2026-03-09  
**Context:** Platform has 43 Lambda IAM roles, 50+ EventBridge rules, 9 CloudWatch alarms. Infrastructure was managed manually via console/CLI. Options: CDK, Terraform, Pulumi, or SAM.

**Decision:** AWS CDK (Python).

**Reasoning:** CDK is Python-native — same language as all Lambdas, no context-switching. CDK constructs for Lambda, EventBridge, and CloudWatch are high-level and concise. Terraform requires HCL (a separate language) and is better suited for multi-cloud. SAM is Lambda-specific and less expressive for complex IAM policies. CDK's L2 constructs (`aws_lambda`, `aws_iam`) mirror the mental model of the platform exactly.

**Outcome:** 8 CDK stacks deployed (Core, Ingestion, Compute, Email, Operational, Mcp, Web, Monitoring). All 43 IAM roles CDK-owned.

---

## ADR-019 — SIMP-2 Ingestion Framework: Adopt for New, Skip Migration of Existing

**Status:** Active  
**Date:** 2026-03-09  
**Context:** `ingestion_framework.py` provides a standardized base class for ingestion Lambdas (gap detection, retry, DLQ, structured logging). All 13 existing ingestion Lambdas predate it. Should we migrate existing Lambdas?

**Decision:** Adopt `ingestion_framework.py` for all new ingestion Lambdas. Do not migrate existing 13 Lambdas.

**Reasoning:** The existing Lambdas are working correctly with their individual implementations. Migrating 13 Lambdas to a new base class introduces regression risk (each has slightly different field mapping, error handling, backfill logic) for zero user-visible benefit. The framework's value is consistency for future sources. `google_calendar_lambda.py` was the first Lambda written to use it.

**Outcome:** Framework adopted for new sources. Existing 13 Lambdas remain on their original patterns.

---

## ADR-020 — MCP Tool Functions MUST Come Before TOOLS={} Dict

**Status:** Active  
**Date:** 2026-02-26  
**Context:** MCP registry.py defines a `TOOLS = {}` dict at module level. When tool functions were defined AFTER the dict, Python raised `NameError` at import time because the dict tried to reference functions not yet defined.

**Decision:** All tool function definitions MUST appear before the `TOOLS = {}` dict in every MCP module. This is a hard rule enforced by `test_mcp_registry.py` R3.

**Reasoning:** Python executes module-level code top-to-bottom at import time. A `TOOLS = {"tool_name": {"fn": tool_fn, ...}}` dict reference to `tool_fn` requires `tool_fn` to already exist in the namespace. This is a class of bug that caused silent failures before the CI test was added.

**Enforcement:** `tests/test_mcp_registry.py` test R3 verifies all registered tool functions exist at registry load time.

**Outcome:** Rule documented and tested. No new MCP modules should violate this ordering.

---

## ADR-021 — EventBridge Rule Naming Convention (CDK)

**Status:** Active  
**Date:** 2026-03-10  
**Context:** CDK auto-generates EventBridge rule names using the pattern `<StackName>-<ConstructId><Hash>`. These names are unreadable in the AWS console and CloudWatch. Some rules were manually named in early CDK stacks.

**Decision:** CDK-generated rule names are acceptable. Do not add `rule_name=` overrides unless the rule name must match an existing live rule (e.g., during manual→CDK migration).

**Reasoning:** CDK-generated names are stable — they only change if the construct ID or stack name changes. Manually naming rules adds boilerplate to CDK stacks and can cause naming conflicts. The CloudWatch console and `post_cdk_reconcile_smoke.sh` identify Lambdas by function name, not EventBridge rule name. The operational value of human-readable rule names is low compared to the maintenance cost.

**Exception:** `life-platform-nightly-warmer` was manually named for the legacy warmer pattern. Now deprecated in favour of the CDK-managed `LifePlatformMcp` warmer rule (v3.7.22).

**Outcome:** CDK-generated names standard. No new `rule_name=` overrides except migration scenarios.

---

## ADR-022 — CoreStack Scoping: Shared Infrastructure vs. Per-Stack Resources

**Status:** Active  
**Date:** 2026-03-10  
**Context:** CDK PROD-1 migration required splitting resources across 8 stacks. Some resources (DynamoDB, S3, SQS DLQ, SNS topic) are shared by all stacks. Should they live in CoreStack or be duplicated?

**Decision:** Shared infrastructure (DynamoDB, S3, SQS DLQ, SNS alerts topic) lives in CoreStack only. All other stacks receive them as constructor parameters (`table`, `bucket`, `dlq`, `alerts_topic`).

**Reasoning:** DynamoDB and S3 are stateful resources — accidental recreation would cause data loss. Centralizing them in CoreStack ensures they are never accidentally deleted during stack updates. Cross-stack references (CDK `Fn::ImportValue`) allow other stacks to consume them without ownership. The pattern also enforces that CoreStack must be deployed first.

**Outcome:** `core_stack.py` owns: `life-platform` DynamoDB table (imported), `matthew-life-platform` S3 (imported), SQS DLQ, SNS topic. All other stacks receive these via constructor injection.

---

## ADR-023 — Sick Day Checker as Shared Utility, Not Standalone Lambda

**Status:** Active  
**Date:** 2026-03-10  
**Context:** Sick day detection logic was duplicated across `character_sheet_lambda.py`, `daily_metrics_compute_lambda.py`, `anomaly_detector_lambda.py`, and `freshness_checker_lambda.py`. Each had a slightly different implementation.

**Decision:** Centralize in `sick_day_checker.py` as a shared utility module in the Lambda Layer. Lambdas import it directly — no Lambda invocation needed.

**Reasoning:** Sick day check is a simple DynamoDB `GetItem` — it doesn't justify a dedicated Lambda invocation (cold start, DLQ overhead, IAM role). The shared module pattern is already established (ADR-013). Centralizing eliminates drift between 4 different implementations of the same logic.

**Interface:** `from sick_day_checker import check_sick_day` → returns the sick day record or `None`. Safe to call from any Lambda — returns `None` on any error rather than raising.

**Outcome:** `sick_day_checker.py` in Lambda Layer. Consumed by `character_sheet_lambda`, `daily_metrics_compute_lambda`, `anomaly_detector_lambda`, `freshness_checker_lambda`. Compute is synchronous with the calling Lambda — no scheduling overhead.

---

## ADR-024 — DLQ Consumer: Schedule-Triggered vs SQS Event Source Mapping

**Status:** Active  
**Date:** 2026-03-14 (v3.7.19)  
**Context:** R8-LT8 asked whether the DLQ consumer should switch from its current scheduled model (EventBridge every 6 hours, Lambda polls SQS) to SQS event source mapping (Lambda triggered immediately on message arrival).

**Decision:** Retain the schedule-triggered model. No migration to event source mapping.

**Reasoning:**
1. **DLQ messages are not time-critical.** A DLQ message represents a failed async Lambda invocation. The underlying failure already happened. Knowing about it in 6 hours vs 30 seconds has no operational difference for a personal project with no SLA.
2. **Schedule model is simpler.** The consumer uses `sqs.receive_message` with long polling. It works correctly today with zero configuration risk.
3. **Event source mapping adds complexity for marginal gain.** ESM requires: a new `SQS` trigger on the Lambda, `sqs:ReceiveMessage` / `sqs:DeleteMessage` / `sqs:GetQueueAttributes` IAM on the Lambda role (currently on the function itself), batch size and window configuration, and a visibility timeout that exceeds Lambda timeout. None of this is complicated, but it adds CDK config and an execution model change to a non-critical path.
4. **Personal project context.** Viktor (Adversarial board member) correctly flagged this as a marginal improvement. The 6-hour polling interval is fine for a system where the operator checks email daily.

**Alternatives considered:**
- SQS event source mapping: triggers immediately on message arrival, auto-deletes on success, no polling needed. Saves ~$0 (SQS free tier). Adds CDK config complexity.
- Reduce schedule to 1 hour: trivial change, still polling model, marginally faster notification.

**Outcome:** No change. Documented explicitly so future reviewers don't re-open this question.

---

## ADR-025 — composite_scores vs computed_metrics: Consolidate into computed_metrics

**Status:** Active  
**Date:** 2026-03-14 (v3.7.22, R9 hardening)  
**Context:** Viktor Sorokin (R9) raised whether SOURCE#composite_scores (v3.7.20) duplicates SOURCE#computed_metrics. ~80% field overlap.

**Decision:** Consolidate into computed_metrics. Remove composite_scores. Execute before SIMP-1 Phase 2.

**Reasoning:** (1) No distinct access pattern — computed_metrics already serves this purpose. (2) Field overlap is a coherence liability with no tie-breaker rule. (3) Two writes for the same data risk temporal divergence. (4) computed_metrics is the established SOT since IC-8.

**Migration:** Remove write_composite_scores() from daily_metrics_compute_lambda.py. Redirect weekly_correlation_compute_lambda.py's composite fetch to computed_metrics. Update SCHEMA.md.

**Outcome:** Consolidate before Apr 13.

---

## ADR-026 — Local MCP Endpoint: AuthType NONE + In-Lambda API Key Check (Accepted)

**Status:** Active  
**Date:** 2026-03-14 (v3.7.22, R9 hardening)  
**Context:** Local MCP Lambda Function URL uses AuthType NONE + x-api-key in-Lambda. Remote uses HMAC Bearer. Yael (R9) asked for explicit documentation.

**Decision:** Retain current model. Document as accepted design.

**Reasoning:** (1) Both endpoints require auth — local validates x-api-key before any processing. (2) IAM AuthType breaks Claude Desktop bridge (would need SigV4 signing). (3) Unguessable URL (~160-bit entropy) + in-Lambda auth is strong for a personal project. (4) HMAC Bearer consistency is cosmetic — no meaningful security gain.

**Alternatives considered:**
- Migrate local endpoint to HMAC Bearer: achieves consistency but requires `mcp_bridge.py` changes with no meaningful security gain.
- AWS IAM AuthType: breaks Claude Desktop bridge without significant rework.

**Outcome:** Document and accept. Local endpoint: `AuthType NONE` + `x-api-key` in-Lambda. Remote endpoint: `AuthType NONE` + HMAC Bearer. Both require valid auth tokens before any processing. No migration planned.

---

## ADR-027 — MCP Two-Tier Structure: Stable Core → Layer, Volatile Tools → Zip

**Status:** Active  
**Date:** 2026-03-14 (R11 engineering strategy)

**Context:** The MCP server is a monolith with 88 tools and 31 modules. Every tool change requires deploying all 31 modules together. The blast radius of a broken `tools_calendar.py` is the entire MCP server going down. R11 board (Priya Nakamura) identified that stable infrastructure and volatile tool modules are bundled together unnecessarily.

**Decision:** Split MCP into two tiers:
- **Stable core → Lambda Layer:** `config.py`, `core.py`, `helpers.py`, `labs_helpers.py`, `strength_helpers.py`, `utils.py` — infrastructure that changes monthly at most
- **Volatile tools → Lambda zip:** `mcp_server.py`, `handler.py`, `registry.py`, `warmer.py`, `tools_*.py` — tool logic that changes every session

**Reasoning:** Lambda resolves imports from both `/opt/python/` (Layer) and `/var/task/` (zip), so a mixed Layer+zip `mcp` package works transparently. Stable modules stay at their versioned Layer state unless explicitly updated. Tool additions/changes only touch the zip.

**Why not move registry.py to Layer:** `registry.py` imports all tool functions at load time. If registry was in the Layer and tools in the zip, the Layer would need the zip to be present before it could import — defeating the separation. Registry stays in the zip with the tools it depends on.

**Migration:** Script at `deploy/build_mcp_stable_layer.sh`. Requires one-time Layer rebuild and CDK update. After migration, `deploy_lambda.sh` workflow is unchanged — it packages only the specified source file.

**Outcome:** Implement before next major MCP expansion. Script ready. See `deploy/build_mcp_stable_layer.sh`.

---

## ADR-028 — Integration Tests as Quality Gate: Test-in-AWS After Every Deploy

**Status:** Active  
**Date:** 2026-03-14 (R11 engineering strategy)

**Context:** 90 offline unit tests pass reliably but cannot catch: wrong IAM permissions, Lambda Layer version mismatches, wrong handler module names, missing EventBridge rules, or secret deletions. These are the root causes of ~80% of historical incidents. Jin Park (R11): "The gap between changed and verified working is where incidents live."

**Decision:** `tests/test_integration_aws.py` (10 tests, I1-I10) runs against live AWS. Required after every CDK deploy. Optional but recommended after any Lambda code deploy. Tests are read-only: no writes, no state changes. Skip gracefully when no credentials present.

**Tests implemented:**
- I1: Lambda handler names match expected (catches CDK reconcile regression)
- I2: Lambda Layer version current (catches stale module copies)
- I3: Spot-check Lambda invocability — no ImportModuleError
- I4: DynamoDB has deletion protection + PITR enabled
- I5: Required secrets exist; deleted secrets are gone
- I6: Critical EventBridge rules exist and are ENABLED
- I7: CloudWatch alarm count meets minimum threshold
- I8: S3 bucket exists with critical config files
- I9: SQS DLQ has zero messages
- I10: MCP Lambda responds to invocation

**Usage:** `python3 -m pytest tests/test_integration_aws.py -v --tb=short`

**Outcome:** Run as part of session-close ritual after CDK deploys. Add to `post_cdk_reconcile_smoke.sh` as a step.

---

## ADR-029 — MCP Monolith: Retain Single Lambda, Revisit at 100+ Calls/Day

**Status:** Active — decision not to split (R13-F03)
**Date:** 2026-03-15 (R13 Finding-03)

**Context (R13-F03 finding):** The MCP server is a single Lambda (`life-platform-mcp`, 768 MB, 89 tools). At current usage (personal, 1 operator, ~5-20 calls/day), response latency is dominated by DynamoDB queries, not Lambda compute. R13 raised the question: should the MCP Lambda be split into read-light (cached metadata, tool list) and read-heavy (correlation, longitudinal, search) functions?

**Options considered:**

1. **Split into 2 Lambdas** — `mcp-read-light` (cached tools, tool list) and `mcp-read-heavy` (correlation, full scans). Pro: read-light can have aggressive keep-warm; read-heavy can scale independently. Con: routing layer needed; doubles deployment complexity; MCP spec doesn't natively support tool-based routing.

2. **Split into N micro-Lambdas by domain** — one Lambda per tool module (health, training, nutrition, etc.). Pro: independent scaling. Con: MCP protocol requires a single endpoint for tool discovery; routing becomes a full API gateway problem.

3. **Retain single Lambda with tiered caching** (chosen). Pro: simple; nightly warmer already pre-computes 14 expensive tools (<100ms cached); SIMP-1 Phase 2 targeting ≤80 tools further reduces cold payload. Con: if usage grows 5-10×, cold start time may degrade.

**Decision:** Retain single Lambda. Revisit when either:
- Daily MCP call volume exceeds 100/day (currently <20), OR
- p95 latency on uncached tools exceeds 15 seconds (currently <8s)

Monitor via X-Ray (added R13-XR, v3.7.40). X-Ray traces will surface which tools dominate latency if a split ever becomes necessary.

**Split trigger checklist (when to re-evaluate):**
- [ ] X-Ray shows consistent >10s p95 on read-heavy tools
- [ ] Cold start time >3s after SIMP-1 Phase 2 (≤80 tools)
- [ ] Usage grows to >100 MCP calls/day
- [ ] Second operator/user is onboarded (multi-tenant changes the equation entirely)

**Outcome:** No action. X-Ray tracing in place. Re-evaluate at AR #16 or when trigger conditions met.

---

## ADR-030 — Google Calendar Integration: Retired

**Status:** Active — decision not to pursue  
**Date:** 2026-03-15 (v3.7.46)

**Context:** Google Calendar was added as a data source in v3.7.21 with a pending OAuth setup step (CLEANUP-3). The intent was to provide daily meeting load, focus block count, and schedule context to MCP tools and the Daily Brief. On 2026-03-15, all viable integration paths were systematically evaluated.

**Options evaluated and blocked:**

| Approach | Blocker |
|----------|---------|
| OAuth via Google Cloud project | Smartsheet IT caps personal Google Cloud projects on work account |
| Secret ICS URL | Disabled by Google Workspace admin (option not shown in calendar settings) |
| Google Apps Script | script.google.com blocked by Smartsheet IT |
| AppleScript → Calendar.app | Calendar.app makes CalDAV network calls on every query; hangs indefinitely on a 21-day window even for single-day queries |
| SQLite direct read of Calendar cache | macOS TCC blocks Terminal from `~/Library/Calendars/` without Full Disk Access |
| Zapier Find Events | Free tier returns 1 event max, not all events for a day; insufficient for meeting load computation |
| launchd → run every 4 hours | Mac lid is typically closed; unreliable data collection |

**Decision:** Retire the Google Calendar integration. Remove from freshness checker, MCP registry, and tool catalog. Mark Lambda and CDK resources as inactive.

**Reasoning:** Calendar data would add meeting load context and focus block detection — useful but supplementary. Todoist already covers planned workload. The platform produces complete Daily Briefs, Weekly Digests, and IC intelligence without calendar data. No viable zero-touch data path exists given Smartsheet IT restrictions on the work Google Workspace account. Personal calendar is Proton (no API). The cost of carrying a permanently-pending data source (showing as a gap in every architecture review, maintaining a Lambda that always returns `pending_oauth`) exceeds the value.

**What was removed (v3.7.46):**
- `get_calendar_events` and `get_schedule_load` removed from `mcp/registry.py`
- `google_calendar` removed from `freshness_checker_lambda.py` SOURCES and FIELD_COMPLETENESS_CHECKS
- `google_calendar_lambda.py` marked `not_deployed` in `ci/lambda_map.json`
- `setup/calendar_sync.py`, `setup/run_calendar_sync.sh`, `setup/com.matthewwalker.calendar-sync.plist` deleted
- `life-platform/google-calendar` secret scheduled for deletion (manual step)
- CDK removal from `ingestion_stack.py` deferred to next CDK deploy session

**What was retained:**
- `lambdas/google_calendar_lambda.py` — archived in place, not deleted (useful reference if integration becomes viable again)
- DynamoDB `SOURCE#google_calendar` records — harmless, no cost, provide historical context

**Revisit conditions:**
- Smartsheet IT allows Google Cloud project creation on work account, OR
- Personal calendar moves from Proton to a platform with an accessible API, OR
- Apple Calendar grants Terminal Full Disk Access in a managed way

**Outcome:** Integration retired. Tool count: 89 → 87. Data sources: 20 → 19 active.

---

## ADR-031 — MCP Lambda Deploy: Always Use Full Zip Build

**Status:** Active — operational constraint  
**Date:** 2026-03-15 (v3.7.47)

**Context:** On 2026-03-15, `bash deploy/deploy_lambda.sh life-platform-mcp mcp_server.py` was used to deploy the MCP Lambda after removing the calendar tools. The script only packaged `mcp_server.py`, stripping the `mcp/` package from the zip. The Lambda booted without error but routed all requests through the bridge handler (which checks `x-api-key`, not Bearer) instead of the remote MCP handler, causing all OAuth endpoints to return `{"error": "Unauthorized"}`. The connector showed "error connecting" in claude.ai. Took ~30 minutes to diagnose.

**Root cause:** `deploy_lambda.sh` is designed for single-file Lambdas. The MCP Lambda is a multi-module package (`mcp_server.py` + `mcp_bridge.py` + the full `mcp/` directory). `update-function-code` replaces the entire zip, so previous content of `mcp/` was deleted.

**Decision:** `deploy_lambda.sh` now hard-rejects `life-platform-mcp` at line ~55 with a clear error and prints the correct build commands. MCP deploys must always use:

```bash
cd /path/to/life-platform
ZIP=/tmp/mcp_deploy.zip
rm -f $ZIP
zip -j $ZIP mcp_server.py mcp_bridge.py
zip -r $ZIP mcp/ -x 'mcp/__pycache__/*' 'mcp/*.pyc'
aws lambda update-function-code --function-name life-platform-mcp --zip-file fileb://$ZIP --region us-west-2
```

**Outcome:** Guard in place. Incident cannot recur via `deploy_lambda.sh`. MCP build pattern documented in RUNBOOK.md.

---

## ADR-032 — S3 Bucket Policy: Deny DeleteObject on Data Prefixes for Deploy User

**Status:** Active
**Date:** 2026-03-16 (v3.7.57, post-incident hardening)
**Context:** On 2026-03-16, a one-off deploy script ran `aws s3 sync --delete` to the bucket root, deleting 35,188 objects across all S3 prefixes. The operator's IAM user (`matthew-admin`) had full S3 permissions. S3 versioning saved the data, but the incident exposed that no guard existed to prevent deploy scripts from deleting data objects.

**Decision:** S3 bucket policy with an explicit Deny on `s3:DeleteObject` for `matthew-admin` on all data prefixes: `raw/*`, `config/*`, `uploads/*`, `dashboard/*`, `exports/*`, `deploys/*`, `cloudtrail/*`, `imports/*`. The `site/` prefix is excluded so that `sync_site_to_s3.sh --delete` can still clean up old site files.

**Reasoning:** An explicit Deny in a resource-based policy overrides any Allow in the IAM user's identity policy. This makes it physically impossible for any CLI command or script running as `matthew-admin` to delete objects in protected prefixes — regardless of bugs, typos, or `--delete` flags. Lambda execution roles are different principals and are unaffected.

**Alternatives considered:**
- IAM policy restriction on `matthew-admin`: Less reliable — a broad `s3:*` Allow anywhere in the user's policies would override a narrower Deny. Resource-based Deny is absolute.
- Separate bucket for data: Architecturally cleaner (see long-term recommendation) but higher migration effort. Bucket policy is immediate.
- MFA Delete: Requires MFA for every delete — impractical for automated processes.

**To temporarily bypass (for legitimate bulk deletes):**
```bash
# Remove the bucket policy temporarily
aws s3api delete-bucket-policy --bucket matthew-life-platform
# Do the work...
# Re-apply the policy
aws s3api put-bucket-policy --bucket matthew-life-platform --policy file:///tmp/bucket_policy.json
```

**Outcome:** Policy applied and verified. `matthew-admin` can upload/overwrite but cannot delete under protected prefixes. Tested: upload succeeded, delete returned `AccessDenied`.

---

## ADR-033 — Safe S3 Sync: Wrapper Function with Dryrun Gate and Root-Block

**Status:** Active
**Date:** 2026-03-16 (v3.7.57, post-incident hardening)
**Context:** The Mar 16 S3 bucket wipe was caused by `aws s3 sync --delete` targeting the bucket root. The canonical `sync_site_to_s3.sh` correctly uses `S3_PREFIX="site"`, but a one-off script bypassed this. A defense-in-depth wrapper is needed for any future script that uses `--delete`.

**Decision:** `deploy/lib/safe_sync.sh` provides a `safe_sync()` bash function that: (1) blocks any sync to bucket root, (2) runs `--dryrun` first and counts deletions, (3) aborts if deletions exceed 100 (configurable). Deploy scripts should `source deploy/lib/safe_sync.sh` and call `safe_sync` instead of raw `aws s3 sync --delete`.

**Reasoning:** The wrapper catches two failure modes: wrong target (bucket root) and unexpectedly large deletions (wrong source). Both are cheap checks — one string match and one dryrun pass — that prevent catastrophic outcomes. The 100-deletion threshold is generous enough for normal site deploys but catches the "syncing 17 files against 35,000" scenario.

**Alternatives considered:**
- Pre-commit hook scanning for `aws s3 sync --delete`: catches at commit time, not runtime. Doesn't protect ad-hoc CLI usage.
- CI/CD pipeline only: the platform doesn't have a full CI/CD pipeline for deploys yet.

**Outcome:** `deploy/lib/safe_sync.sh` committed. Combined with ADR-032 (bucket policy) and S3 versioning, the platform now has three independent layers of protection against accidental S3 data deletion.

---

## ADR-034 — Website Content Consistency Architecture (Component System + Constants)

**Status:** Active
**Date:** 2026-03-24 (v3.9.8)
**Context:** With 54 HTML pages and 30+ pages containing hardcoded journey/platform values (302, 185, dates, tool counts), any narrative reframe or factual update requires manual spot-checking across all files. The nav/footer restructure across 44 files (v3.8.9) proved this is unsustainable. A content consistency system is needed that allows "change once, propagate everywhere" without migrating to a full static site generator.

**Decision:** Implement a 3-layer content architecture:
1. **`site_constants.js`** — single source of truth for all factual values (journey weights/dates, platform counts, bios, meta descriptions, reading paths). Pages reference values via `data-const="key.path"` attributes; JS injects values at page load.
2. **`components.js`** — shared structural components (nav, footer, bottom-nav, subscribe CTA, reading path) injected at runtime into mount-point `<div>` elements. Eliminates 54-file duplication.
3. **Content manifest** (`content_manifest.json`) — inventory of all journey-sensitive prose across the site, categorized as constant/api_driven/prose_with_facts/narrative/archive. Used by humans and CI to find all locations needing review when the narrative changes.

Supporting files: `data_sources.json` (source registry), `lint_site_content.py` (CI validator), `migrate_page_to_components.py` (mechanical migration tool).

**Reasoning:** A full SSG (Hugo, Eleventy) was considered but adds build dependencies, a templating language, and deploy pipeline changes for a solo project. The JS injection approach preserves the zero-build-step static HTML deploy model while solving 90%+ of the consistency problem. Narrative prose is deliberately excluded from auto-replacement — the content manifest makes it findable, but rewriting is an editorial act.

**Alternatives considered:**
- **Hugo/Eleventy SSG:** Full templating but requires Node/Go build step, partials, frontmatter. Overhead exceeds benefit for solo operator.
- **Server-side includes (SSI):** CloudFront doesn't support SSI without Lambda@Edge processing every request.
- **Full CMS (Notion/Contentful):** Adds external dependency, API calls on page load, and per-request latency. Overkill.
- **Find-and-replace scripts:** Brittle, doesn't handle prose context, no CI validation.

**Outcome:** Foundation files committed. Pages migrate incrementally — each conversion replaces ~200 lines of duplicated nav/footer HTML with 5 mount-point divs. OG meta tags require a build-time sync step (JS can't modify meta tags for crawlers). Published archive content (chronicle/journal posts) is explicitly excluded from auto-updates per Dr. Lena Johansson's recommendation.

---

## ADR-035 — SIMP-1 Tool Consolidation: View-Dispatchers over Standalone Tools

**Status:** Active
**Date:** 2026-03-09 (v3.7.17–19)

**Context:** The MCP server had grown to 116 tools. Claude's tool-selection accuracy degrades above ~80 tools — the model has to scan the full tool list on every call, and near-synonym tools (`get_habit_adherence` vs `get_habit_streaks` vs `get_habit_dashboard`) cause frequent misrouting. MCP spec imposes no hard limit, but usability suffers.

**Decision:** Consolidate related tools into "view-dispatchers" — a single tool with a `view=` parameter that selects the analysis. 13 dispatchers replaced 30+ standalone tools (116 → 86).

**Dispatchers created:** `get_daily_snapshot`, `get_longitudinal_summary`, `get_health`, `get_nutrition`, `get_labs`, `get_training`, `get_strength`, `get_character`, `get_cgm`, `get_mood`, `get_daily_metrics`, `get_todoist_snapshot`, `manage_sick_days`. Later (v4.4.0): `get_habits`.

**Reasoning:**
1. **Reduced tool-selection noise.** A single `get_health` with `view=dashboard|risk_profile|trajectory` is easier for Claude to route than three separate tools.
2. **Shared parameter validation.** Date range handling, source validation, and cache checks are written once in the dispatcher.
3. **Retained standalone for unique signatures.** `compare_periods` (4 required date params) and `search_activities` (unique filters) stayed standalone — forcing them into a dispatcher would degrade the schema.

**Alternatives considered:**
- **Nested tool categories in MCP schema:** MCP spec doesn't support tool grouping/namespacing.
- **Separate MCP endpoints per domain:** Would require tool routing layer and break the single-endpoint assumption. See ADR-029.
- **Aggressive reduction (target 50 tools):** Would force unnatural groupings and lose descriptive tool names.

**Outcome:** 116 → 86 tools (SIMP-1 Phase 1). Post-v4.4.0 habit consolidation: 112 tools. Claude's routing accuracy improved noticeably.

---

## ADR-036 — 3-Layer Status Monitoring Architecture

**Status:** Active
**Date:** 2026-03-29 (v4.4.0)

**Context:** The initial status page showed binary freshness (data exists today: green; no data: red). This produced false reds for activity-dependent sources (Strava on rest days) and false greens for silently broken pipelines (Dropbox secret deleted Mar 10 — Lambda returned "no files found" but the status page showed stale-but-present data as OK). Four pipelines were silently broken for up to 10 days before manual discovery.

**Decision:** 3-layer monitoring with overlay pattern:
1. **Layer 1 — Data freshness.** Per-source stale thresholds (Whoop: 48h, Strava: 72h, Labs: 180 days, etc.). Checks DynamoDB for most recent `DATE#` record per source.
2. **Layer 2 — CloudWatch alarm overlay.** Site-api reads alarm state for every source's error alarm. If an alarm is in `ALARM` state, the source is marked red regardless of freshness.
3. **Layer 3 — Pipeline health check.** Daily at 6 AM PT, a dedicated Lambda invokes every ingestion Lambda with `{}` payload and checks for `FunctionError`. Also checks all 11 Secrets Manager secrets for deletion. Results written to DynamoDB, overlaid by site-api.

**Reasoning:** Each layer catches failures the others miss. Freshness catches "Lambda ran but wrote nothing." Alarms catch "Lambda threw errors." Health check catches "Lambda can't even start (missing secret, import error, auth expired)." The Dropbox incident proved that silent failures (Lambda returns 200 with empty results) bypass both freshness and alarm monitoring — only active probing would have caught it.

**Alternatives considered:**
- **CloudWatch Synthetics canaries:** $12/canary/month × 17 sources = $204/month. Disproportionate for a personal project.
- **Step Functions workflow:** Orchestration overhead for a simple probe-and-report pattern.
- **Alarm-only monitoring:** Misses silent failures (Lambda succeeds but writes no data).
- **Freshness-only monitoring:** Misses configuration failures (deleted secrets, expired tokens).

**Outcome:** 3-layer monitoring live. Caught the Dropbox, Notion, and Eight Sleep failures that the old system missed.

**Update (v4.4.0):** Health check now sends `{"healthcheck": true}` payload. All 17 probed Lambdas have a 2-line early-return guard at the top of `lambda_handler` — they validate imports and module initialization, then return immediately without hitting external APIs, writing to DDB, or sending emails. The daily-brief probe no longer sends a duplicate email. The original `{}` full-invocation risk has been eliminated.

---

## ADR-037 — Site API Read-Only Constraint

**Status:** Active
**Date:** 2026-02-27 (established), formally documented 2026-03-29

**Context:** `site_api_lambda.py` serves the public website at averagejoematt.com with 60+ endpoints. It has full DynamoDB read permissions to serve data. Should it have write permissions?

**Decision:** The site API Lambda must never write to DynamoDB. This is a hard constraint. The Lambda's IAM role has `dynamodb:Query`, `dynamodb:GetItem`, `dynamodb:Scan` only — no `PutItem`, `UpdateItem`, or `DeleteItem`.

**Reasoning:** The site API is the platform's only internet-facing endpoint with unauthenticated access (CloudFront → Lambda). Allowing writes would create a vector for data corruption via crafted requests. Even with input validation, the blast radius of a write-capable public endpoint is disproportionate to any benefit. All data ingestion flows through dedicated ingestion Lambdas with source-specific IAM roles. Rate limiting state is kept in-memory (ADR-038) specifically to avoid needing write permissions.

**Alternatives considered:**
- **Write-capable with strict input validation:** Increases attack surface. Input validation is defense-in-depth, not a primary control.
- **Separate read/write endpoints:** Adds deployment complexity. No current use case requires public writes.

**Outcome:** IAM role enforces read-only. In-memory rate limiting (ADR-038) was a downstream consequence.

---

## ADR-038 — In-Memory Rate Limiting over DynamoDB Counters

**Status:** Active
**Date:** 2026-03-20 (v3.7.84), formally documented 2026-03-29

**Context:** The `/api/ask` (AI Q&A) and `/api/board_ask` (Board of Directors Q&A) endpoints need rate limiting. Options: DynamoDB atomic counters, Redis/ElastiCache, or in-Lambda memory.

**Decision:** In-memory Python dict (`_RATE_LIMITS = {}`) in the site-api Lambda. 5 requests/hour anonymous, 20/hour subscriber for `/api/ask`; 5/hour per IP for `/api/board_ask`.

**Reasoning:** The site-api Lambda is read-only (ADR-037) — adding DynamoDB write permissions for rate counters would break that constraint. ElastiCache requires VPC (rejected in ADR-008) and costs $13+/month minimum. In-memory counters are free, zero-latency, and sufficient for a single-Lambda, low-traffic personal site. The tradeoff is that counters reset on cold starts and are per-container — a determined abuser could hit the limit, wait for a new container, and get a fresh budget.

**Defense in depth:** R18-F06 deployed WAF rate rules on the CloudFront distribution: 100 requests per 5 minutes on `/api/ask` and `/api/board_ask`. The WAF provides coarse-grained abuse prevention (hard ceiling regardless of Lambda containers). The in-memory limits provide fine-grained per-user UX guardrails (5/hour feels right for a personal Q&A feature). Together they form a two-layer defense: WAF stops bots, in-memory shapes human usage.

**Outcome:** In-memory rate limiting live as UX layer. WAF rate rules live as security layer. Cost: $0 incremental (WAF WebACL already provisioned for other rules). No DynamoDB writes from site-api.

---

## ADR-039 — CSS/JS Cache: Content-Hash Filenames with 1-Year Immutable TTL

**Status:** Active
**Date:** 2026-03-29 (v4.4.0)

**Context:** Site CSS/JS files were originally served with `max-age=31536000, immutable` but filenames had no content hash (`base.css` not `base.a1b2c3d4.css`). Returning visitors saw broken layouts after CSS changes. An interim fix changed TTL to 1 day, but this forced daily re-downloads of ~150KB.

**Decision:** Content-hash filenames with 1-year immutable cache. The deploy script (`sync_site_to_s3.sh`) computes an 8-char MD5 hash per CSS/JS file, creates a hashed copy (e.g., `base.a1b2c3d4.css`), and rewrites all HTML `<script>`/`<link>` references to the hashed filename. Hashed files are uploaded with `max-age=31536000, immutable`. Original filenames are also uploaded with `max-age=86400` as a fallback for dynamic JS loads.

**Build step:** The deploy script creates a temporary build directory, hashes files, updates HTML, syncs to S3, and cleans up. No permanent build artifacts. The `site/` directory in git remains unhashed — hashing happens at deploy time only.

**Edge case:** `components.js` dynamically loads `countdown.js` at runtime via `document.createElement('script')`. This dynamic reference uses the original (unhashed) filename and gets the 1-day fallback cache. All other files are referenced via static HTML tags and get the full 1-year cache benefit.

**Alternatives considered:**
- **1-day TTL on all assets:** Simple but forces ~150KB re-download daily. Previous interim solution.
- **Versioned query strings** (`base.css?v=4.4.0`): CloudFront cache policy may not include query strings in the cache key. Fragile.
- **Full build tool (Vite/webpack):** Adds Node dependency and build pipeline. Overkill for 10 asset files.

**Outcome:** Content-hash filenames live in `sync_site_to_s3.sh`. Returning visitors only re-download assets when content actually changes. Page load improved ~100ms for return visits.

---

## ADR-040 — Board of Directors: Fictional Advisors over Real Public Figures

**Status:** Active
**Date:** 2026-03-26 (v4.2.1, offsite Decision 30)

**Context:** The Board of Directors originally used real public figures (Peter Attia, Andrew Huberman, Layne Norton, etc.) as AI personas — each board member spoke in the voice of the real person, generating health advice attributed to them.

**Decision:** Replace all real public figures with fictional advisor characters. Real figures are referenced only as "inspired by" attributions and as evidence citations (e.g., "Dr. Attia's research on Zone 2").

**Reasoning:**
1. **Legal risk.** Generating AI text in a real person's voice and attributing health advice to them — especially medical advice — creates right-of-publicity and defamation exposure. The platform is public.
2. **Accuracy risk.** An AI generating "Huberman says X" will inevitably produce advice that Huberman never said or wouldn't endorse. This erodes trust in both the platform and the cited expert.
3. **Editorial independence.** Fictional advisors can evolve with the platform's needs. A "Dr. Sarah Chen" character can synthesize sleep research from multiple experts without being constrained to one real person's published positions.

**Fictional panel (14 members):** Elena Voss (narrator), Sarah Chen (sleep), Marcus Rodriguez (behavioral), James Whitfield (training), Priya Nakamura (engineering), Viktor Sorokin (adversarial), Lena Johansson (editorial), Jin Park (data), Clara Okafor (nutrition), Tomás Delgado (metabolic), Diane Chowdhury (longevity), Alex Reeves (movement), Mia Tanaka (social), Rachel Adler (mind).

**What was retained:** Evidence citations to real researchers remain throughout (e.g., "Attia benchmarks", "Huberman jet lag protocol", "Walker sleep debt"). These are factual references, not persona-generation.

**Outcome:** All email Lambdas, MCP tools, and site pages use fictional advisors. Board config in `s3://matthew-life-platform/config/board_of_directors.json`.

---

## ADR-041 — Food Delivery Data: Delivery Index Abstraction for Privacy

**Status:** Active
**Date:** 2026-03-28 (v4.2.2)

**Context:** 15 years of food delivery data (1,598 transactions, $61K total) is one of the platform's strongest behavioral signals — order frequency correlates with diet adherence, stress, and weight trends. But raw dollar amounts and order details are sensitive.

**Decision:** Expose food delivery data publicly only through an abstracted "Delivery Index" (0-10 scale) and clean streak (days since last order). Never surface raw dollar amounts, specific restaurants, or order contents in public-facing contexts.

**Reasoning:** The platform's editorial philosophy is radical transparency about health data, but financial spending patterns carry different privacy implications. A reader knowing "Matthew had a Delivery Index of 8.2 in August" conveys the behavioral signal without exposing "$3,674 in delivery charges." The Index is calibrated so that the worst historical month (Aug 2025: 68 orders, 24/31 days with delivery) = 10.0, using a divisor of 1.55.

**Privacy boundary:** MCP tools and private dashboards show full detail (amounts, restaurants, order counts). The public site, API, and Chronicle emails only show Index + streak.

**Outcome:** `get_food_delivery` MCP tool has full data. `/api/food_delivery` returns Index-only. Chronicle emails reference streak days, not dollars.

---

## ADR-042 — OG Image Generation: Lambda + Pillow over External Services

**Status:** Active
**Date:** 2026-03-28 (v4.3.0)

**Context:** Each of the 67 site pages needs an Open Graph image for social sharing (Twitter cards, link previews). Options: static placeholder images, external OG image services (Cloudinary, og-image.vercel.app), or generate images programmatically.

**Decision:** Dedicated Lambda (`og-image-generator`) runs daily at 11:30 AM PT, generates 12 page-specific 1200×630 PNG images using Pillow, uploads to S3. Pillow deployed as a Lambda Layer.

**Reasoning:** External OG services charge per-image or per-render and add an external dependency. Static images don't reflect live data. Pillow in a Lambda Layer (~15MB) is free to run on the daily EventBridge schedule (well within free tier), produces images with live stats (weight, character level, HRV, etc.), and keeps all assets within the existing S3+CloudFront infrastructure. The daily cadence matches the data update frequency — health stats don't change intra-day.

**Alternatives considered:**
- **Static placeholder images:** No live data. Missed engagement opportunity.
- **Cloudinary/Imgix dynamic URLs:** Per-render pricing. External dependency. URL complexity.
- **Puppeteer/Playwright headless Chrome:** Heavier Lambda Layer (~50MB+), slower generation, more complex setup for rendering HTML to PNG.
- **Build-time generation in deploy script:** Would need data access at build time. Currently the deploy pipeline has no data access.

**Outcome:** 12 OG images generated daily. ~3s per image. Total Lambda cost: ~$0.001/day.

---

## ADR-043 — Challenge/Protocol/Experiment Taxonomy: Three Behavioral Tiers

**Status:** Active
**Date:** 2026-03-26 (v3.9.28–29, v4.4.0)

**Context:** The platform needs to track behavioral interventions at different levels of formality. Users create "experiments" (N=1 with before/after metrics) and also want lighter-weight participation mechanisms.

**Decision:** Three-tier taxonomy:
1. **Protocols** — the strategy layer. Long-running (weeks to permanent). Defines the what and why of an ongoing health practice (e.g., "Sleep Protocol: no screens after 9pm"). Tracks adherence, key metrics, related habits. Status: active/paused/retired.
2. **Experiments** — the science layer. Time-bounded (7-60 days). One variable changed, hypothesis stated upfront, 16 metrics auto-compared before vs during. Board evaluation. Status: active/completed/abandoned.
3. **Challenges** — the engagement layer. Gamified, short-duration (7-30 days). Daily check-ins, XP awards, badge unlocks. Can graduate from experiments ("creatine worked → 30-day creatine challenge"). Status: candidate/active/completed/failed.

**Reasoning:** Early design conflated experiments and challenges. Users would create an "experiment" to track a 7-day step challenge — but experiments require a hypothesis, minimum 14-day duration, and statistical comparison. The mismatch created friction. Separating the tiers means: protocols = "what I do," experiments = "what I'm testing," challenges = "what I'm playing." Each has appropriate tooling and lifecycle.

**Alternatives considered:**
- **Single "intervention" type with tags:** Simpler schema, but the lifecycle rules (experiments need hypotheses and baseline periods; challenges need daily check-ins and XP) are different enough that a unified type would need extensive conditional logic.
- **Two tiers (experiments + challenges):** Protocols were added because many behavioral practices (fasting, sleep hygiene, supplement stacks) are indefinite — they don't fit the bounded timeline of experiments or challenges.

**Outcome:** 4 protocol tools, 4 experiment tools, 5 challenge tools. All store to `SOURCE#protocols`, `SOURCE#experiments`, `SOURCE#challenges` partitions respectively.

---

## ADR-044 — Measurements Ingestion via S3 Trigger over EventBridge Cron

**Status:** Active
**Date:** 2026-03-29 (v4.4.0)

**Context:** Body tape measurements are taken every 4-8 weeks (not daily). A CSV or XLSX file is uploaded to S3 after each session. Unlike the 13 API-based ingestion Lambdas that run on daily EventBridge cron schedules, measurements have no external API to poll.

**Decision:** S3 event notification trigger on `s3://matthew-life-platform/imports/measurements/` prefix → invokes `measurements-ingestion` Lambda on file upload.

**Reasoning:** EventBridge cron makes no sense for aperiodic data. The Lambda would run daily, find no new file 95% of the time, and waste invocations. An S3 trigger fires only when a file is actually uploaded, processing it immediately. The pattern also enables drag-and-drop workflows — upload a CSV, get results in DynamoDB within seconds.

**Alternatives considered:**
- **Daily cron scanning `imports/` for new files:** Wastes 350+ invocations per year. Adds delay between upload and processing.
- **Manual Lambda invocation after upload:** Requires operator to remember to run the Lambda after every file upload. Error-prone.
- **MCP tool that accepts inline data:** Would require pasting CSV data into a chat message. Awkward for 20+ measurements.

**⚠️ Note:** The S3 bucket notification configuration was created but needs verification that it's wired correctly (the CDK stack may need updating to include the S3→Lambda trigger).

**Outcome:** S3-trigger pattern established. Can be reused for any future aperiodic ingestion source (DEXA scans, genetic test results, etc.).

---

## ADR-045 — SIMP-1 Phase 2: Accept 115 MCP Tools as Operating State

**Status:** Active
**Date:** 2026-03-30 (v4.5.1)

**Context:** The MCP server has grown from 85 tools (R16) to 118 tools (R19) over 4 consecutive architecture reviews. SIMP-1 Phase 1 (ADR-035, v3.7.17) consolidated ~30 tools into 13 view-dispatchers, reducing from 116 to 86. Since then, product expansion — observatory upgrades, food delivery, measurements, challenges, protocols, decisions — added 32 new tools, bringing the count to 118. The Technical Board (Viktor, 12-2 vote) directed: either execute Phase 2 (target ≤80) or formally accept the current state via ADR. Perpetual deferral is the worst outcome.

**Decision:** Accept 115 tools as the operating state (reduced from 118 via SIMP-1 cleanup). Do not pursue further consolidation at this time.

**Reasoning:**
1. **Tool count maps to product breadth.** 115 tools across 26 data sources and 6 observatory domains is ~4.4 tools per source — a natural density for a platform with this scope.
2. **Low-hanging fruit is already picked.** SIMP-1 Phase 1 consolidated the easy wins (summary/detail pairs, overlapping dashboards). Remaining tools serve genuinely distinct purposes.
3. **No measured degradation.** Claude's tool selection accuracy has not measurably degraded. The MCP cache warmer pre-computes 14 high-frequency tools, reducing cold-start context pressure.
4. **Consolidation cost exceeds benefit.** Merging the remaining tools into view-dispatchers (~38 tools to reach ≤80) would require ~1 week of work and reduce tool discoverability. Users would call `get_lifestyle_data(view="travel")` instead of `get_travel_data()` — a UX regression for a metric improvement.
5. **Revisit trigger defined.** If tool selection accuracy degrades measurably (Claude consistently picks wrong tools) or MCP context window limits are hit, reopen this ADR and execute Phase 2.

**Alternatives considered:**
- **Execute Phase 2 (consolidate to ≤80):** ~1 week effort. Would merge tools_lifestyle (25 tools), tools_habits (16), tools_health (15) into view-dispatchers. Reduces count but degrades discoverability.
- **Partial consolidation (target ~100):** Merge only the largest modules. Moderate effort for moderate reduction. Still doesn't hit 80.

**Outcome:** Finding R17-F13/R18-F07/R19-F05 is formally closed. Tool count is accepted as a product-breadth indicator, not a deficiency. Monitor for selection accuracy degradation.

---

### ADR-046 — S3 Prefix Separation: Static vs Generated Content

**Status:** Active
**Date:** 2026-04-05 (v5.0.0)

**Context:** Lambda-generated files (public_stats.json, character_stats.json, OG images, journal posts) were stored in the same S3 prefix (`site/`) as static HTML/CSS/JS files. When site deploys used `aws s3 sync --delete`, Lambda-generated files were deleted because they don't exist in the local `site/` directory. This broke the live site multiple times — home page gauges went blank, character page showed level 0, supplement data disappeared. A manual exclusion list in `safe_sync.sh` was added as mitigation but failed 3 times (missed files each time).

**Decision:** Move all Lambda-generated files to a new `generated/` S3 prefix. Add a CloudFront origin (`S3GeneratedOrigin`) pointing at `/generated`. Route generated-file URL patterns to the new origin via 6 cache behaviors. Public URLs remain unchanged.

**Reasoning:**
1. **Structural impossibility of collision.** `aws s3 sync site/ --delete` physically cannot touch `generated/*` because the prefixes are disjoint. No exclusion list needed.
2. **Same S3 bucket, zero cost increase.** Different prefix, not a different bucket.
3. **Same public URLs.** CloudFront cache behaviors route `/public_stats.json`, `/data/character_stats.json`, `/assets/images/og-*`, `/journal/posts/*` to the `generated/` origin transparently.
4. **Bucket policy protection.** `generated/*` added to the Deny DeleteObject statement for the deploy user, as defense-in-depth.
5. **Different cache policies.** Generated content can have shorter TTLs (5 min for stats) while static content keeps the 1-hour default.

**Files changed:** `site_writer.py`, `output_writers.py`, `site_stats_refresh_lambda.py`, `og_image_lambda.py`, `wednesday_chronicle_lambda.py`, `chronicle_approve_lambda.py`, `site_api_lambda.py` (S3 key constants), `web_stack.py` (CloudFront origin + behaviors), `role_policies.py` (IAM), `bucket_policy.json`.

**Outcome:** Site deploys are now safe by design, not by exclusion list. The `safe_sync.sh` exclusion list was simplified to only `config/*` (manually-uploaded config files that still live under `site/`).

---

### ADR-047 — Coach Intelligence Architecture: Stateless Prompts → Stateful Agents

**Status:** Active
**Date:** 2026-04-06 (v6.0.0)

**Context:** The platform's coaching system used stateless prompt templates — each generation cycle operated independently with no memory of prior outputs, no awareness of other coaches' perspectives, and no narrative planning. After 6 days of the experiment, gaps were already visible: repetitive framing, no callbacks to prior observations, no cross-domain synthesis, no prediction accountability.

**Decision:** Replace stateless prompt templates with persistent, stateful AI coaching agents. 8 coaches with episodic memory (output archive, thread registry, learning log), voice differentiation (structural voice specs with few-shot calibration), cross-coach communication (ensemble digest, influence graph, disagreement tracking), prediction accountability (Bayesian confidence, null hypothesis comparison), and narrative orchestration (showrunner producing generation briefs).

**Key design principles:**
1. **Computation/LLM separation** — All math (EWMA, regression-to-mean, seasonality, autocorrelation) in deterministic Python. LLM receives results and writes about them in character. (Source: Karpathy, Expert Panel)
2. **DynamoDB state store in existing table** — New PK patterns (COACH#, ENSEMBLE#, NARRATIVE#) in the existing single-table design. No new tables, no external agent frameworks.
3. **Voice specs as calibration anchors** — Few-shot examples maintain voice consistency across model changes. Structural rules (opening patterns, sentence rhythm, analogy domain) differentiate coaches at the structural level, not just vocabulary.
4. **Statistical guardrails scale with coaching sophistication** — Decision class ceilings (observational/directional/interventional) enforced by the orchestrator based on data availability.
5. **Productive disagreement** — Cross-coach disagreement is tracked and surfaced, not smoothed over. Unanimous agreement is flagged as suspicious (S-10).

**Alternatives considered:**
- External agent framework (LangChain, AutoGen) — rejected: too heavy, vendor dependency, can't customize deeply enough for voice differentiation
- Vector store for coach memory — rejected: structured state queries (threads, predictions) don't benefit from semantic search; DynamoDB fits the access pattern
- Single unified coach — rejected: 8 distinct voices with domain expertise create richer coaching than one generalist; cross-coach tension is a feature
- Fewer coaches (3-4) — rejected: the 8 domains map directly to the platform's data pillars; fewer would create artificial domain merging

**8 Lambdas created:** coach-computation-engine, coach-narrative-orchestrator, coach-state-updater, coach-ensemble-digest, coach-prediction-evaluator, coach-history-summarizer, coach-quality-gate, coach-observatory-renderer.

**Cost impact:** ~$3-5/month additional API cost (Haiku for orchestration/extraction/ensemble, Sonnet for generation). DynamoDB cost negligible.

**Outcome:** All 8 coaches live on both email pipeline and public observatory pages. System accumulates state forward from Day 6 of the experiment.

---

### ADR-048 — Observatory Integration: Coach Intelligence Replaces Expert Analyzer

**Status:** Active
**Date:** 2026-04-06 (v6.0.0)

**Context:** Observatory pages used `ai_expert_analyzer_lambda.py` — a weekly Lambda that called Sonnet once per coach with a rotating analytical lens and no memory. This was a separate system from the daily brief coaches. After building the Coach Intelligence pipeline, the expert analyzer became redundant — the daily pipeline produces richer, more consistent, voice-differentiated content.

**Decision:** Wire observatory pages to read from the COACH# state store (populated by the daily brief pipeline) via a new `/api/coach_analysis` endpoint. The expert analyzer Lambda is deprecated. Observatory JS tries the new endpoint first, falls back to legacy `/api/ai_analysis` during transition.

**Reasoning:**
1. **One source of truth** — Coaches write once (daily brief pipeline), observatory and email read the same state. No drift between what the email says and what the website shows.
2. **Richer content** — Observatory cards now show continuity markers (thread references, revision signals, cross-coach references) that the stateless expert analyzer couldn't produce.
3. **No additional LLM cost** — The observatory renderer is a pure DynamoDB reader. Content is pre-computed by the daily pipeline.
4. **Observatory summary** — The state updater now extracts a shorter `observatory_summary` optimized for card format, alongside the full email content.

**Files changed:** `site_api_lambda.py` (new endpoint), `observatory-v3.js` (new fetch + continuity markers + data_availability), `observatory-v3.css` (marker styles), `coach_state_updater.py` (observatory_summary extraction), `coach_observatory_renderer.py` (standalone reader Lambda).

**Outcome:** Observatory pages serve Coach Intelligence content with stateful memory, cross-coach awareness, and data availability constraints. Legacy endpoint retained as fallback.

---

### ADR-049 — COST-OPT-2: Prompt Caching + Strategic Model Downgrades

**Status:** Active
**Date:** 2026-04-09 (v6.7.1)

**Context:** Platform spending ~$17-20/month on Anthropic API calls across 22 Lambdas. Two cost levers were completely unused: prompt caching (90% discount on repeated input tokens) and model tiering (Haiku at ~75% less than Sonnet for structured tasks). The API key ran out of credits, surfacing the cost issue. Analysis showed daily brief (4 Sonnet calls/day) and weekly emails (6+ Sonnet calls/week) as the largest drivers, with observatory expert analyzer (9 Sonnet calls/week) as a strong downgrade candidate.

**Decision:** Two-phase optimization:

**Phase 1 — Prompt caching (zero quality risk):**
- Added `anthropic-beta: prompt-caching-2024-07-31` header and structured system message content blocks with `cache_control: {"type": "ephemeral"}` to all 12 API call sites across 11 files.
- Two shared utilities updated: `retry_utils.py` (`call_anthropic_api`) and `ai_calls.py` (`call_anthropic`) — both auto-wrap string `system` params as cached content blocks. Callers opt in automatically.
- Expert analyzer builds a shared system prompt (goals, inventory, format rules — ~2900 chars) once per invocation, cached across all 8 sequential expert calls.
- New CloudWatch metrics: `AnthropicCacheWriteTokens`, `AnthropicCacheReadTokens` per Lambda.

**Phase 2 — Model downgrades (Sonnet → Haiku for structured tasks):**
- `ai_expert_analyzer_lambda.py`: Haiku default (observatory page content — templated output with KEY RECOMMENDATION / ELENA QUOTE tags)
- `ai_calls._run_analysis_pass()`: Haiku (200-token JSON extraction)
- `hypothesis_engine_lambda.py`: Haiku (structured JSON hypothesis generation)
- `challenge_generator_lambda.py`: Haiku (structured JSON challenge output)
- `field_notes_lambda.py`: Haiku (weekly lab notes)
- All downgrades use `AI_MODEL` env var — instant rollback without code deploy.

**NOT downgraded (quality-critical narrative content):** daily-brief (BoD, TL;DR, training/nutrition, journal coaches), wednesday-chronicle, weekly-plate, nutrition-review, monday-compass, weekly-digest, partner-email.

**Phase 3 — Batch API (deferred):** 50% discount via async batch submission. Evaluated but deferred: $1.11-1.66/month savings doesn't justify the architectural complexity (split monolithic Lambdas into submit/collect pairs, handle batch timeouts, fallback paths). ~$0.04/month additional AWS costs.

**Reasoning:**
1. **Prompt caching is free money.** Same prompts, same quality, 90% off cached tokens. No downside.
2. **Model tiering matches task complexity.** Structured JSON extraction and templated observatory content don't need Sonnet's reasoning depth. Haiku follows format constraints reliably when the preamble is well-specified.
3. **Env var model selection enables safe experimentation.** Can A/B test Haiku vs Sonnet per Lambda without code changes.
4. **Batch API complexity scales poorly at this spend level.** Engineering time better spent elsewhere when savings are ~$1.50/month.

**Files changed:** `retry_utils.py`, `ai_calls.py`, `ai_expert_analyzer_lambda.py`, `coach_narrative_orchestrator.py`, `coach_ensemble_digest.py`, `coach_state_updater.py`, `coach_quality_gate.py`, `coach_history_summarizer.py`, `journal_enrichment_lambda.py`, `hypothesis_engine_lambda.py`, `challenge_generator_lambda.py`, `field_notes_lambda.py`, `site_api_lambda.py` (AI_UNAVAILABLE fix), `constants.py` (layer v41).

**Projected cost impact:** $17-20/month → $8-12/month (40-60% reduction). Shared layer v41 deployed.

---

### ADR-050 — TD-19: UTC as the platform-wide DDB partition convention

**Status:** Active (Phase 2 fix-forward shipped 2026-05-03 v6.8.9; Phase 3 historical migration deferred)
**Date:** 2026-05-03
**Audit:** `docs/audits/TD-19_DATE_PARTITION_AUDIT.md`

**Context:** Discovered during 2026-05-02 HAE webhook verification that source Lambdas disagree on what "today" means: HAE Lambda was partitioning at the source-tz date (PT-local for an iOS device); Withings + every other source uses UTC. A 9pm PT workout would land at `DATE#2026-05-02` (HAE) but `DATE#2026-05-03` (Withings) — same wall-clock event, two different partitions. Cross-source aggregation silently undercounts; cross-source correlations are systematically wrong rather than visibly missing.

**Decision:** Adopt UTC midnight as the canonical partition convention for every ingestion path.

**Reasoning:**
1. **Source-of-truth alignment.** Every wearable / API I'm aware of stores timestamps in UTC internally. PT-local was a layer added on the way in.
2. **Travel + DST are non-issues in UTC.** Matthew travels; PT-local breaks across timezone changes (a "day" becomes 23 or 25 hours).
3. **Cross-source correlation correctness.** With UTC, two sources observing the same instant always land on the same partition.
4. **Reversibility.** UTC → PT presentation is a one-line read-time conversion. PT → UTC requires knowing the original timezone, which we don't reliably store.

**Audit results:** 16 Lambdas + 1 backfill. 8 ✅ already UTC, 2 ❌ PT-local needed fix (HAE + apple_health), 5 ⚪ event-anchored (no fix needed), 1 ⚠ Notion intentionally PT-local (user-typed Date in Notion UI), 1 🪞 backfill mirror (v16 — fixed in lockstep with HAE per TD-14).

**Implementation (Phase 2 — shipped 2026-05-03 v6.8.9):**
- `lambdas/health_auto_export_lambda.py parse_date_str()` converts source-tz timestamp → UTC date string before partition extraction
- `lambdas/apple_health_lambda.py parse_date()` same fix
- `backfill/backfill_apple_health_export_v16.py parse_dt()` same fix (TD-14 parity)
- Notion left as-is (event-anchored to user-typed date — intentional exception)

**Phase 3 (deferred):** Historical migration of existing rows under wrong partitions. DDB cost + idempotency risk warrant a dedicated PR with dry-run + per-item conditional puts. Acceptable interim policy: everything from 2026-05-03 forward is UTC, prior data is on whatever partition it was originally written to.

**Files changed:** `lambdas/health_auto_export_lambda.py`, `lambdas/apple_health_lambda.py`, `backfill/backfill_apple_health_export_v16.py`. Shipped via `cdk deploy LifePlatformIngestion`.

---

### ADR-051 — WR-48: Stale-Source Alerts + Anthropic Canary (observability hardening)

**Status:** Active (shipped 2026-05-03 v6.8.8 + v6.8.9)
**Date:** 2026-05-03
**Spec:** `docs/WR_47_48_ARCHITECTURE_SPEC.md`

**Context:** The 30-day silence (April → May 2026) was undetected because the freshness-checker Lambda had a missing IAM grant (`sns:Publish` on `life-platform-alerts`) — it correctly detected 4-5 stale sources every day but every alert silently `AuthorizationError`'d. Separately, on the morning of 2026-05-03 Anthropic disabled the platform's API key for billing reasons and the daily brief silently failed for ~2 hours before the F-grade brief surfaced it.

Both failures share a pattern: **the platform's own monitoring blind spots are themselves silent failure modes.**

**Decision:** Triple-layer observability hardening for ingestion + AI dependencies:

1. **Restore the freshness-checker SNS:Publish IAM** (the immediate root cause of the 30-day silent failure).
2. **Add a backstop alarm**: `life-platform-freshness-checker-not-emitting` fires if no `StaleSourceCount` metric is emitted in 26h. Closes the "what watches the watcher" gap.
3. **Add the freshness-status MCP tool**: `get_freshness_status` queries DDB directly (independent of the freshness-checker Lambda) — works even if the Lambda silently fails.
4. **Add the daily brief stale-source banner** (Enhancement 1): every brief now prepends "⚠️ Data Status — N source(s) stale" if any source is past threshold. Means a low grade is contextualized as data-vs-signal upfront.
5. **Add an Anthropic canary check**: `lambdas/canary_lambda.py` makes a tiny ($0.0001) Haiku call every 4h and emits `CanaryAnthropicFail` on 401/402/403/429. Detects "API access turned off" / "credits exhausted" within ≤4h.

**Reasoning:**
- Single-layer alerting (one Lambda, one SNS topic, one email subscription) is brittle. The 30-day failure was a single missing IAM grant.
- Multi-layer detection (Lambda + backstop + independent MCP read + brief banner + canary) catches different failure modes the others would miss.
- Cost is negligible (~$0.0006/day for the Anthropic canary; ~$0/yr for the alarms).

**NOT shipped tonight (deferred):**
- WR-48 Enhancement 2 (escalation tiers in the Lambda) — logic is in `get_freshness_status` MCP tool only
- WR-48 Enhancement 3 (Pause Mode awareness) — gated on WR-47
- WR-47 Pause Mode — design spec at `docs/WR_47_48_ARCHITECTURE_SPEC.md`

**Files changed:** `cdk/stacks/role_policies.py` (SNS:Publish for freshness-checker; ai-keys for canary), `cdk/stacks/operational_stack.py` (backstop alarm + canary anthropic alarm), `lambdas/canary_lambda.py` (check_anthropic), `lambdas/daily_brief_lambda.py` (banner), `mcp/tools_labs.py` (get_freshness_status).

---

### ADR-052 — Two-tier alerting: urgent SNS + daily-batched digest

**Status:** Active (shipped 2026-05-16, PR1 of the alert-noise-reduction series)
**Date:** 2026-05-16

**Context:** With 58 CloudWatch alarms all publishing to a single SNS topic (`life-platform-alerts` → `awsdev@mattsusername.com`), the inbox receives multiple emails per day even when nothing is genuinely broken. Past attempts to reduce noise (ADR-043 silent-failure hardening, the 24h→1h period reduction, ADR-048 email Lambda suppression) tuned individual thresholds but kept the underlying model: **every alarm → instant email**. The same `stale-data-source` and `ingestion-error-*` alarms keep firing every day because the model never changed.

Root cause analysis on recurring alarms:
- `slo-source-freshness` re-fires daily until the upstream OAuth/API issue is fixed
- `ingestion-error-whoop` / `ingestion-error-garmin` fire on transient 5xx that gap-aware backfill recovers automatically on the next hourly invocation
- Auth failures (expired OAuth) fire 5×/day until manually rotated

In all three cases, the alarm is telling the operator about a problem that **has already self-healed or will heal on its own**. The signal is preserved; the inbox noise is not.

**Decision:** Split alerts into two SNS topics by urgency:

1. **`life-platform-alerts` (urgent, ~7 alarms, real-time):**
   - `life-platform-daily-brief-errors` (user-facing email delivery)
   - `slo-daily-brief-delivery` (24h SLO)
   - `daily-brief-no-invocations-24h` (silent failure)
   - `life-platform-canary-{ddb,mcp,s3,anthropic}-failure` (site actually broken)
   - `life-platform-dlq-depth-warning` (failed ingestion accumulating)
   - `life-platform-freshness-checker-not-emitting` (backstop-on-backstop, ADR-051)
   - `ai-tokens-platform-daily-total` (cost runaway)
   - `slo-mcp-availability` (claude.ai integration broken)
   - `life-platform-ddb-throttled-requests` (silent data loss)

2. **`life-platform-alerts-digest` (~51 alarms, batched into 8 AM PT email):**
   - All `ingestion-error-*` (16 ingestion + 21 compute Lambdas) — transient errors that gap-fill recovers
   - All email Lambda errors (the daily brief still has its urgent alarm; the rest are recoverable)
   - `slo-source-freshness` (re-fires daily until upstream fixed; one digest line suffices)
   - Duration / latency / memory / item-size warnings (degradation signals, not pages)
   - S3 bucket size, MCP duration, MCP warmer error

The digest topic feeds an SQS queue (`life-platform-alerts-digest-queue`, 25h retention) which is drained by `lambdas/alert_digest_lambda.py` daily at 8 AM PT via EventBridge. The Lambda dedupes by `AlarmName` (one line per distinct alarm regardless of fire count), formats a single SES email, and sends nothing if the queue is empty (no "all clear" spam).

**Reasoning:**
- Two-tier model preserves real-time visibility for the small set of alarms where minutes matter, while batching the long tail that doesn't.
- Personal health/fitness data is daily-granular; nothing actionable about a 2 AM transient Whoop API hiccup.
- Dedup by `AlarmName` means a flapping source produces one digest line, not N emails.
- Operator can still see fire count and latest reason in the digest — full signal, less noise.
- Sets up subsequent PRs (self-healing in PR2, freshness polish in PR3) to also reduce the underlying causes.

**Routing implementation:** `cdk/stacks/lambda_helpers.py` accepts `digest_topic` and `digest=True` params. When both are set, the alarm publishes to the digest topic instead of the urgent topic. `alerts_topic=None` continues to disable alarms entirely (backward compatible). MonitoringStack's `_alarm()` helper accepts a `to_digest=True` kwarg.

**Trade-offs:**
- A real incident that triggers a digest alarm now waits up to 24h to surface in email. Mitigation: urgent topic still catches user-facing breakage (daily-brief, canary, DLQ depth, cost runaway). The digest is for noise that was already not actionable in real-time.
- New infrastructure surface area (SQS, SNS subscription, Lambda, EventBridge schedule). All managed via CDK; revertable by deleting the new resources and re-pointing `digest=True` callers.

**Files changed:** `cdk/stacks/core_stack.py` (digest SNS topic), `cdk/stacks/lambda_helpers.py` (digest routing param), `cdk/stacks/{ingestion,compute,email,operational,mcp,monitoring}_stack.py` (alarm classification), `cdk/stacks/role_policies.py` (`operational_alert_digest()`), `cdk/stacks/operational_stack.py` (SQS + Lambda + EventBridge schedule), `lambdas/alert_digest_lambda.py` (new), `ci/lambda_map.json` (registry entry), `tests/test_alert_digest.py` (unit tests).

**Follow-ups (separate PRs):**
- PR2: Self-healing retries on Whoop/Garmin (currently no retry on transient 5xx); OAuth writeback safety; auth-failure circuit breaker in `ingestion_framework.py`.
- PR3: Multi-day sick-day suppression; staged staleness thresholds (24h warning → 36h digest → 48h urgent).

---

### ADR-053 — S3 Encryption + CloudFront Website Endpoint Incompatibility

**Status:** Active (decision shipped 2026-05-17, v7.20.0)
**Date:** 2026-05-17

**Context:** Phase 2.4 of the v7.x audit (ADR-046 era) migrated the platform S3 bucket from `AES256` default encryption to `aws:kms` with a dedicated CMK (`alias/life-platform-s3`). This was intended as a hardening win: customer-managed key, audit-traceable, rotatable. The migration changed only the bucket default; existing 27k AES256 objects were left as-is per the "new only" decision.

On 2026-05-17, a routine `aws s3 cp site/index.html ...` (without `--sse` flag) inherited the bucket default KMS encryption. CloudFront immediately returned HTTP 400 to readers: *"The object was stored using a form of Server Side Encryption. The correct parameters must be provided to retrieve the object."* averagejoematt.com was broken for ~90 seconds.

Root cause: **S3 website endpoints (`bucket.s3-website-{region}.amazonaws.com`) cannot serve KMS-encrypted objects, regardless of IAM permissions.** This is a well-known AWS limitation. All 4 CloudFront origins for the platform site use the website endpoint (path-based routing: `/site`, `/generated`, etc).

**Decision:** Multi-part:

1. **Revert bucket default to AES256** (shipped 2026-05-17 via `aws s3api put-bucket-encryption`). Any future `aws s3 cp` without `--sse` flag now defaults to AES256, which CloudFront serves cleanly.
2. **Retain the S3 CMK** (`5c50ca02-c187-4338-8704-5b27f1efafca`). Still usable via explicit `--sse aws:kms --sse-kms-key-id <arn>` for sensitive non-website prefixes (e.g., `raw/`, future export archives).
3. **Add CloudFront grant to the CMK** (CDK-shipped in `cdk/stacks/core_stack.py`): `cloudfront.amazonaws.com` service principal scoped by `aws:SourceAccount`. Permission is in place but only takes effect after the future migration in #4.
4. **Defer S3-website→REST+OAC migration** (separate ADR-054). KMS-encrypted public content requires this migration; deferred because the cost (4 CloudFront origins repointed, CloudFront Function for directory-→-index.html rewrite, OAC bucket policy migration, extensive regression testing) outweighs the benefit (compliance signaling for a single-user personal platform).

**Reasoning:**
- The website-endpoint architecture is well-suited to this static site's needs (index docs, error pages, simple path routing) and works correctly with AES256.
- Phase 2.4's KMS migration was correct in spirit (CMK > S3-managed key for audit/rotation) but didn't account for the existing CloudFront origin architecture.
- The CMK isn't deleted because explicit-KMS use cases still exist (sensitive `raw/` data, future export bundles). Bucket default is just AES256.
- Adding the CloudFront grant now means the future REST+OAC migration only requires changing CloudFront, not redoing IAM.

**Trade-offs:**
- KMS encryption is no longer the platform default for new uploads — slight hardening regression. Mitigated by per-prefix explicit-KMS for any sensitive new content.
- Future devs may not realize the website-endpoint constraint and re-attempt the KMS default. Mitigation: this ADR + the comment block at `cdk/stacks/core_stack.py:85-93`.

**Files changed:** `cdk/stacks/core_stack.py` (CMK grant for CloudFront), bucket encryption config (manual AWS CLI), `docs/CHANGELOG.md` (v7.20.0 entry).

**Follow-ups:** If real subscribers join the platform (then KMS-on-public has trust value), execute the website→REST+OAC migration per ADR-054.

---

### ADR-054 — CloudFront Origins: S3 Website Endpoint over REST+OAC (Status Quo)

**Status:** Active (decision 2026-05-17, v7.20.0)
**Date:** 2026-05-17

**Context:** Following the ADR-053 KMS incompatibility, the question was: migrate CloudFront S3 origins from website-endpoint to REST-endpoint + Origin Access Control (OAC)?

REST+OAC is the AWS-recommended modern pattern for CloudFront → private S3. It supports KMS-encrypted objects, restricts S3 access to CloudFront only (no public bucket policy needed), and is HTTPS-native to origin.

Cost of migration:
- 4 CloudFront distributions to repoint origins (averagejoematt.com, dash, blog, buddy)
- New CloudFront Function (or Lambda@Edge) to rewrite `/path/` → `/path/index.html` (website endpoint does this automatically; REST does not)
- CloudFront custom error responses to replicate website-endpoint 404 handling
- Bucket policy migration from public-anonymous to OAC-only
- CDK changes across `web_stack.py` and per-distribution stacks
- Substantial regression testing across 4 distributions and ~30+ HTML files

Benefit:
- KMS encryption on public-served content (ADR-053 unblocked)
- Defense-in-depth: S3 not publicly readable (only CloudFront has access)
- AWS-best-practice alignment

**Decision:** Defer the migration. Keep S3 website endpoints for all 4 CloudFront origins. Document the incompatibility (ADR-053). Re-evaluate when one of the following becomes true:
- Platform takes on real subscribers (KMS-on-public becomes a trust signal worth the cost)
- AWS deprecates S3 website endpoints (no current sunset announcement)
- An OAC-only requirement emerges (regulated content, paid tier, etc.)

**Reasoning:** For a single-user personal health platform with public, intentionally-readable content (averagejoematt.com is a public blog), the actual security model isn't improved by hiding S3 from public reads — the data is meant to be public. The compliance signaling value of KMS-on-public is real but currently abstract.

**Trade-offs:**
- Stuck with S3-managed AES256 for public content (ADR-053). Modern alternatives unavailable.
- Cannot easily migrate sensitive prefixes (e.g., `raw/`) to a more restrictive read pattern without breaking the website-endpoint shared bucket.

**Files changed:** None (decision-only ADR). `docs/DECISIONS.md` (this entry).

**Follow-ups:** None scheduled. Revisit per trigger conditions above.

---

### ADR-055 — Coach Prediction Loop Closure: 4-Step Chain

**Status:** Active (v7.15.0–v7.18.0, 2026-05-17)
**Date:** 2026-05-17

**Context:** ADR-047 promised "stateless prompts → stateful agents" — coaches that make predictions, get evaluated against outcomes, and grow more calibrated over time. The audit assumed P5.7 (the auto-evaluator) was a 982-LOC skeleton needing implementation.

Reality: the evaluator (`lambdas/coach_prediction_evaluator.py`) was already fully built and running daily at 9 AM PT, processing 25-37 predictions per day across 8 coaches. The verdicts were written to two places (PREDICTION# status updates + LEARNING# audit records) — but **no consumer was reading them**. The only LEARNING# consumer (`coach_observatory_renderer.py`) matched only `type=position_revision`, a type the evaluator never wrote. The MCP `tool_get_predictions` queried the legacy `SOURCE#coach_thread#` partition, not the post-ADR-047 `COACH#{coach_id}` partition. The loop was open at the consumer side, not the producer side.

Compounding issue: 100% of recent evaluations resolved `inconclusive` because coaches were predicting against prose metric descriptions ("REM percentage stability and correlation with stress markers") that didn't map to the evaluator's 16-key `METRIC_SOURCES` allowlist.

**Decision:** Close the loop in 4 sequential steps over one session:

1. **v7.15.0 — Expose verdicts via MCP** (`tool_get_coach_track_record`): reads `COACH#{coach_id}/LEARNING#` over configurable window, returns by_outcome + hit_rate_pct + by_subdomain + by_metric + recent_evaluations. Accepts bare or `_coach`-suffixed coach IDs.
2. **v7.16.0 — Forward fix at extraction time** (`coach_state_updater.py`): added `MEASURABLE_METRICS` allowlist + `_normalize_metric_hint()` helper. Extractor system prompt updated to instruct Haiku to return one of 15 allowlisted keys or null. Write-boundary normalization marks unsalvageable predictions as `evaluation.type="qualitative"` (evaluator already skips qualitative).
3. **v7.17.0 — Historical backfill** (`deploy/backfill_prediction_metrics_dryrun.py`): walked 504 active machine-type predictions, normalized 319 (prose → allowlisted), demoted 179 to qualitative, left 6 alone. Per-record audit fields (`backfilled_at`, `backfill_action`).
4. **v7.18.0 — Observatory surface** (`coach_observatory_renderer.py`): per-coach card gains `track_record` field with 30-day decided counts + hit_rate_pct + summary string. Returns null when no decisions yet (avoids misleading 0% display).

**Reasoning:**
- The plan's "build the evaluator" framing was outdated; the real gap was consumer-side. Reframing was honest and cheaper than building duplicate evaluator infra.
- The 4 steps map to producer (#2 forward fix, #3 historical) → reader (#1 MCP) → display (#4 observatory). Each step is independently shippable and reversible.
- The MEASURABLE_METRICS allowlist is duplicated in `coach_state_updater.py` and `coach_prediction_evaluator.py`; documented "keep in sync" in both. Future consolidation possible but not blocking.

**Validation timeline:** The 325 backfilled+forward-fix-eligible predictions need 7-30 days to hit their evaluation windows and produce real `confirmed`/`refuted` counts. Until then the chain is code-complete but functionally unverified end-to-end. `tool_get_coach_track_record` currently returns `decided_count: 0, hit_rate_pct: null` for all coaches (correct — no verdicts yet) but the path is exercised.

**Trade-offs:**
- Normalizer is heuristic (substring map) — some remaps may be semantically wrong (e.g., a multi-metric prose prediction mapped to one allowlisted key). Acceptable: at-worst-noisy beats current at-worst-daily-inconclusive.
- The 179 qualitative-demoted predictions will never resolve. Acceptable: they weren't going to resolve usefully under the old path either.

**Files changed:** `mcp/tools_coach_intelligence.py`, `mcp/registry.py`, `lambdas/coach_state_updater.py`, `lambdas/coach_observatory_renderer.py`, `deploy/backfill_prediction_metrics_dryrun.py` (new), `tests/test_wiring_coverage.py` (passive update), `docs/CHANGELOG.md` (v7.15–v7.18).

**Follow-ups:**
- 7-30 days from now: verify non-zero `decided_count`. If still zero, the evaluator has a separate metric-resolution bug.
- Wire `track_record` into daily-brief preamble per-coach (Phase 5.8 cousin work).
- Once hit_rate_pct is meaningful (≥14 days): tie coach quality gate threshold to it.

---

### ADR-056 — SIMP-2 Ingestion Framework: 8 Sources Migrated, 6 Pattern-Exempt

**Status:** Active (v7.10.0–v7.13.0, 2026-05-17)
**Date:** 2026-05-17

**Context:** The v7.x audit identified the SIMP-2 framework (`lambdas/ingestion_framework.py`) as a major debt-paydown opportunity: 80% of every ingestion Lambda was duplicated boilerplate (auth refresh, gap detection, S3 archival, DDB writes, validation, structured logging). The plan called for migrating all 13 ingestion Lambdas to the framework.

**Decision:** Migrate the 8 Lambdas that fit the framework's per-day-fetch shape. Exempt the 6 that don't, with explicit per-source rationale.

**Migrated (8 / 14):**
- weather (pre-existing proof of concept, 2026-03-09)
- todoist (v7.10.0)
- habitify (v7.11.0) — also added `refresh_today=True` flag to framework for intra-day-updated sources
- withings (v7.12.0)
- strava (v7.12.0)
- eightsleep (v7.13.0) — JWT auth, no refresh-token endpoint, full re-login on each cold start
- whoop (v7.13.0) — first user of framework's `sk_suffix` for per-workout sub-records; reserved concurrency=1 still pending AWS quota raise
- garmin (v7.13.0) — most complex, garth library, native deps in separate layer

Cumulative reduction: **5,560 LOC → 3,177 LOC (−2,383 LOC / −43%)** across the 8 migrations.

**Exempt (6 / 14):**
- notion — date-RANGE fetch with multi-record-per-date via sub-record SKs (`DATE#X#TEMPLATE#journal`). Framework iterates per-date and writes one record. Forcing would require framework changes.
- macrofactor — S3-triggered CSV import. Date is derived from file, not a schedule.
- apple_health — S3-triggered XML, parses years of data per upload, multi-record per date.
- health_auto_export — API Gateway webhook receiving real-time event batches (CGM, BP, state of mind). Framework's polling loop doesn't apply.
- dropbox_poll — every-30-min poll checking S3 for new uploads. Not date-driven.
- food_delivery — quarterly CSV import. Framework's gap-detection assumptions don't fit 90-day cadence.

**Reasoning:**
- Forcing the framework on the 6 exempt sources would have made each Lambda LONGER and uglier than the standalone implementations.
- The 8 migrated sources all share OAuth + per-day-fetch + DDB-write shape — they're the ones where framework actually reduces complexity.
- Future Notion migration would require framework features (date-range primitive, multi-record `sk_suffix` factory, bucket-by-date helper) — ~1 week of framework work. Not worth doing unless a second range-fetch source emerges.

**Trade-offs:**
- 6 ingestion Lambdas remain on the old pattern. Each has its own retry/auth-breaker/validation. Drift risk: a bug fix in the framework doesn't automatically apply to them.
- Mitigation: shared modules (`http_retry.py`, `auth_breaker.py`, `numeric.py`) are still importable by the standalone Lambdas. They're not isolated, just not orchestrated.

**Files changed:** All 8 migrated `lambdas/*_lambda.py` files (full rewrites or near-full), `lambdas/ingestion_framework.py` (`refresh_today` flag added for habitify), `tests/test_numeric.py` (shim list pruned per migration), `tests/test_ddb_patterns.py` (D4 gap removed for garmin), `docs/CHANGELOG.md` (v7.10–v7.13).

**Follow-ups:**
- Whoop reserved concurrency=1: blocked on AWS Support raising L-B99A9384 quota from 10 → 50. Manual ticket required (Business+ support plan needed for API path).
- If a second range-fetch source emerges, extend framework with date-range primitive + multi-record support, then migrate Notion as second user.

---

### ADR-057 — Audit Items Formally Closed With Rationale

**Status:** Active (v7.19.0, 2026-05-17)
**Date:** 2026-05-17

**Context:** The v7.x audit produced ~130 findings across 8 phases. After 2 days of intensive work shipping ~70 of them, several items remained on the backlog that — on closer inspection — should not be done. Leaving them as "pending" implies future work that won't happen; formal closure with rationale prevents repeat re-discovery.

**Decision:** Close the following items as **"deferred-with-rationale, not actionable as written"**:

| Item | Rationale |
|---|---|
| **P4.3 Split `intelligence_common.py`** | 1556 LOC has only 1 active importer (ai_expert_analyzer — corrected from "daily_brief" 2026-05-17 per V2 P2.10). Splitting would multiply imports without reducing complexity for the actual consumer. Revisit only if a second major importer emerges. |
| **P4.6 HAE handler registry refactor** | 1492 LOC already organized per-data-type. A registry pattern would be cleanup-only with no behavior change. Revisit only if a 6th+ data type is added. |
| **P8.11 Site-api pagination** | `/api/changes-since` and `/api/observatory_week` already bounded by natural query windows (single-day, single-week). Not a practical risk. Revisit only if a new endpoint surfaces an actually-unbounded query. |
| **P8.6 Lambda Power Tuning campaign** | Most Lambdas already at 256 MB (minimum effective tier). Only mcp (768) and daily-brief (768) have headroom — but daily-brief sends real emails on invocation, making it unsafe to tune. Realistic savings: $1-3/mo for ~30 min work per safe-to-tune target. Better ROI elsewhere. |
| **P1.2 Orphaned WAF cleanup** | Audit was wrong. WAF protects HAE webhook, isn't orphaned. Still billing $4.75/mo but it's load-bearing. **(See "Correction (2026-07-05)" below — this claim did not hold up.)** |
| **P5.2 board_ask shared preamble caching** | Each persona system prompt is ~80 tokens, below Anthropic's ~1024-token cache minimum. `cache_control` annotation shipped (v7.14.0) but is no-op. Plan's $2/mo savings overestimated. |
| **P6 Multi-user / Cognito (entire phase)** | ~4 FTE-weeks for a single-user personal platform. Revisit only when a second real user is on the horizon. |
| **P8.13 Cross-region DR** | Overkill for personal platform. Deferred-as-planned. |
| **P5.9 Batch API** | Deferred to July 2026 reconsideration per original plan. |

**Reasoning:**
- A formally-closed item with documented rationale is more useful than an indefinitely-open one. Future audits should not re-surface these without new triggering evidence.
- Closure ≠ rejection of the underlying concept. Each rationale describes the specific trigger that would re-open the item.
- Honest accounting: the original audit had ~10% wrong-premise findings (P1.2 WAF, P5.2 caching, P5.7 already-built). That's normal for fast audits; this ADR documents the corrections.

**Trade-offs:**
- Risk of future "we should split intelligence_common.py" suggestions ignoring this ADR. Mitigation: cite ADR-057 when the suggestion recurs.

**Files changed:** Task list updates (TaskUpdate with rationale on tasks #44, #46, #50), `docs/CHANGELOG.md` (v7.19.0, v7.20.0), this ADR.

**Follow-ups:** None. Closure is final pending the specific trigger conditions per item.

**Correction (2026-07-05, #500):** the P1.2 rationale above ("WAF protects HAE webhook") was
itself wrong, not just the original "orphaned" audit finding it was closing out. WAFv2 cannot
attach to API Gateway HTTP APIs at all (only REST APIs, ALB, AppSync, and CloudFront) — the HAE
webhook edge is an HTTP API, so a WAF ACL was never actually in the request path protecting it.
WAF was removed platform-wide 2026-06 (billing line is gone); the webhook's actual protection is
(1) the Lambda's own bearer-token check (`health_auto_export_lambda.py`, constant-time compare)
and (2) the API Gateway stage's throttle settings (`cdk/stacks/ingestion_stack.py`, now codified
per #500/D-7). Site-facing rate limiting elsewhere on the platform is DynamoDB-backed and
in-Lambda (`rate_limiter.py`), not WAF-based, per the same 2026-06 removal — see CLAUDE.md's
"Rate limiting is DynamoDB-backed" convention. This note amends the record rather than rewriting
the original (wrong) rationale above, per ADR discipline.

---

**Verified:** 2026-05-19

## ADR-058: Experiment Restart — single source of truth for genesis date

**Status:** Accepted (2026-05-23)
**Anchor:** EXPERIMENT_START_DATE = 2026-05-18
**Baseline:** 303.68 lbs (Withings reading on genesis)

### Decision
Re-anchor the experiment to a fresh genesis date. All pre-genesis raw data is
preserved in DynamoDB but tagged `phase=pilot` and hidden from public surfaces,
scoring, coaching, chronicle, and grading. The genesis date is the single
source of truth — everything (Day-N counter, character sheet, coach predictions,
challenges, experiments, chronicle, public site) anchors to it.

### Implementation
- **Config-driven constants** — `config/user_goals.json` is the canonical source of
  truth. `lambdas/constants.py` is regenerated from it via
  `deploy/sync_constants_from_config.py`.
- **DDB phase tagging** — `restart_phase_tag.py` marks every record under
  `USER#matthew#SOURCE#*` with `phase=pilot` (sk date < genesis) or
  `phase=experiment` (sk date ≥ genesis). Cross-phase identity records
  (subscribers, genome, profile, config) are never tagged.
- **Read-path filter** — `lambdas/phase_filter.py` provides `with_phase_filter()`
  used by `site_api._query_source`, `mcp.core.query_source`, and named
  endpoints/tools. Default: phase=pilot hidden. `include_pilot=True` to bypass.
- **Intelligence wipe** — `restart_intelligence_wipe.py` tombstones coach
  state via UpdateItem add-flag (interpretation B): the original content
  stays intact under `tombstone=true`. Reversible by removing the flag.
- **Character rebuild** — `restart_character_rebuild.py` invokes
  `character-sheet-compute` for every day genesis→today with `force=true`.
  `fetch_date` filters tombstones so the cascade starts at Level 1.
- **Chronicle** — `restart_chronicle_handler.py` archives chronicle HTML to
  `*/archive/pilot/` (tombstone-overwrite originals, IAM blocks DeleteObject).
  Indexes rewritten to Day-1 placeholder. Optional --resurrect-sk to keep + redate.
- **Site copy** — `restart_site_copy_sync.py` regenerates
  `site_constants.js` journey block + hero copy, sweeps "Day 1 · 307 lbs" /
  Feb-22 references, S3 syncs, CloudFront invalidates.
- **Orchestrator** — `restart_pipeline.py` chains all of the above given
  `--genesis YYYY-MM-DD`.

### Consequences
- The system is **repeatable**: a one-command pipeline can move genesis to a
  new date and re-converge all surfaces.
- All pre-genesis data is preserved and recoverable (interpretation B
  preserves item content under tombstone flags; raw S3 objects are
  tombstone-overwritten but accessible at `*/archive/pilot/*`).
- Public-facing copy has no acknowledgement of any prior attempt. Per
  Matthew's D decision: full scrub, including the platform-build narrative.
- Six pre-existing tech-debt failures in the integration test suite are
  not in scope: notion secret deletion, 62-message DLQ, stale layer versions
  on 6 Lambdas (now resolved as side-effect of v53 deploy).

### §13. Scheduled re-evaluation of the phase filter (added 2026-07-04, #383)

**Gap this closes:** the 2026-07 product review (RESTART-PHASE-FILTER-REEVAL)
and the backlog scoring both cite "ADR-058 §13" as the place the 30/60/90-day
phase-filter re-evaluation was promised — but the promise was never actually
written into this ADR. This section is that missing commitment, recorded
retroactively while building the checkpoint mechanism (#383).

**Decision.** The read-path filter's default (`phase=pilot` hidden) is not a
one-time call — how much pre-genesis history should stay hidden from public
surfaces, coaching, and scoring is an empirical question that gets revisited
at **30, 60, and 90 days** after `EXPERIMENT_START_DATE`, so the default is
checked against how the hiding actually played out (where it protected the
"fresh start" framing vs. where it hid context a coach or reader needed).

**Mechanism.** `deploy/phase_filter_checkpoint.py` computes each checkpoint's
due date relative to `EXPERIMENT_START_DATE` (so it re-derives correctly
across any future restart, not a fixed calendar date), and gathers a
deterministic diagnostic snapshot (every `include_pilot=True` bypass site in
`lambdas/`+`mcp/`, plus the current EXPERIMENT_SCOPED source list from
`phase_taxonomy.py`) to ground the review. `status` reports what's due;
`record` writes the verdict — **keep-as-is / widen-read-paths /
adjust-taxonomy**, even "no change" — to a durable audit trail
(`docs/reviews/PHASE_FILTER_CHECKPOINTS.{json,md}`) and refuses to record a
checkpoint before its due date (`--force` is testing-only). Any verdict that
widens a read path is implemented through `phase_taxonomy.py` — the single
classification source (ADR-077) — never as a one-off filter bypass.

**Status:** mechanism shipped 2026-07-04. The current cycle's genesis
(2026-06-14) puts the 30-day checkpoint at **2026-07-14**, 60-day at
2026-08-13, 90-day at 2026-09-12. The 30-day review itself is Matthew's
judgment call on real usage and had not yet happened as of this write-up
(only 20 days post-genesis) — tracked in the audit trail above, not guessed
here.

## ADR-059: Deploy Governance — `restart_pipeline.py` as the Single Safe Entry Point for Multi-Step State Changes

**Status:** Accepted (2026-05-24)
**Sits alongside:** ADR-058 (restart pipeline), ADR-032/033/046 (S3 safety).

### Context

`deploy/` has grown to 66 scripts (28 Python + 31 Bash + helpers). The May 2026 restart alone added 9 new scripts. Without a documented governance model, the next operator has no way to know which script is safe to run alone vs which is a sub-step of an orchestrator. The recent restart effort proved that even with idempotent sub-scripts, running them in the wrong order or with stale local state can leak pre-genesis content into the public site.

### Decision

**For any operation that mutates more than one DDB partition OR more than one S3 prefix in a single session, the operator MUST go through `deploy/restart_pipeline.py`.**

Direct invocation of sub-scripts (`restart_phase_tag.py`, `restart_intelligence_wipe.py`, `restart_character_rebuild.py`, `restart_chronicle_handler.py`, `restart_site_copy_sync.py`, `restart_docs_update.py`, `restart_verify_rendered.py`) is reserved for:

1. Pipeline development / testing
2. Surgical fixes when only one sub-step needs replaying
3. Read-only inspection (every sub-script supports `--dry-run`)

The orchestrator provides guarantees no individual sub-script does:
- **Ordered execution** — sub-steps depend on each other (constants regen precedes phase-tag, etc.)
- **Idempotency** — re-running with the same `--genesis` is a no-op
- **Verify-rendered hard gate** — the run fails if public surfaces still show pre-genesis state

### Consequences

- One-off scripts older than 30 days are moved to `deploy/archive/<YYYY-MM-DD>/` once their execution is logged.
- `deploy/OPERATIONAL_RUNBOOK.md` is the single index keyed by symptom.
- New operational scripts must be either: wrapped into the pipeline as a sub-step, or dated as one-off (auto-archive after 30 days).
- The `restart_verify_rendered.py` URL+token list is institutional memory. New public surfaces (pages, endpoints) must be added to it in the same PR that introduces them.

### Non-decisions

- Per-Lambda surgical deploys (`deploy_lambda.sh`) are unchanged.
- Normal `cdk deploy` for infra changes is unchanged.
- This scopes only **state-mutating operational workflows** — not feature deploys.

---

## ADR-060: Hevy Workout API as Independent Source — Dedicated Secret, Webhook + Cursor Backfill

**Date:** 2026-05-25
**Status:** Accepted
**Spec:** `SPEC_HEVY_AND_NUTRITION_BRIDGE_2026_05_25` (WS-1).

### Context

Hevy is a workout-logging app Matthew uses alongside MacroFactor. Previously workouts arrived ONLY via the MacroFactor Dropbox export (manual upload). Spec adds Hevy as a first-class data source so workouts log automatically with no manual export. Both Hevy and the MacroFactor workout path stay live — they're independent apps, not duplicates (different workouts on different days), so records are additive.

### Decision

1. **Dedicated secret `life-platform/hevy`** holding `{api_key, webhook_secret}`. Per ADR-014: NOT bundled into `api-keys`. Mirrors `life-platform/habitify` precedent.

2. **Two ingestion modes** writing to the same normalized records:
   - **Webhook (primary, real-time):** `hevy-webhook` Lambda exposes a FunctionURL with `auth_type=NONE`; auth is enforced via the `webhook_secret` in the Hevy-sent header (direct-match OR HMAC-SHA256 of the body). Webhook payload contents are NOT trusted — only the `workout_id` is extracted, then full data is fetched via the authenticated `GET /v1/workouts/{id}`.
   - **Backfill (cursor-based catch-up):** `hevy-backfill` Lambda runs daily at 13:00 UTC (06:00 PT), reads a cursor from `USER#system / INGESTION_CURSOR#hevy`, walks `GET /v1/workouts/events?since=<cursor>`, ingests anything the webhook missed, and persists the new cursor on success.

3. **Schema follows platform convention** (`USER#matthew#SOURCE#hevy` + `DATE#{yyyy-mm-dd}#WORKOUT#{hevy_id}`), NOT the spec's proposed `USER#matthew / WORKOUT#...`. Verified against live table before authoring. Weights normalize to kg at ingest (Hevy account may be lbs); original unit recorded in `original_unit`.

4. **Raw payloads archived to `s3://matthew-life-platform/raw/hevy/{id}.json`** so derived fields can be recomputed without re-hitting Hevy (matches the platform's re-derivation discipline).

5. **`source: "hevy"` + `workout_uid: "hevy:<id>"`** on every record. Hevy never dedupes against MacroFactor records — different apps, different workouts.

### Accepted risk

- Hevy explicitly warns the API surface may change. Mitigations: schema_version pinned in the normalized shape; the webhook payload parser is liberal (multiple field-name shapes accepted); the backfill cursor falls back gracefully if `next_cursor` is missing.
- Webhook auth mechanism is best-guessed (Hevy's docs are sparse). The verifier accepts both direct-string match and HMAC; tighten to one once the actual mechanism is observed.

### Consequences

- One new secret + 2 Lambdas in `LifePlatformIngestion` (CDK).
- `pytest tests/test_hevy_common.py` (9 tests) covers normalization + signature verification with synthetic payloads. A `tests/test_hevy_live.py` parity test is deferred until a real workout is observed end-to-end.
- Hevy Pro subscription cost: ~$5/month (paid by Matthew, not platform infra).
- Site/UI changes (source attribution) are out-of-scope for WS-1; deferred to WS-3 once schema migration of historical MacroFactor workouts is decided.

### Non-decisions

- MacroFactor Dropbox workout pipeline is **NOT removed** — runs parallel.
- Cross-source workout dedupe between Hevy and MacroFactor is **NOT introduced** (they're independent apps).
- The MacroFactor unofficial-API client (WS-2) is **NOT included** in this ADR — see ADR-061.

---

## ADR-061: MacroFactor Unofficial-API Puller as Tier 1 Food-Level Nutrition Path

**Date:** 2026-05-25
**Status:** Accepted
**Spec:** `SPEC_HEVY_AND_NUTRITION_BRIDGE_2026_05_25` (WS-2).

### Context

The platform's current food-level nutrition path is a manual MacroFactor Dropbox export. The goal is no-touch food-level ingestion (food names, brands, per-entry servings — not just aggregate macros). FatSecret, Cronometer, and Terra/Vital were all rejected (see spec §3.7); the unofficial MacroFactor API is the only path that satisfies both "food-level" and "no manual upload" without changing apps.

### Decision

1. **Pure-Python Firebase + Firestore client** (`lambdas/macrofactor_client.py`). NOT the npm `@sjawhar/macrofactor-mcp` package or the Rust `macro-factor-api` crate. Both are unofficial undocumented community libraries; depending on either at runtime adds a fragile remote-distribution risk to a critical path. Instead: we reverse-engineered the Firebase config + Firestore collection paths from both libraries on 2026-05-25, and re-implemented the minimum surface in pure Python (stdlib `urllib` only). What we learned:
   - **Firebase web API key** for the `sbs-diet-app` project is **public** (`AIzaSyA17Uwy37irVEQSwz6PIyX3wnkHrDBeleA`, hardcoded in the Rust crate). Firebase web keys are designed to be embedded — security comes from Firebase Auth rules + bundle ID validation, not the key being secret.
   - **Bundle ID header** `X-Ios-Bundle-Identifier: com.sbs.diet` is required on auth requests.
   - **Firestore base** `https://firestore.googleapis.com/v1/projects/sbs-diet-app/databases/(default)/documents`.
   - **Food log path** `users/{uid}/food/{YYYY-MM-DD}` — single doc per day, food entries as map fields keyed by epoch-micros id.
   - Food entry field codes (one-letter): `t`=name, `b`=brand, `c`=calories, `p`=protein, `e`=carbs, `f`=fat, `g`=grams, `q`=quantity, `s`=serving, `h`=hour, `mi`=minute. Values stored as `stringValue` (MF Android parser convention).

2. **Dedicated secret `life-platform/macrofactor`** holding `{username, password}`. Per ADR-014: NOT bundled into `api-keys`. Mirrors `life-platform/habitify` precedent.

3. **The secret holds Matthew's actual MacroFactor account password** (Firebase email/password auth — no scoped API key exists for MacroFactor). **Accepted risk** per spec §3.0:
   - Encrypted at rest by AWS KMS.
   - Only `mf-puller` Lambda role can read it.
   - Rotate immediately if you change your MF password.

4. **Architecture (isolation guarantee):** the puller Lambda NEVER raises. Hard failures (auth, schema drift, App Check changes) are caught, logged, and written into a health record at `USER#system / INGESTION_STATE#macrofactor_api`. The platform doesn't notice. Matthew falls back to Tier 2 (manual Dropbox export) when the digest alert says "Tier 1 down".

5. **Tier 1 writes alongside Tier 2 — NOT instead of it.** Both write to the same nutrition-record shape; the `entry_uid` is derived from a stable hash of `date + entry_id + food_name` so dedupe works across tiers. Priority when both have the same date is configurable; default = Tier 1 authoritative.

6. **Schedule:** daily 14:00 UTC = 07:00 PT. Rolling 3-day lookback window self-heals small gaps without re-processing the whole archive every run.

### Accepted risks

- **Unofficial undocumented API.** MacroFactor can change the Firestore schema, add App Check enforcement, or block our bundle-ID header at any time. Mitigations: per-request best-effort, status record with `consecutive_failures` counter, fallback path (Tier 2) preserved.
- **Account password in Secrets Manager.** Risk acknowledged in `deploy/create_macrofactor_secret.sh` interactive prompt. Operator must explicitly type `y` to proceed.
- **Token refresh requires real account credentials.** Lambda re-authenticates each cold start; warm containers refresh idToken via `securetoken.googleapis.com/v1/token` when within 5min of expiry. Refresh-token never expires unless MF revokes it.

### Consequences

- One new secret + 1 new Lambda (`mf-puller`) in `LifePlatformIngestion`.
- New DDB partition: `USER#matthew#SOURCE#macrofactor_api` with `NUTRITION#{date}#{entry_uid}` SK pattern.
- Raw payloads archived to `s3://matthew-life-platform/raw/macrofactor_api/`.
- `pytest tests/test_macrofactor_client.py` (16 tests) covers Firestore value decoding, field-code → schema mapping, stable-uid determinism, phase tagging.
- Parity diff (spec §3.8) deferred — Matthew runs a manual export later, compares Tier 1 vs Tier 2 records for a 7-day window, signs off on which fields are export-only and adjusts `priority` constant accordingly.

### Non-decisions

- **Workout ingestion via MacroFactor unofficial API** — out of scope of the initial cut, BUT added in a follow-up commit (62549d0) on 2026-05-25: the same puller now pulls both food log AND `users/{uid}/workoutHistory` in a single signed-in session, so MF workouts get the same Tier-1/Tier-2 treatment as nutrition.
- **Periodic credential health check** beyond the puller's own failure tracking — not added.

### Update 2026-05-25 — Tier 1 BLOCKED by Firebase App Check

**Status (earlier today): ⚠️ Tier 1 deployed but disabled.**

First live test invocation (mf-puller against the real `life-platform/macrofactor` secret) returned:
```
HTTP 401: "Firebase App Check token is invalid."
```

App Check enforcement on the auth endpoint itself is **new since the community libraries were written**. Confirmed by probing 5 alternate paths — all fail:

| Approach | Result |
|---|---|
| Android package header | 403 — Firebase restricts to iOS bundle only |
| `/v3/verifyPassword` (pre-2018 endpoint) | 404 — removed |
| Referer + Origin spoof | 403 — same iOS-bundle restriction |
| No bundle header | 403 |
| `X-Firebase-AppCheck: debug` token | 401 — would need MF to allow our debug token in their Firebase Console |

The remaining theoretical paths all require either:
- Real device attestation (DeviceCheck on iOS, Play Integrity on Android) — **impossible from a Lambda**, or
- Capturing a live App Check token from Matthew's MF mobile app and refreshing manually every ~1 hour — too brittle to operate.

### Update 2026-05-25 (same day, later) — Tier 1 TORN DOWN

**Status: ❌ Tier 1 removed. Decision recorded for institutional memory.**

Initial "park indefinitely" plan reversed: when the disabled Tier 1 surface produced a GitHub secret-scanning alert on the hardcoded Firebase Web API key (`AIzaSy...`), it became clear that parking the code costs ongoing maintenance + audit surface without providing recoverable optionality. If a future App Check workaround appears, it will appear in updated community libraries (Rust `macro-factor-api`, npm `@sjawhar/macrofactor-mcp`); we'd re-extract from the new state of the art anyway, not from this stale code.

**Removed today:**
- `lambdas/macrofactor_client.py` (unofficial Firebase + Firestore client)
- `lambdas/macrofactor_puller_lambda.py` (the puller Lambda code)
- `tests/test_macrofactor_client.py` (16 tests for the deleted client)
- `deploy/create_macrofactor_secret.sh` (the secret-creation script)
- `MacrofactorPuller` definition in `cdk/stacks/ingestion_stack.py`
- `ingestion_macrofactor_puller()` in `cdk/stacks/role_policies.py`
- `life-platform/macrofactor` from `KNOWN_SECRETS` (test_iam_secrets_consistency.py)
- `macrofactor_api` from `mcp/tools_hevy.py` `_WORKOUT_SOURCES` + `mcp/registry.py` enum
- `macrofactor_api` from `ci/lambda_s3_paths.json` exceptions
- AWS resources (via CDK deploy): `mf-puller` Lambda, its IAM role, the EventBridge rule
- AWS Secrets Manager: `life-platform/macrofactor` (force-deleted, no recovery window)
- DDB record at `USER#system/INGESTION_STATE#macrofactor_api`

**What remains:**
- This ADR — kept as institutional memory: *we already attempted this; here's why it didn't work; here's the threshold for re-attempting*. Future-Claude or future-Matthew can read it and decide whether re-attempting is worth it without re-discovering App Check independently.
- Tier 2 (MacroFactor Dropbox export → `dropbox-poll` → `macrofactor-data-ingestion`) — unchanged, fully operational, the *only* MF path for both food and workouts.
- The MCP workout bridge (`tool_get_workouts` with `_expand_legacy_aggregate`) — unchanged, still maps `macrofactor_workouts` legacy daily-aggregates into per-workout views with `source="macrofactor_export"`.

**Re-attempt threshold:** A credible App Check workaround lands in `macro-factor-api` or `@sjawhar/macrofactor-mcp` AND someone (Matthew or future-Claude) confirms it works against a live MF account from a Lambda environment. Re-implementation would extract fresh from the new community library; this ADR documents the prior attempt's specifics.

**Practical impact:** Tier 2 (manual MacroFactor Dropbox export) is the active food-level + workout path. Hevy (ADR-060) is the active no-touch workout path. There is currently no no-touch path for food-level nutrition — the explicit "accepted risk" of WS-2 has materialized on day one, and we are accepting it indefinitely.

---

## ADR-062: Migrate Claude inference from direct Anthropic API to AWS Bedrock

**Date:** 2026-05-27
**Status:** Code complete; cutover deploy gated on the Anthropic Bedrock use-case form (a one-time AWS-console action).

### Context

The platform called Claude via the direct Anthropic API (`urllib` POST to
`api.anthropic.com/v1/messages`) using a prepaid-credit API key stored in
`life-platform/ai-keys` + `life-platform/site-api-ai-key`. On 2026-05-27 the
prepaid balance hit zero and **every** AI feature died at once — daily-brief
coaches returned `[AI_UNAVAILABLE]`, briefs froze at Grade 43 (F), `/api/ask`
500'd. The failure had no graceful warning; it surfaced via inbox noise hours
later. The operator had also barely *used* the platform that month (auto-
generated content still ran daily and burned the credits), so the spend
produced little personal value.

### Decision

Move Claude inference to **AWS Bedrock** (`bedrock-runtime invoke_model`):
- Bills through the AWS account — consolidated with the rest of the infra
  spend, covered by Cost Explorer + the existing budget alarm. **No prepaid-
  credit cliff**: usage just appears on the AWS bill.
- Auth is **IAM** (`bedrock:InvokeModel`), not an API key.
- The InvokeModel response for Claude is byte-identical to the direct
  Anthropic Messages API, so all downstream parsing/validation is unchanged.

### Key implementation facts

- **Inference profiles required.** On-demand 4.x Claude models reject the bare
  `anthropic.claude-*` model ID ("on-demand throughput isn't supported"). Must
  use the cross-region inference profile (`us.anthropic.claude-*`). See
  `lambdas/bedrock_client.py` `_MODEL_MAP`.
- **`anthropic_version: "bedrock-2023-05-31"`** in the body (vs `"2023-06-01"`
  on the direct API). Drop the top-level `model` field (→ `modelId` param).
- **Prompt caching** is GA on Bedrock for Claude via the same `cache_control`
  blocks — no `anthropic-beta` header needed.
- **No API key.** `api_key` params are now vestigial (kept for signature
  compatibility + rollback ease; the `life-platform/ai-keys` secret is
  retained but unused by the inference path).

### Code surface

- New primitive: `lambdas/bedrock_client.py` (`invoke()`, `resolve_model_id()`),
  added to the shared layer.
- Chokepoints rewritten: `ai_calls.call_anthropic`, `retry_utils.call_anthropic_api`,
  `retry_utils.call_anthropic_raw` (the latter still accepts a pre-built urllib
  Request for backward-compat — it extracts the body and forwards to Bedrock).
- Stragglers migrated (direct urllib callers): the 5 `coach_*` Lambdas,
  `site_api_ai_lambda` (/api/ask + /api/board_ask), `hypothesis_engine`,
  `challenge_generator`, `partner_email` (fallback path), `canary` (AI
  health-check now probes Bedrock).
- IAM: `_bedrock_statement()` in `role_policies.py`, wired into `_compute_base`
  (when `needs_ai_keys`), `_email_base` (all email roles), the 2 inline
  enrichment roles, `site_api_ai`, and `operational_canary`.
- Error handling: botocore `ClientError` codes (ThrottlingException,
  ModelTimeoutException, etc.) replace urllib HTTPError; graceful-degradation
  `[AI_UNAVAILABLE]` contract preserved.

### The gating step (why cutover is deferred)

Bedrock requires submitting the **Anthropic use-case details form** (AWS
console → Bedrock → Model access → Anthropic) before `InvokeModel` works.
There is no CLI/API for this in aws-cli 2.27. Until submitted +propagated
(~15 min), InvokeModel returns `ResourceNotFoundException: Model use case
details have not been submitted`. The code is committed but NOT deployed until
the form clears, so prod stays in its current state until then.

### Tradeoffs (honest)

- **Not cheaper per token** — Bedrock Claude pricing ≈ direct API. The win is
  consolidation + no-cliff + IAM auth, not unit cost.
- **Consumption discipline is separate** — Bedrock doesn't stop the platform
  auto-generating expensive content that goes unread. An engagement-gate
  (skip generation when briefs go unopened) is the actual money-saver and is
  tracked separately in BACKLOG.
- **urllib convention exception** — CLAUDE.md says "no external HTTP libraries";
  Bedrock needs `boto3 bedrock-runtime`. Sanctioned exception, noted in CLAUDE.md.

### Rollback

Revert the migration commit + redeploy. The `life-platform/ai-keys` secret is
retained, and the chokepoints' old urllib paths are in git history. (Rollback
only useful if Anthropic credits are also topped up.)

---

## ADR-063: $75 Monthly Budget Guardrails with Tiered AI Degradation

**Date:** 2026-05-29
**Status:** Implemented + enforcement enabled.

### Context

Post-Bedrock migration (ADR-062), AI spend is now on the AWS bill alongside infrastructure — no prepaid cliff, but also no built-in spend ceiling. The operator wants a hard **$75/month total cap** (all AWS, not just AI) with graceful degradation as spend climbs, auto-pause at the ceiling, and "protect daily brief longest" priority. Manual review of alerts is not enough; the platform should self-throttle.

### Decision

A two-component guardrail system:

1. **`cost_governor_lambda`** (hourly, in `operational_stack`) — projects month-end spend using `mtd + (non_ai_daily + ai_daily) × days_remaining`. `non_ai_daily` averaged across elapsed days; `ai_daily` averaged across days that actually had AI activity (not full month). Writes the resulting **tier 0–3** to SSM `/life-platform/budget-tier`.
2. **`lambdas/budget_guard.py`** (shared-layer module) — `current_tier()` reads SSM with 5-min cache (fail-open to 0). `allow(feature)` returns False once tier ≥ that feature's cutoff. `BudgetExceeded` raised by `bedrock_client.invoke()` at Tier 3 as a hard chokepoint failsafe.

Feature → tier cutoffs (priority ordering "protect daily brief longest"; amended by ADR-100 — readers degrade last):
- `coach_narrative`, `ensemble`: tier 1 (`chronicle` later raised to tier 2 to keep the Panel fed)
- `website_ai` (`/api/ask`, `/api/board_ask`): tier 3 (was 2 — see ADR-100)
- `daily_brief_ai`: tier 3 (last to degrade)

Plus a single `CfnBudget` `life-platform-monthly-75` in `core_stack` with 50/70/85/100% email alerts via SES.

### Key implementation facts

- **Early-month guard:** if `elapsed_days < 2`, computed tier is clamped to 0 — a tiny first-of-month sample can't false-escalate to Tier 3 and pause everything.
- **`OBSERVE_MODE`** env var on the governor — defaults to true (shadow); CDK overrides to false (currently enforcing). Lets the system run for a week observing-only before flipping.
- **Tier-3 hard gate at the chokepoint:** `bedrock_client.invoke()` raises `BudgetExceeded` at the top — stops bleed even if `budget_guard` was bypassed upstream.
- **Website graceful-pause:** `site_api_ai._ai_paused_response()` returns a friendly JSON at tier 2+ rather than 500ing.

### Tradeoffs

- **Projection is an estimate, not a meter.** Bedrock metrics lag ~15 min; price tables can change; the guardrail prioritizes "no surprise overages" over precision. Acceptable for a $75 ceiling on a solo platform.
- **Manual override is intentional.** `aws ssm put-parameter --name /life-platform/budget-tier --value 0 --overwrite` lets the operator reset for testing or after a cost-anomaly bug fix.
- **Doesn't address consumption value** — auto-generating content the user doesn't read still spends. An engagement-gate (skip generation when briefs go unopened) is tracked separately in BACKLOG.

### Rollback

Set `OBSERVE_MODE=true` on the governor (CDK env override) to make it observe-only. Tier-3 hard-gate in bedrock_client requires a code revert (intentional — it's the failsafe).

---

## ADR-064: Self-healing Remediation Agent as the Default Triage Loop

**Date:** 2026-05-29
**Status:** Phase 1 (shadow) validated; Phase 2 (auto-merge) enabled.

### Context

The operator was the middle-person for technical signals: alerts/QA/CI/DLQ emails → screenshot to Claude → Claude diagnoses + fixes → repeat. Most fixes this quarter (~80% by count) are highly self-healable: missing IAM grants, alarm miscalibration, `lambda_map` drift, freshness/QA source-list tweaks. A small stable set genuinely needs a human (OAuth re-auth, paid-tier decisions, AWS quota escalations).

### Decision

A scheduled GitHub Actions workflow (`.github/workflows/remediation-agent.yml`) runs Claude (Sonnet 4.6 on Bedrock) every morning ~07:45 PT, gathers the last 24h of signals deterministically (boto3 + `gh`, no LLM), and hands them to the agent with `docs/REMEDIATION_TAXONOMY.md` as the classification rubric. The agent buckets each signal into A/B/C/D and acts:

- **A — auto-fix-safe:** open a PR labeled `auto-fix-safe` (deterministic gate merges if all guards pass — see ADR-065).
- **B — fix-via-pr:** open a PR labeled `needs-review` (always human-merged).
- **C — needs-human:** no PR; specific action surfaced in the email.
- **D — stale/ignore:** collapsed in the email.

Plus *operational remediations* done directly via the read-only role (clearing a stale OK alarm, draining a confirmed-stale DLQ msg, re-running a gap-fill ingestion).

One curated email replaces the raw `[LP digest]` noise.

### Architecture

- **Auth:** AWS OIDC → `github-actions-remediation-role` (`deploy/setup_remediation_role.sh`; operator-run, not agent-run). Scope: `bedrock:InvokeModel` + `InvokeModelWithResponseStream` on `us.anthropic.claude-*`, `logs:FilterLogEvents/GetLogEvents`, `cloudwatch:DescribeAlarms/GetMetric*`, `dynamodb:GetItem/Query`, `lambda:GetFunctionConfiguration`, `sqs:ReceiveMessage` (DLQ only), `ssm:GetParameter` (life-platform/*), `kms:Decrypt`, `s3:GetObject` (platform bucket), `s3:PutObject` on `remediation-log/*`, `ses:SendEmail`. **NO deploy, IAM mutate, or lambda update.**
- **SDK:** `claude-agent-sdk` in the runner; `permission_mode="bypassPermissions"` (headless safety — `acceptEdits` hangs on Bash/gh in headless). Real blast-radius guard is the IAM role + GITHUB_TOKEN scope, not the SDK denylist (defense-in-depth only).
- **Mode kill-switch:** SSM `/life-platform/remediation-mode` = `off | shadow | auto`. Tier-3 budget also no-ops the run.
- **Triggers:** schedule (daily) + `repository_dispatch: urgent_alarm`. The urgent dispatcher Lambda (`life-platform-remediation-dispatcher`) was built + deployed 2026-05-29: subscribed to `life-platform-alerts` SNS, filters to a narrow URGENT_PATTERNS list (`canary`, `dlq-depth`, `site-api-error`, `budget-tier`, `bedrock-throttle`, `slo-`), dedupes per 30-min window via S3 marker, calls GitHub `repository_dispatch` using a fine-grained PAT stored in Secrets Manager `life-platform/github-dispatch-token`. Routine ingestion-source errors stay non-urgent (the daily sweep handles them).
- **Reporting:** SES email (reuses the `alert_digest_lambda` pattern). Audit log → `s3://matthew-life-platform/remediation-log/`.

### Why a long-running Claude agent rather than a rule-based bot

Rule-based systems can clear an alarm but can't recognize that a CI failure on commit X is *stale* because the bug was fixed in commit Y three hours later. Pattern-matching the "this is already fixed" class needs reading the diff + recent commits. Claude is good at this; rules are not.

### Tradeoffs

- **Cost:** ~$0.05/run × 30/month ≈ $1.50/mo. Negligible vs the toil eliminated.
- **Trust earned in phases:** shadow first (~1 week of correct calls before flipping to auto), narrow allowlist, every action a git commit/PR (revertable), audit log to S3.
- **Failure modes:** worst case in shadow = a PR you ignore; in auto, the gate's deterministic guards (ADR-065) prevent merging anything off-template.

### Rollback

`aws ssm put-parameter --name /life-platform/remediation-mode --value off` — immediate; the next scheduled run is a no-op.

---

## ADR-065: Auto-merge as a Deterministic Gate, Not the Agent

**Date:** 2026-05-29
**Status:** Implemented + enabled (mode=auto).

### Context

The remediation agent (ADR-064) can OPEN PRs but should not MERGE them. Letting an LLM decide which of its own PRs to merge to a solo prod platform is the wrong trust posture even with bypass permissions — small classifier errors compound. The desired property is: **the LLM proposes, deterministic code verifies and merges**.

### Decision

A separate post-agent workflow step (`remediation/automerge.py`) is the **only** thing that merges. It is intentionally NOT an LLM — every decision is a small set of boolean checks. The agent's `disallowed_tools` includes `Bash(gh pr merge *)` to enforce the separation in-band.

**Gate rules — ALL must hold to merge a PR:**

1. SSM `/life-platform/remediation-mode == auto` AND budget tier < 3.
2. Every changed file matches the ALLOWLIST (specific change templates, not "any small diff"):
   `cdk/stacks/role_policies.py`, `ci/lambda_map.json`, `cdk/stacks/monitoring_stack.py`, `lambdas/emails/freshness_checker_lambda.py`, `lambdas/operational/qa_smoke_lambda.py`, `tests/`.
3. No file matches the DENYLIST: substrings `bedrock_client`, `budget_guard`, `secret`, `credential`, `auth`, `deploy/`, `setup_github_oidc`, `setup_remediation_role`, `.github/workflows/`, `cdk/app.py`, `cdk/stacks/core_stack.py`, `remediation/`.
4. Diff ≤ 60 lines, no new non-test top-level files.
5. `flake8 --select=E9,F63,F7,F82` + the offline unit-test subset (`test_role_policies`, `test_lambda_handlers`, `test_layer_version_consistency`, `test_iam_secrets_consistency`, `test_shared_modules`) pass on the PR branch — **because GITHUB_TOKEN PRs don't trigger `ci-cd.yml`**, so CI-green can't be checked via `gh pr checks`. The gate runs the checks itself before merging; CI re-runs them on main after merge.
6. Per-day merge cap (3) not reached.

If a PR fails any check, it stays open with a `🤖 auto-merge gate held` comment and the reason. The agent's email surfaces held PRs distinctly from merged ones.

### What auto-merge does NOT do

- **Does not bypass the production deploy approval gate.** `ci-cd.yml`'s Deploy job has `environment: production` → manual approval still required. Auto-merge gets fixes into main + full CI validation, but the operator still clicks approve to deploy.
- **Does not auto-cdk-deploy infra.** CI hot-deploys Lambda CODE only. Merges touching `cdk/` are flagged "⚠️ needs `cdk deploy` to apply" in the email; infra deploys remain a deliberate operator action.

### Why this is safer than it sounds

- The ALLOWLIST is *specific files*, not patterns. A bug in another file area can't be auto-merged even if the agent wants to.
- Lint + unit-tests gate every merge, so a syntactically broken or consistency-violating "fix" can't reach main.
- Production deploy stays human-approved → no auto-deploy to prod without a click.
- Every gate decision logged to S3 with the diff (`remediation-log/automerge/YYYY/MM/DD/`), giving a complete audit trail.

### Rollback

`aws ssm put-parameter --name /life-platform/remediation-mode --value shadow` — the gate becomes a no-op next run; the agent still opens PRs but nothing merges automatically.

## ADR-066: Hevy Routine Write-Loop — One Path, Two Front Doors, Cron Disabled at Birth

**Date:** 2026-05-31
**Status:** Implemented (chat path + cron Lambda + adherence shipped; cron runtime-disabled, add-load runtime-disabled).
**Related:** `SPEC_HEVY_ROUTINE_WRITELOOP_2026_05_31.md`, `..._PREREQS.md`, `reviews/REVIEW_HEVY_ROUTINE_WRITELOOP_2026_05_31.md`.

### Context

Hevy is the strength-training source of truth (per ADR-060). The platform reads workouts via webhook + backfill. Closing the **program → perform → adapt** loop requires WRITING routines back to Hevy — informed by data Hevy lacks (recovery, volume landmarks, labs) — then reading what was actually performed. Boards approved "to outline" with strict phasing: ship the chat path first; cron only after Phase 1 usage clears Viktor's "meaningfully better than hand-built" bar; "add load" autoregulation only after Henning's N≥30 validation.

### Decision

Five tightly coupled subdecisions, all shipped together because splitting them would have caused multi-layer redeploys:

1. **One write path, two front doors.** Both the chat path (`manage_hevy_routine` MCP tool) and the cron (`hevy-routine-cron` Lambda) stop at a shared `RoutineSpec` IR and hand off to a single `hevy_compiler` module that owns the Hevy wire format. Isolation enforced by `tests/test_hevy_compiler_isolation.py` (AST scan: `exercise_template_id` only appears in the compiler/client). An API change touches one file.

2. **Subtract-only autoregulation by default.** Honors Henning's dissent. Red recovery / high ACWR may shrink the budget; green recovery may not enlarge it. `add_load_enabled` flag exists in `routine_generator.py` but is a no-op until the readiness signal validates per PREREQS §C. SSM `/life-platform/hevy/autoreg_add_load_enabled` ships `false`.

3. **Cron disabled by default at TWO layers.** The EventBridge rule is created with `enabled=False` AND SSM `/life-platform/hevy/cron_enabled` defaults to `false`. The Lambda no-ops on either gate, on Pause-Mode = `paused`, or on budget tier ≥ 3. Operator flips both ON after Phase 1 usage justifies it; no code redeploy needed.

4. **Write-key bundling decision: separate secret.** `life-platform/hevy-write` is its own Secrets Manager secret, read by exactly two Lambdas (`hevy-routine-cron` and `life-platform-mcp`). The pre-existing `life-platform/hevy` (read) is unchanged. Yael's bundling rule: same creds + same Lambda set only. A leaked write key cannot read; a leaked read key cannot write.

5. **One fat MCP tool, not five thin ones.** `manage_hevy_routine` dispatches on an `action` param (9 actions). Respects SPEC §9's "fewer fat tools" guidance. Acknowledged tension: the platform is already at 130 tools, above the SIMP-1 Phase 2 ≤80 target; this build does not address the underlying overshoot, but adds 1 fat tool rather than 5 thin ones to avoid widening the gap.

### Architecture details captured elsewhere

- IR schema, partition keys, ID-map: SCHEMA.md (ROUTINE# section).
- Generator algorithm and guardrails (MEV default, asymmetric autoreg, floor + re-entry variants, joint-friendly bias, portfolio guard, bounded outputs): PREREQS §B.
- API contract surprises (no DELETE, no webhooks, no documented rate limits, `updated_at`-only conflict guard): PREREQS §A.
- Interim Sports Med seat appointment: BOARDS.md + `config/board_of_directors.json:iris_tanaka_interim`.
- Operator procedures (provision secret, flip cron on, flip add-load on, archive routine, conflict playbook): RUNBOOK.md.

### Consequences

- Phase 1 chat-path authoring is usable day one via the MCP tool.
- Phase 2 adherence readback is wired (`action=adherence`) but only useful once routines exist.
- Phase 3 cron will fire weekly **only after** the operator flips both gates. The Lambda + IAM + DLQ are pre-provisioned so flip-on is configuration-only.
- "Add load" autoregulation requires a separate SSM flip (also operator-only) after the N≥30 validation completes; the generator code path is present but inert until then.
- Public-site copy: per Lena's dissent, this feature is **never** to be described as "autoregulated" while the readiness signal is unvalidated. Correct framing: "deterministic volume-landmark programming with red-day deload guard."

### Rollback

- Chat tool: remove `manage_hevy_routine` from `mcp/registry.py` + redeploy MCP.
- Cron: `aws events disable-rule --name hevy-routine-cron-weekly` (already disabled at birth); set SSM `cron_enabled=false` (already false). The Lambda + IAM can stay parked indefinitely with zero invocation cost.
- Secret: rotate `life-platform/hevy-write` via Secrets Manager; no Lambda redeploy needed (secret_cache TTL is 15 min).
- Interim Iris Tanaka: delete `iris_tanaka_interim` from `config/board_of_directors.json` and re-sync to S3. The `_sunset_trigger` field documents the procedure.

## ADR-067: Hevy Routine Title Convention — "<Phase> - <Type> - <N> - <Y>"

**Date:** 2026-05-31
**Status:** Implemented (code shipped; layer rebuild + cdk deploy pending — see RUNBOOK §"Hevy Routine Title Convention — Deploy Steps").
**Related:** ADR-066 (Hevy routine write-loop), `lambdas/routine_title.py`, `config/training_phases.json`.

### Context

ADR-066 shipped the write-loop with a placeholder title ("`<archetype> — <date>`") and the IR's multi-line rationale dumped into Hevy's notes field. Both surfaces are wrong for the actual user experience in the Hevy app:

- The routine list in Hevy shows the title as a one-line label. The placeholder doesn't carry the information that's useful in a glance — *what phase am I in? how many of this type? how deep into the journey?*
- The notes field is shown as a free-form description. A multi-line rationale dump is noisy and reads as machine output.

### Decision

Adopt a single title convention used by every variant except re-entry:

```
<Phase> - <Type> - <N> - <Y>
```

- **Phase** — current training-phase name from `config/training_phases.json`. Phases ship as `["Foundation", "Build", "Forge", "Sustain"]`; rename as the program matures. `current` is manually advanced — no auto/milestone-driven transitions. Phase boundary date lives in `current_started` and is the inclusive lower bound for N.
- **Type** — `ir.archetype` title-cased (Upper / Lower / Full / Aerobic / Mobility). Push/Pull/Legs would require an archetype refactor; not in scope.
- **N** — count of **pushed** routines of this archetype within the current phase + 1. 1-based; resets at phase boundary.
- **Y** — total **performed** Hevy workouts to date + 1. Computed at generation time from a DDB COUNT query against `USER#matthew#SOURCE#hevy` `DATE#`.

Examples:
- `Foundation - Upper - 3 - 47`
- `Build - Lower - 1 - 51`

Re-entry variant overrides the convention entirely:

```
Welcome back · <Type>
```

No counters surface in the title. Y and N still flow through the IR for analytics — they're kept out of the title to honor the no-guilt-debt principle (Coach Maya / Dr. Reeves in REVIEW §5). "You missed N" framing is unkind and unhelpful.

A one-line **WHY note** is projected into Hevy's notes field, replacing the rationale dump. Variants:

- `re_entry`  → "Easing back in after a gap. Take it gently today."
- `floor`     → "Floor session — minimum effective dose for a low-energy day."
- red recovery → "Recovery red. Deloading today; protect joints."
- portfolio guard active → "Aerobic base low. Holding strength flat to protect Zone 2."
- yellow recovery → "Readiness yellow. Holding steady."
- green recovery → "Readiness green. Programmed against weekly volume targets."

### Why Y is performed-based but N is pushed-based

The spec is explicit: **Y derives from performed-workout history so it's honest and self-correcting** — skipping a planned session never inflates Y. A naive ever-incrementing counter would drift away from physical reality every time a session is missed; that drift is corrosive over months. The cumulative tally is the most prominent "deep into the journey" signal, so it has to be honest.

**N is pushed-based for sequencing simplicity.** When Matthew looks at his Hevy routine list, he sees the sequence of routines we've sent him; numbering them in that order matches the mental model of "I just pushed Push-3." A performance-based N would require cross-referencing each routine to a Hevy workout on the same target_date — possible (the linkage is in DDB) but adds two more DDB queries per commit and a subtler semantic ("this routine is N=3 but you've only performed 1 push so far"). Phase 1 prefers the simpler interpretation; Phase 2 can revisit if the drift turns out to matter.

### Open call: per-phase vs all-time-per-type N

The default ships per-phase (N resets when `current_started` moves). The alternative is all-time-per-type (Push #47 forever). Flagged in the handover; flipping is a one-helper change in `routine_title.count_phase_archetype_routines` (drop the `phase_start` filter). Matthew's call.

### Phase advancement

Manual only. Update `config/training_phases.json`:

```json
{
  "phases": ["Foundation", "Build", "Forge", "Sustain"],
  "current": "Build",
  "current_started": "2026-09-01"
}
```

Then `aws s3 cp config/training_phases.json s3://matthew-life-platform/config/`. The next commit picks up the new phase from S3 (15-min secret/config TTL on warm containers; cold start is instant). N resets to 1 for each archetype at the boundary.

### Consequences

- The existing routine `75e4268c-...` (already committed under the old title) will get retitled at next `commit` (which is a PUT). No data loss; the IR keeps its full rationale and prior title in the version history.
- Hevy app routine-list scanning becomes meaningful: at a glance, phase + type + sequence + journey tally.
- The chat path and the cron path use the same title convention via the shared `routine_title.build_title_context` helper. Two routines for the same target_date generated on the same day will share the same N and Y — appropriate, since they reflect "where you are right now" not "where this specific routine fits in the pushed sequence."

### Rollback

Pass `title_context=None` (and omit `why_note`) at every caller site. Compiler falls back to `ir.title` + `ir.notes`, restoring the ADR-066 placeholder behavior. No deploy needed beyond reverting the two caller edits in `mcp/tools_hevy_routine.py` and `lambdas/operational/hevy_routine_cron_lambda.py`.

### ADR-067 Amendment (2026-05-31): N is all-time-per-type since EXPERIMENT_START_DATE

> **⚠️ Superseded by ADR-088 (2026-06-16).** N is per-phase again (resets at `current_started`) and is now derived from PERFORMED workouts, not pushed routines; Y anchors to a new `reset_epoch_date` rather than `EXPERIMENT_START_DATE`. The amendment below is retained for history.

The original ADR-067 shipped per-phase N. After a same-day review, Matthew flipped to **all-time-per-type-since-experiment-start**:

- N counts pushed routines of this archetype since `EXPERIMENT_START_DATE` (set to 2026-06-01 by the same change).
- Phase boundaries no longer reset N. Phase becomes a decorative narrative marker in the title — "you are in Build phase" — but the Push sequence continues across phase transitions.
- Y counts performed Hevy workouts since `EXPERIMENT_START_DATE`. Pre-experiment Hevy workouts stay in DDB (preserved by the restart-pipeline's phase-tag stage) but are excluded from these counters so they reflect *this experiment's* journey, not lifetime.

Reasoning: the experiment is the anchor that gives N and Y their meaning. Per-phase resets fragment the arc and create same-name collisions (`Foundation - Push - 3` and `Build - Push - 3`); all-time-since-experiment keeps the sequence intact and self-correcting. Y's honesty argument (don't inflate on skipped sessions) carries over.

`count_phase_archetype_routines` → renamed `count_experiment_archetype_routines`. `count_total_performed_workouts` → renamed `count_performed_workouts_since(start_date)` with the experiment date pinned in `build_title_context`. Tests updated accordingly. Layer v69 → v70.

## ADR-068: Per-Exercise Notes — Deterministic History Cues, LLM Never Computes

**Date:** 2026-05-31
**Status:** Implemented (code shipped; layer rebuild + cdk deploy pending — see RUNBOOK §"Per-Exercise Notes — Deploy Steps").
**Related:** ADR-066 (write-loop), ADR-067 (title + WHY-note), `lambdas/exercise_history.py`, `config/training_week.json:exercise_notes_mode`.

### Context

The Hevy routine surface has three text fields per push: routine title (ADR-067), routine notes (ADR-067 WHY-line), and per-exercise notes. ADR-067 covered the first two. This ADR covers the third — one short line per exercise, set at generation time, visible mid-set on the phone.

Hevy's routine create/update API accepts a `notes (string, nullable)` field on each exercise. Verified live 2026-05-31 by PUT-ing a routine with an `exercises[].notes` field and reading it back round-tripped intact.

### Decision

**Default note shape** (one_best_line mode, default): `Last: 60kg 8/8/7 (24 May)` — the top-set weight from the last performed session, the per-set reps preserved (so drop-off is visible), and a friendly short date.

Rendering is **pure Python** from real DDB records. No LLM call at the rendering step.

Two cue sources are wired in `pick_note`:
- **history_cue** — deterministic, always computed from `USER#matthew#SOURCE#hevy` records via `exercise_history.render_history_cue`.
- **ai_comment** — optional, scoped to one short coaching line. Wiring exists; **no module emits one today.** Reserved for a future coach-layer output. When that layer ships, `pick_note` will prefer it over the history cue (one_best_line) or show both (show_both).

**Config flag:** `training_week.json:exercise_notes_mode` ∈ `one_best_line` | `show_both` | `off`. Default `one_best_line`. Easy to flip per Matthew's preference.

**Cutoffs for honesty (Henning standard):**
- 0 prior sessions of this movement → empty note (no fluff).
- 1+ prior sessions → factual history cue.
- (Future: progression cues will require N ≥ a configured floor; not in scope here.)

### Anti-hallucination guard

Two-layer enforcement:

1. **Structural** — no LLM in the rendering path. The renderer reads facts and formats. No model means no invented numbers.
2. **Test** — `tests/test_exercise_history.py::test_anti_hallucination_render_quotes_only_source_numbers` regex-extracts every numeric token from the rendered cue and asserts each one traces back to the source `history_facts` dict (weight, reps, date day). A `pick_note` companion test enforces the same on the combiner output.

When a future AI comment is wired, the same anti-hallucination test will run against its output — the LLM may only phrase facts that the Python-computed facts dict already contains. **The LLM never does math.** This is the platform invariant; the test is the gate.

### Numbers vs prescribed load — strict separation

Per spec: a note may *report* "Last: 60kg 8/8/7" or (in future) *suggest* "Try 60kg ×8/8/8 today," but the **prescribed** sets/weights in the routine's exercise blocks are still bound by `autoreg_add_load_enabled=false` (subtract-only). The note is advisory text on a separate field; it does NOT feed back into the generator's budget math. Code path: `_build_exercise_note` reads history and renders text; the generator's `_muscle_budget` is untouched and still respects all autoreg gates.

### Data + performance

`exercise_history.load_recent_history(lookback_days=180)` performs **one batched DDB Query** per generation over `USER#matthew#SOURCE#hevy` with `sk >= DATE#<today-180>`, paginates via `LastEvaluatedKey`, and builds an in-memory index keyed by Hevy `template_id`. Subsequent per-exercise lookups are O(1) dict access. A routine with 8 exercises makes 1 DDB call total, not 8.

Legacy daily-aggregate records (no `source_workout_id` field) are intentionally skipped — pre-write-loop history stays in DDB but does not surface into notes. Post-reset, the SOURCE#hevy partition is the canonical history.

### Out of scope (explicitly not built)

- AI-trainer comment generation (coach-layer hook documented; no emitter today).
- Progression cues — bound to future N≥validation-floor decision.
- Cross-routine PR detection / streak surfacing.
- Mood / journal / sensitive content in notes. **Training only.**
- Changes to cron, autoreg, or the subtract-only gate.

### Rollback

`training_week.json:exercise_notes_mode = "off"` and re-sync to S3. The generator skips the DDB load entirely (verified by `test_exercise_notes_off_mode_yields_empty_notes`), and notes ship as empty strings. No code redeploy needed.

## ADR-069: Custom Routine Authoring — `draft_custom` Escape Hatch for Hand-Designed Sessions

**Date:** 2026-05-31
**Status:** Implemented (chat path only; cron unchanged).
**Related:** ADR-066 (write-loop), ADR-067 (title), ADR-068 (per-exercise notes), `mcp/tools_hevy_routine.py`, `config/movement_catalog.json`, `lambdas/hevy_template_cache.py`.

### Context

ADR-066 shipped the write-loop with a single authoring front door: `action=draft`, which runs the deterministic volume-landmark programmer (`routine_generator.generate_routines`). That path builds its *own* routine from recovery/volume/ACWR state and, by design (ADR-068, "LLM never computes"), never accepts an exercise list. In practice this meant a hand-designed session — "barbell bench ramping to 185×5, incline 70s, a lateral/reverse-pec/pushdown tri-set" — could **not** be pushed from chat at all. The only channels were the browser (Claude-in-Chrome) or manual entry, both of which failed or stalled in real use. Three walls blocked it: (1) no action accepted an explicit exercise/set/weight list; (2) several common movements (barbell bench, DB shoulder press, reverse pec deck) weren't in the 18-movement catalog; (3) the generator's loads are subtract-only and `add_load_enabled=False`, so it structurally can't emit user-chosen heavy loads.

### Decision

1. **New action `draft_custom`** on `manage_hevy_routine`. It accepts an explicit `exercises` list (`movement_key` or human `title`/`name`, `sets[{weight_lbs|weight_kg, reps|rep_range, type, count}]`, `rest_seconds`, `superset_id`, per-exercise `notes`), converts lbs→kg, expands a set's `count`, and persists a normal `RoutineSpec` IR with `source_action="draft_custom"`. Because it stops at the same IR, the existing `dry_run → commit` chain pushes it to Hevy unchanged — one write path is preserved (ADR-066 §1 intact). Loads are taken **verbatim**; the platform does not compute them. ADR-068's "LLM never computes" governs the *deterministic* path only — `draft_custom` is explicitly the user authoring their own session, not the system inventing loads.

2. **Resolve-by-title fallback for unmapped movements.** New catalog movements ship their exact Hevy *title* and **no** `hevy_template_id_hint`. `_make_resolver()` (in the MCP tool) tries `resolve_movement` first, then falls back to `reconcile_custom`, which searches the live Hevy template list by title and caches the real id. Rationale: a hand-transcribed 8-char template id that's wrong would **silently mis-map** to the wrong exercise; a title miss instead fails **loudly** (`MovementUnmappable`) and is fixed with a one-line title correction. Loud-wrong beats silent-wrong.

3. **Catalog +3 movements:** `barbell_bench_press`, `db_shoulder_press`, `reverse_pec_deck` — title-only, resolved per (2).

4. **No silent caps.** `draft_custom` does not hard-assert the session ceiling (the user authored it deliberately); it returns a `warnings[]` advisory when `total_sets` exceeds `session_set_ceiling` rather than truncating.

### Consequences

- A hand-designed session pushes from chat with no browser: `draft_custom → dry_run → commit`.
- Titles still follow ADR-067 at commit (archetype drives the `<Phase> - <Type> - <N> - <Y>` form); the WHY-note surfaces the user's own first note line (new `format_why_note` branch) instead of a generator-flavored rationale.
- The deterministic `draft` path, cron, autoreg, and the subtract-only gate are **untouched**.
- Public-site framing unchanged: still "deterministic volume-landmark programming," and a custom session is plainly user-authored, never described as autoregulated.

### Rollback

Remove `"draft_custom"` from `_VALID_ACTIONS`/`_DISPATCH` in `mcp/tools_hevy_routine.py` and redeploy MCP; the catalog additions and the resolve-by-title fallback are inert without it (the generator never selects title-only movements because they lack a `default_rep_range`-driven selection advantage — and are harmless if it does). The `format_why_note` custom branch is a no-op for non-custom IRs.

### ADR-069 Amendment (2026-06-01): Full Hevy template index — author any exercise by title

The initial cut required every authorable movement to be a curated `movement_catalog.json` entry, so anything outside the ~26-movement pool (circuits, varied cardio, accessories) threw `MOVEMENT_UNMAPPABLE` until someone hand-added it. Closing that gap properly without polluting the generator's curated pool:

- **`config/hevy_template_index.json`** — the full Hevy template list (built-in + the account's custom exercises) pulled via `hevy_write_client.list_templates`, normalized to `title → {id}`. **Distinct from `movement_catalog.json`** (which stays the generator's small curated pool with selection metadata). Rebuild any time by re-pulling the live list.
- **`draft_custom` resolution order** (`_resolve_movement_key`, conservative — exact before fuzzy, curated before index): curated key → curated exact-title → index exact normalized-title → **live Hevy lookup (self-heal for templates newer than the index)** → loose contains within the curated catalog only. An index/live hit returns a synthetic `movement_key="tmpl:<id>"`; `_make_resolver` short-circuits those straight to the id (no catalog/cache needed). A true miss fails **loudly** with close-title suggestions — never a silent fuzzy mis-map.
- **Result:** any built-in or custom Hevy exercise is authorable by its exact title with zero catalog edits; circuits are just shared `superset_id`s, already supported. The deterministic generator is untouched (it never sees `tmpl:` keys or cardio movements — `primary_muscle:"cardio"` keeps them out of its selection).

Config-only + MCP code; no layer change. Rollback: delete the index file (resolution falls back to curated catalog + live lookup) or revert the resolver edits.

### ADR-069 Amendment (2026-06-01): Auto-create missing exercises (no-stuck authoring)

Even with the full index, an exercise Hevy simply doesn't have (e.g. "Landmine Snatch") would dead-end the draft. `draft_custom` now **creates** the missing exercise so the routine isn't blocked:

- **Default `create_missing: true`.** When a title resolves to nothing (curated → index → live) and the caller gave a **human title** (never a bare `movement_key` — that's treated as a likely typo), the exercise is created via `POST /v1/exercise_templates` and then used. Created exercises are reported under `created_exercises` (the visibility net against typos); `create_missing: false` reverts to loud-fail-with-suggestions.
- **Verified Hevy create contract (2026-06-01):** body is `{"exercise": {title, muscle_group, exercise_type, equipment_category}}` — create-side field names + the `exercise_type` enum DIFFER from the GET-side object, and the response is a bare id string. So we create, then **reconcile the canonical id by title** (handles the bare-string / PREREQS integer-id quirk + eventual consistency). Metadata comes from optional per-exercise overrides (`muscle_group`/`exercise_type`/`equipment_category`) or is inferred from the set shape + title keywords.
- **Idempotent** across drafts (resolve-first → already-created exercises are found, not duplicated) and within a draft (created titles memoized). A failed create lands in `creation_errors` and that one exercise is skipped — the rest still drafts (never stuck).

MCP code only; no layer/index change required (re-pull the index later to fold new exercises in).

---

**Verified:** 2026-05-31 (ADR-069 — custom authoring escape hatch) · amended 2026-06-01 (full Hevy template index; auto-create missing exercises)

## ADR-070: Vacation Fund Tracker — $1 per workout mile, additive across sources

**Date:** 2026-06-01
**Status:** Implemented (MCP + site-api + daily brief; live on layer v71).
**Related:** `lambdas/vacation_fund.py`, `config/vacation_fund.json`, `mcp/tools_vacation.py`, `lambdas/web/site_api_lambda.py` (`/api/vacation_fund`), `lambdas/emails/daily_brief_lambda.py` + `lambdas/html_builder.py`, `handovers/HANDOVER_2026-06-01_VacationFund.md`.

### Context

A motivation game: every mile of workout distance since `EXPERIMENT_START_DATE` (2026-06-01) earns $1 toward a shared vacation fund. Needed to total *Matthew's* miles from existing data, convert to dollars, and surface it easily.

### Decision

1. **One shared compute in the layer, three thin consumers.** `lambdas/vacation_fund.py:compute_vacation_fund(start?, end?)` owns the miles→USD math; the MCP tool (`get_vacation_fund`), the site-api route (`/api/vacation_fund`), and the daily-brief banner all call it. No new compute Lambda/schedule — on-demand (data is small, grows slowly).

2. **Strava base + additive opt-in Hevy/MacroFactor (user's choice).** Strava daily `total_distance_miles` is the base (Zwift `VirtualRide`s, Garmin auto-syncs, and outdoor walks/runs all already flow into Strava). Hevy (`exercises[].sets[].distance_m`÷1609.34) and MacroFactor (`distance_miles` or `distance_yards`÷1760) are **added on top** because Matthew logs some cardio only there. **Garmin is never counted separately** (double-count). Overlap (a ride in both Strava and Hevy) is accepted and made visible via a per-source breakdown + a warning; `manual_adjustment_usd` corrects it.

3. **Config in S3, not code.** `config/vacation_fund.json`: `rate_per_mile` (1.0), `start_date` (null→genesis), `included_sport_types` ("all" or a Strava sport_type list), `extra_sources` (["hevy","macrofactor_export"]), `manual_adjustment_usd`. Loaded local-first (tests) then S3; missing/partial config falls back to defaults and never errors.

4. **Read-only.** Every consumer only reads DDB/S3; the tool/endpoint never write. Genesis day returns zeros + a clear warning rather than erroring.

### Consequences

- Layer **v70 → v71** (`vacation_fund.py` added to `build_layer.sh` + `ci/lambda_map.json`; `html_builder.py` edited for the banner). Fleet repointed to v71.
- Activity-type filtering, when set, restricts Strava sport_types and skips Hevy/MacroFactor (they have no sport_type to filter on) — surfaced in `warnings`.
- The girlfriend's miles are out of scope for auto-counting (not in Matthew's Strava); can be folded in as a `manual_adjustment_usd` lump sum.
- Optional future: same-day Strava↔Hevy distance-match dedup (not built — additive by design).

### Rollback

Remove `get_vacation_fund` from `mcp/registry.py` + redeploy MCP; remove the `/api/vacation_fund` route + the brief's `compute_vacation_fund` call. `vacation_fund.py` and the config become inert. No data migration (read-only).

---

**Verified:** 2026-06-01 (ADR-070 — vacation fund tracker)

---

## ADR-071: v4 "The Measured Life" front-end — one engine, three doors

**Date:** 2026-06-01 (rebuilt + cut over), refined 2026-06-02
**Status:** Live on `averagejoematt.com`.
**Related:** `docs/CLAUDE_CODE_PROMPT_V4_PASTE_READY.md` + the four source-of-truth design docs; `site/index.html`, `site/now/`, `site/story/`, `site/evidence/`, `site/subscribe/`; `site/assets/js/{story,cockpit,evidence,dispatches,charts}.js`; `scripts/v4_build_evidence.py`, `scripts/v4_build_dispatches.py`, `scripts/v4_build_rss.py`, `scripts/v4_migration_inventory.py`, `scripts/v4_vendor_fonts.py`; CloudFront `v4-redirects` function; `site/legacy/`; `handovers/HANDOVER_LATEST.md`.

### Context

The pre-v4 site was a sprawl of ~40 standalone pages. Goal: a world-class, intuitive, repeat-visitor experience that keeps all the depth but is easy to navigate — over the **unchanged** engine (read existing `/api/*` contracts only; no engine/schema/Lambda changes).

### Decision

1. **Three doors over one engine.** **Cockpit** (`/now/`, today's live data — noindex, the daily tool), **Story** (`/story/`, the narrative/writing hub: chronicle · AI lab notes · journal · timeline · about — a master-detail reader), **Evidence** (`/evidence/`, the browsable data archive — horizontal group tabs → topic tiles → data-bound readout). The home landing (`/`) is a separate cinematic scroll; the brand/logo is the only link to it.
2. **Old site preserved verbatim at `/legacy`** — private rollback, **no UI links**; old URLs 301 to their v4 home via the CloudFront `v4-redirects` function generated from `redirects.map` (`v4_migration_inventory.py`, 0 unmapped enforced).
3. **No framework, no deps.** Static HTML + `tokens.css` design system (OKLCH, Fraunces/Instrument Sans/IBM Plex Mono, ember accent) + vanilla-JS ES modules. Self-hosted fonts (CSP `font-src 'self'`). Charts are inline SVG (`charts.js`). Weights shown dual-unit (kg · lb).
4. **Naming:** "the story" is the writing hub at `/story/` (renamed from the short-lived `/dispatches/`, which 301s); the home page is a separate landing, not "the story."

### Outcome

Live; the 2026-06-02 QA sweep verified all 36 routes render with 0 HTTP/JS/CSP errors and 0 mobile overflow (320–414px). `/subscribe` re-skinned to v4 (2026-06-02). Engine untouched throughout.

---

## ADR-072: Experiment restart zeroes the accountability ledger

**Date:** 2026-06-02
**Status:** Implemented — `deploy/restart_ledger_reset.py`, wired into `deploy/restart_pipeline.py`.
**Related:** `lambdas/web/site_api_data.py::handle_ledger`, `restart_intelligence_wipe`.

### Context

The site's `/api/ledger` reads `TOTALS#current` **directly** and does not honour the phase/tombstone filter the rest of the restart pipeline relies on. So re-anchoring the experiment left pre-genesis ledger dollars still showing on the site.

### Decision

New idempotent `restart_ledger_reset.py` deletes every `LEDGER#` transaction under `pk=USER#matthew#SOURCE#ledger` and writes a zeroed `TOTALS#current`. Dry-run by default, `--apply` to execute. Wired as a step **after** `restart_intelligence_wipe` in `restart_pipeline.py` so every future restart zeroes the ledger automatically.

### Outcome

Ran `--apply` (5 pre-genesis txns cleared, `/api/ledger` verified `$0`). Future re-anchors are clean with no manual step.

---

## ADR-073: Site API returns shaped-empty 200 on sparse data (not 503)

**Date:** 2026-06-02
**Status:** Code committed; deploys via the CI/CD production-approval gate (full `web/` package).
**Related:** `lambdas/web/site_api_observatory.py`, `lambdas/web/site_api_data.py`.

### Context

On genesis week / before compute runs, several read-only endpoints returned `503` (`/api/nutrition_overview`, `/api/correlations`, and code paths in `habit_streaks`/`supplements`/`genome_risks`). The v4 front-end degrades gracefully, but the contract was dishonest and the browser console showed 503s.

### Decision

Genesis-sensitive read handlers return a **200 with the success contract's keys at empty/null values** + a short cache, instead of a 503. Read-only correctness preserved (no writes). The pattern is restart-safe — endpoints behave honestly the first week of any re-anchor.

### Outcome

Confirmed live 503s (nutrition_overview, correlations) fixed in code; the rest audited to match. Cleaner console, honest empty states.

---

**Verified:** 2026-06-02 (ADR-071/072/073 — v4 front-end + restart ledger reset + graceful empty-states)

---

## ADR-074: Garmin direct-API ingestion retired (paused) — vendor anti-automation

**Date:** 2026-06-03 (cron disabled 2026-07-04, #497)
**Status:** Paused — commented out of `freshness_checker_lambda.py` SOURCES + OAUTH_SECRETS + `qa_smoke_lambda.py` (shown ⏸). **2026-07-04 (#497/C-2): the EventBridge cron is now DISABLED too** — it had kept firing 4×/day into the throttle (~73 consecutive failures) against this pause, and each hit only prolongs the lockout. The function stays deployed for manual invokes; the INGEST_HEALTH sentinel keeps tracking. Revive = manual re-auth (`setup/setup_garmin_browser_auth.py` from a residential IP) + restore `schedule=` in `cdk/stacks/ingestion_stack.py`.
**Related:** `lambdas/ingestion/garmin_lambda.py` (garth + 429 circuit-breaker), `setup/setup_garmin_browser_auth.py`.

### Context

Garmin ingestion broke on a recurring cycle (re-auth → works briefly → 429 → re-auth). Root cause, finally measured: Garmin's **2026 anti-automation crackdown 429-rate-limits the OAuth2 refresh-exchange endpoint for non-browser/datacenter clients** — **374 throttles vs 2 successes over 14 days**, last data 2026-05-29. The OAuth1 token stays valid, but Garmin won't let a Lambda exchange it for a fresh OAuth2 from an AWS IP, so each browser re-auth only buys ~1 run. The `garmin_lambda.py` code is correct (persists tokens, lazy refresh, 3h 429 breaker) — it simply can't win an IP-reputation block.

### Decision

**Leave Garmin paused.** No clean, zero-touch, low-cost, fully-background fix exists: (a) a library swap can't help — all hit the same endpoint from the same IP (`python-garminconnect` is built on `garth`); (b) the official Garmin Health API is B2B/approval-gated (low odds for a personal/N=1 platform); (c) a wearable aggregator (**Terra** — free tier, official Garmin partnership, webhook push) works and is hands-off but routes health data through a third party (privacy trade-off); (d) a residential proxy is paid + fragile (continued cat-and-mouse); (e) a residential host (laptop/Pi) means more tech to babysit. Owner opted to pause, not pursue any of these now. Strava (API 402) and MacroFactor (torn down) were already paused the same way; `apple_health` covers daily steps/activity.

### Consequences

Garmin metrics unique to it (body battery, stress, SpO2, respiration, floors, RHR, calorie split) stop updating; Whoop + Eight Sleep + Apple Health cover the rest. The freshness/QA noise stops (shown ⏸ paused, never failing). Revive = uncomment + re-auth from a residential IP, or onboard Terra/official API.

---

## ADR-075: Budget guard early-month guard + AI cost trim (remediation agent)

**Date:** 2026-06-03
**Status:** Implemented — `cost_governor_lambda.py` deployed; `.github/workflows/remediation-agent.yml` live from `main`.
**Related:** ADR-063 ($75 ceiling / budget guard).

### Context

Two budget alerts. (1) A **day-2 false tier-3 AI cutoff**: `cost_governor` projected month-end as `mtd / elapsed_days × days` (`$15.56/2 → $233`), but fixed monthly charges front-load onto day 1, so the run-rate is wildly overstated early; the existing `elapsed_days < 2.0` guard had just expired in UTC. (2) AWS's native forecast crossed $75 — driven by ~$3/day of **Sonnet**, almost all of it the **remediation agent** (a *daily agentic* Claude Code run finding nothing most days).

### Decision

1. **Early-month guard:** for the first `EARLY_MONTH_DAYS=5`, escalate the AI tier on **actual mtd vs ceiling** (the true guardrail), not the noisy projection. A genuine runaway still trips (it shows in actual spend); front-loaded fixed costs no longer cause a false AI cutoff.
2. **Remediation agent cost:** cadence daily → **Mon/Wed/Fri**, model Sonnet → **Haiku-primary** (urgent alarms still trigger on-demand via `repository_dispatch`; the auto-merge gate is deterministic so safety is model-independent; Sonnet stays available for escalation). ~$45–70/mo saved. Compute jobs already run Haiku; the daily brief stays Sonnet (flagship, single small call — caching's 5-min TTL doesn't help once-daily jobs).

### Consequences

No more false early-month AI pauses; month-end forecast drops back under $75 without degrading the daily brief. The budget guard still backstops a real overage.

---

## ADR-076: Visual + AI-vision UI test harness

**Date:** 2026-06-05
**Status:** Implemented — `tests/visual_qa.py` + `tests/visual_ai_qa.py`; CI `visual-qa` job ADVISORY (not yet gating).
**Related:** ADR-062 (Bedrock chokepoint), ADR-071 (v4 front-end), ADR-064/065 (shadow→auto ramp pattern).

### Context

The v4 site is **data-driven** — its inline-SVG charts/values legitimately change every day — so naive pixel-diff visual regression is the wrong tool (it false-positives daily). The existing `tests/visual_qa.py` was a real Playwright harness but **v4-stale** (old v3 routes, Chart.js-canvas checks, a vestigial `cf-auth` gate). HTTP smoke tests and DOM checks can't answer "does the page actually *look* right" — and can't catch interaction-only failures.

### Decision

A two-layer, self-hosted harness (no paid SaaS, no "hyperframes" — that's an HTML→video tool, not testing):
1. **Deterministic (Playwright):** v4 routes, inline-SVG geometry checks, the cockpit pillar-disclosure **interaction**, responsive overflow, per-chart element crops; actionable failed-request capture (broken `/api/` calls fail with URL; resource hiccups warn).
2. **Semantic (Claude vision):** each screenshot → `bedrock_client.invoke()` (Haiku, ~$0.001/img) → a structured verdict (`renders_ok`/`severity`/`issues`). Judges *render correctness*, not pixel identity — so it passes honest sparse-data states and flags real breakage (blank/garbled charts, raw `undefined`/`NaN`, clipped/overlapping text). Degrades cleanly (Bedrock error / budget tier-3 → AI-QA skipped; deterministic checks stand).
3. **CI:** a post-deploy `visual-qa` job, introduced **advisory** (`continue-on-error`) per the ADR-064/065 shadow→auto ramp — tune for ~1 week, then gate on high-severity (deterministic OR AI). AI-QA needs `bedrock:InvokeModel` on `github-actions-deploy-role` (staged in `setup_github_oidc.sh`, operator-applied). Rollback's `needs` excludes `visual-qa` so advisory failures never roll back.

### Consequences

The two layers are complementary and earned their keep immediately — the interaction layer caught a real `/api/coach_analysis` 400 (4 of 7 cockpit pillars) that no HTTP smoke test or screenshot could see (the page still *looked* fine via its fallback). Cost is pennies per run. Pixel-diff is intentionally NOT used (data-driven). Trade-off: AI verdicts can hallucinate, so the gate fires only on high-severity + the deterministic signal, never on AI med/low.

---

**Verified:** 2026-06-05 (ADR-076 — visual + AI-vision test harness; advisory in CI)

---

## ADR-077: Phase taxonomy — one classification for experiment-restart semantics

**Date:** 2026-06-07
**Status:** In progress — `lambdas/phase_taxonomy.py` registry + `tests/test_phase_taxonomy.py` (180 live families) + `docs/PHASE_TAXONOMY.md` landed; restart-script rewiring, write-time stamping, cycle stamping, and the 7 mechanism fixes follow under the same ADR.
**Related:** ADR-058 (experiment restart + phase filter), ADR-072 (ledger reset), the 2026-06-07 read-side phase-filter sweep (PR #23).

### Context

Restart semantics were enforced by **three mechanisms with no shared definition**: the tagger (`restart_phase_tag.py`, scans only `USER#…SOURCE#`), the wipe (`restart_intelligence_wipe.py`, its own hand-rolled partition lists), and ~250 read paths. A full-table census (27,083 items, 180 record families) plus a three-lens expert review (physiologist, behavioral scientist, data/product) found the divergence was causing real harm: **279 pre-genesis coach-conversation threads leaking into live prompts** (writer on a bare `USER#matthew` pk the tagger can't see; the wipe aimed at a phantom partition name); public endpoints serving 100% pilot data; the clinical labs page one careless wrap from emptying; durable memories tagged for hiding; `ENSEMBLE#digest` missed by both tools; a `phase="plateau"` attribute collision on `NARRATIVE#arc`.

### Decision

A single registry (`phase_taxonomy.py`) classifies every record type into four classes — **cross_phase** (clinical/identity/durable: never touch), **raw_timeseries** (facts kept; current views genesis-anchored), **experiment_scoped** (tagged + wiped + cycle-stamped at restart; phase-filtered on read), **system_state** (phase machinery ignores). Both restart tools and the read paths derive from it. Owner invariants: nothing is ever deleted; restart re-anchors progress to genesis; clinical truths are date-independent. Panel-corrected reclassifications (supplements→cross_phase for med safety; measurements/day_grade→raw_timeseries; `chronicling`→cross_phase; email_log→system_state; ledger keeps a durable LIFETIME aggregate; vice-streak longest-ever promoted out of the wiped partition). New **cycle / reset-generation stamping** (`cycle=N` at archive + write time) makes the archive a navigable sequence of past runs. Curated **chronicle carry-forward** keeps selected Wednesday issues across a restart, re-dated to genesis−N. Full rationale + per-record table: `docs/PHASE_TAXONOMY.md`.

### Consequences

The taxonomy is mechanically enforced and test-covered against every live family, so a new source can't silently default to the wrong behavior. The seven divergence bugs are fixed at the root (shared registry) rather than patched per-symptom. Restart becomes auditable: a dry-run reports exactly what each run will tag/wipe/cycle-stamp. Trade-off: experiment_scoped writers must now stamp `phase`/`cycle` at write time (small additive change across ~6 writers) so the wipe can reach tagger-blind partitions.

---

**Verified:** 2026-06-07 (ADR-077 — phase taxonomy registry + tests + doc; wiring in progress)

---

## ADR-078: Commercial wedge — sequence, don't choose (PG-00)

**Date:** 2026-06-07
**Status:** Decided — adopts the 2026-06-07 Product + Personal summit recommendation; resolves PG-00 and unblocks PG-06+ in `docs/BACKLOG.md`. (Reversible: a different wedge call is a one-line edit here + re-gating the PG items.)
**Related:** `docs/reviews/SUMMIT_2026-06-07_PRODUCT_GROWTH_REVIEW.md` (full summit record), BACKLOG PG-series, W-02 (multi-tenant — won't-do).

### Context

The summit asked "what's the commercial opportunity?" and found three companies hiding in the question, mostly mutually exclusive for the next ~6 months: **Wedge A** (the transformation story), **Wedge B** (build-in-public — the architecture/AI-use itself), **Wedge C** (multi-tenant SaaS). The governing tension: the platform is ~2 years more mature than the transformation it documents (genesis re-anchored 2026-05-30, baseline 304.62 lb, goal 185), and commercialising is the highest-fidelity version of the platform's recurring adversarial verdict ("more pounds lost than Lambdas deployed"). Dissents on record: Reeves/Maya (an audience swaps an adherence system for a performance one), Viktor (do no wedge for 90 days and just lose weight), Sofia (start audience-building immediately).

### Decision

**Sequence, don't choose forever.**
- **Wedge B (build-in-public) — NOW.** The only wedge true today; it monetises the building that's already happening and doubles as proof for the enterprise-AI-adoption mandate. **CAP:** it documents what exists and must NOT be used to justify net-new platform construction (this is the Reeves/Viktor guardrail).
- **Wedge A (transformation story) — ACCRUING.** Start the email list + chronicle cadence now (adopts Sofia's "list now"), but **monetise only at the hard gate of ~30 lb visible honest progress AND a sustained list** (PG-11).
- **Wedge C (multi-tenant SaaS) — SHELVED.** Stays behind the existing **W-02** trigger (a real second user begins onboarding). Not pulled forward.
- **Governing test on every PG item:** *more likely, or less likely, to reach 185?* Growth as a byproduct of real progress = yes; growth that requires more building or more performance = no.

### Consequences

Unblocks **PG-06** (Wedge-B build-log surface) and **PG-13 Phase 1** (surface the existing agent roster) as the sanctioned Wedge-B work under the cap. **PG-07** (reader predict-the-week) and **PG-10** (public-AI hardening) proceed as engagement infrastructure — any reader-facing AI must clear PG-10 first. **PG-11/PG-12** stay gated on the result + list milestones. The wedge is revisited at the ~30-lb / sustained-list milestone, or sooner if the build cap is being used to rationalise construction (the failure mode this ADR exists to prevent).

---

**Verified:** 2026-06-07 (ADR-078 — commercial wedge: B now / A accruing / C shelved; PG-00 resolved)

---

## ADR-079: Defer GuardDuty + AWS Config — accept the gap with compensating controls

**Date:** 2026-06-08
**Status:** Decided — owner choice during the 2026-06-08 A-grade readiness review. (Reversible: enabling both is a few CLI/CDK calls; revisit on the triggers below.)
**Related:** `docs/SECURITY.md`, `docs/COST_TRACKER.md` (ADR-063 budget), the A-grade review plan.

### Context

A CTO/CIO-grade AWS review flagged two missing account-level controls: **GuardDuty** (threat detection) and **AWS Config** (compliance baseline / drift rules). Both are standard enterprise-checklist items. Both also carry **recurring cost** — together ~$5–10/mo for an account this size, which is **~20–40% of the platform's ~$25/mo steady-state run-rate** against a hard $75/mo ceiling (ADR-063).

### Decision

**Do not enable GuardDuty or AWS Config at this time. Accept the gap as a documented, reasoned cost/risk trade-off**, rather than reflexively enabling paid services on a single-user, cost-capped personal platform. A reasoned decision with compensating controls is itself sound governance — not an oversight.

### Compensating controls already in place

- **CloudTrail** (`life-platform-trail`) — full API audit log → S3 (the forensic capability GuardDuty would build on).
- **Cost governor + AWS Budget** (ADR-063) — the most likely "incident" on a personal account is runaway spend; that is already detected and *enforced* (tiered AI degrade + the independent `life-platform-monthly-75` budget). A compromised key's blast radius surfaces as spend and trips the cap.
- **Least-privilege IAM** — per-Lambda CDK-owned roles, no wildcards beyond AWS-service limitations (`role_policies.py`).
- **No long-lived keys** — CI is OIDC-federated; only IAM principal is `matthew-admin` with **MFA on root**.
- **Data protection** — Secrets Manager only; encryption (KMS CMK, rotation on) + 35-day PITR; public AI rate-limited + budget-gated (PG-10).

### Revisit triggers

Enable both (codified in CDK) if any of: a **second/real user** onboards (W-02), a **commercial/compliance obligation** appears (SOC2, customer data), run-rate headroom makes ~$10/mo immaterial, or a security event makes threat detection worth the cost.

### Consequences

The AWS "account-controls" sub-grade stays below a literal-checklist A on those two items, by choice. The rest of the security axis (audit logging, least-privilege, encryption, MFA, budget enforcement, no long-lived credentials) is in place. `docs/SECURITY.md` records this stance so a reviewer sees the reasoning, not a gap.

---

**Verified:** 2026-06-08 (ADR-079 — GuardDuty/Config deferred by choice; compensating controls documented)

---

## ADR-080: CI quality gates — enforced mypy (tier-1), coverage floor, Lambda size gate

**Status:** Accepted (2026-06-08)

**Context:** After the A-grade overhaul (black + ruff already enforced; the `ai_calls` split done), the remaining code-quality gaps were *unformalized good practice*: mypy ran advisory, coverage was measured but not gated, and nothing stopped a new god-module. A CTO inspection wants these as enforced gates, not conventions.

**Decision:**
1. **mypy is ENFORCED** on a curated clean-module set (`tests/test_mypy_clean_modules.py::MYPY_CLEAN_MODULES`, mirrored by a blocking CI step). **Tier-1** = the budget/auth/inference core (`secret_cache`, `retry_utils`, `phase_filter`, `constants`, `bedrock_client`) — a type regression there is exactly the class of silent bug that risks spend or security. The broader clean set (`scoring_engine`, `character_engine`, `intelligence_common`, `ai_calls`/`ai_context`/`ai_summaries`) is enforced too; modules join the set only once clean (ratchet outward).
2. **Coverage regression floor** `--cov-fail-under=8` on `lambdas/`+`mcp/`. The offline line-coverage baseline is ~9% **by design** — handlers are integration-tested (live smoke + the post-deploy I1–I9 checks); the ~1600 offline tests are mostly structural/contract (wiring, role-policy, registry, schema). The floor prevents *backsliding*; it is not a quality bar. Ratchet up as offline coverage grows.
3. **Lambda size gate** (`tests/test_lambda_size_gate.py`): no NEW `*_lambda.py` may exceed 2000 lines. Three existing handlers are **grandfathered accepted-complexity** — `daily_brief_lambda.py`, `wednesday_chronicle_lambda.py`, `daily_insight_compute_lambda.py` — tightly-coupled email/compute pipelines whose split is deferred. The set may only shrink (split), never grow.

**Consequences:** Type-correctness on the spend/security core, coverage, and module size are now machine-enforced — quality can't silently decay. The grandfathered set + the low coverage floor are honest, documented trade-offs rather than hidden gaps.

---

## ADR-081: Adopt the orphaned intelligence Lambdas into CDK (drift elimination)

**Status:** Accepted (2026-06-08)

**Context:** Three intelligence Lambdas — `ai-expert-analyzer` (Observatory analysis), `field-notes-generate`, `journal-analyzer` — were created by CLI early in the project and never lived in IaC. The drift was real and visible: no shared layer, no DLQ, no error alarm, `Tracing=PASS_THROUGH`, and all three shared the CDK-owned `daily-insight` role rather than having their own. A `# Cannot import to CDK (already exists)` comment in `compute_stack.py` even shipped a manual `aws lambda update-function-configuration` recipe for keeping their layer current — exactly the hand-maintenance IaC exists to remove. A CTO inspecting `aws lambda list-functions ∖ (CDK-managed)` would find a non-empty set; the goal is ∅.

**Decision:** Define all three in `LifePlatformCompute` via `create_platform_lambda(...)`, identical in shape to their compute siblings:
- **Dedicated least-privilege role each** (`role_policies.intelligence_{ai_expert,field_notes,journal_analyzer}`). The grant-set is intentionally identical to `compute_daily_insight()` — DDB R/W, KMS, S3-config read, ai-keys secret, Bedrock inference-profile, DLQ, budget-tier SSM — because the workload **already runs on that exact grant-set** (the shared daily-insight role), so the role swap is provably non-breaking while still giving each function its own role (one-role-per-Lambda).
- Standard convergence: shared layer, DLQ, X-Ray `ACTIVE`, 30-day log retention, a digest-routed error alarm, and a CDK-owned EventBridge schedule preserving each live cadence (`cron(0 14 * * ? *)` / `cron(0 18 ? * SUN *)` / `cron(0 10 * * ? *)`). Handlers move to the package path (`intelligence.<module>.lambda_handler`) so they deploy from the standard monorepo asset; absolute imports (`from constants import …`) resolve unchanged from the asset root.

**Adoption mechanics:** Because the physical functions already exist, CloudFormation sees the synthesized resources as additions — a plain `cdk deploy` would fail "function already exists." Adoption is therefore an **owner-run, in-the-loop step**: either (a) delete the three stateless functions + their CLI-created EventBridge rules, then `cdk deploy LifePlatformCompute` recreates them under IaC with the same names/ARNs (chosen — these are stateless, idempotent, gap-aware jobs with no Function URLs or event-source mappings, so a sub-minute window away from cron times has no effect), or (b) two-phase `cdk import` (import matching live, then converge) for strict zero-downtime. The old CLI rules are deleted so each function fires once, from its CDK rule.

**`og-image-generator` (us-west-2) — also adopted (revised 2026-06-08):** the daily Pillow PNG/WebP share-card generator was the fourth CLI orphan. The initial read (that its source wasn't in the tree) was wrong: downloading the deployed package showed it byte-identical to `lambdas/web/og_image_lambda.py`, already in the repo. So adoption needed only CDK wiring — defined in `LifePlatformOperational` via `create_platform_lambda` with `custom_policies=operational_og_image_generator()` (S3 read `public_stats.json` / write `generated/assets/images/*` / CloudFront invalidation — no DDB), the standalone `pillow-layer` as an additional layer (no shared utils layer — it imports none), 512 MB / 60 s, preserving the `cron(30 19 * * ? *)` cadence. Same owner-run delete-and-recreate as the three above.

**Separate pre-existing bug surfaced (not fixed here):** `web_stack`'s us-east-1 `life-platform-og-image` references the same file via handler `web.og_image_lambda.handler`, but the module defines `lambda_handler`, not `handler` — so that function has errored on every invoke since 2026-03-20. It's the CloudFront dynamic-OG origin (rarely hit). Flagged for a focused follow-up; untouched here to avoid scope creep into `web_stack`.

**Consequences:** `aws lambda list-functions ∖ CDK` shrinks by **four** — the orphan set reaches **∅**. All four adopted functions gain the platform's monitoring, layering, and least-priv posture automatically going forward; the manual layer-update recipe is deleted. One latent `web_stack` handler bug is now documented rather than silent.

---

## ADR-082: Security & supply-chain hardening (SAST, action pinning, Dependabot)

**Status:** Accepted (2026-06-09)

**Context:** A "blind-spot" audit found the security baseline strong (per-Lambda least-priv, Secrets-Manager-only, OIDC, budget guard) but missing three cheap, standard supply-chain controls: no SAST (ruff `select` lacked the `S`/bandit ruleset), GitHub Actions pinned to **mutable** `@vN` tags (silent-injection vector), and no automated dependency-update channel.

**Decision:**
1. **Enable ruff `S` (flake8-bandit) as SAST**, gated by the existing CI ruff step — zero new tooling. The high-signal rules stay ON (`S102` exec, `S307` eval, `S301` pickle, `S506` unsafe-yaml, `S602/4/5` shell-injection, `S324` weak-hash, `S501` no-cert-verify, …). Rules that only ever fire on this **single-user, stdlib-only, Secrets-Manager-only** platform's intentional conventions are silenced with documented reasons (`pyproject.toml`): `S310` (the urllib-only HTTP convention; URLs are constant API bases), `S110/S112` (deliberate best-effort try/except), `S101/S108/S311`, `S603/S607` (subprocess always list-form, no shell). The full audit found **zero genuine findings** — no hardcoded secret *values* (S105/S106 only flagged secret *names*/URLs/sentinels), so `S`'s value is forward-looking: catch a future real `eval`/`pickle`/`shell=True`/hardcoded value.
2. **Pin all GitHub Actions to commit SHAs** (`# vN` comment kept for readability) across every workflow — eliminates the mutable-tag injection vector.
3. **Add Dependabot** (`.github/dependabot.yml`) for `github-actions` + the dev and CDK pip toolchains — updates (incl. the action SHAs) arrive as reviewable PRs.
4. **Broaden `pip-audit`** to both dependency manifests with a loud `::warning::` on any CVE, kept **non-blocking** (Dependabot is the remediation channel, so an unfixable transitive CVE never red-walls deploys).

**Not done (accepted):** GuardDuty/Config stay deferred (ADR-079). GitHub native secret-scanning + push-protection is an owner repo-settings toggle (recommended, complements the bespoke `ci/deprecated_secrets.txt` grep).

**Consequences:** SAST now runs every CI; supply-chain injection via action tags is closed; dependency drift is surfaced + auto-PR'd. All at ~zero added cost/latency. The `S`-ignore list is the documented contract for "what's an accepted convention vs a real smell" going forward.

---

**Verified:** 2026-06-09 (ADR-082 — ruff `S` SAST enabled + tuned; all GitHub Actions SHA-pinned; Dependabot added; pip-audit broadened)

---

## ADR-083: Single-region is an accepted risk (no cross-region DR)

**Status:** Accepted (2026-06-09)

**Context:** The platform runs in **us-west-2** (data plane: Lambdas, DynamoDB, S3, SQS, SNS) with a small **us-east-1** edge footprint (CloudFront + its Function-URL Lambdas). There is no second region, no cross-region replica, no Route 53 failover. A blind-spot audit flagged this as an undocumented acceptance — acknowledged in the DR doc but never made a decision of record.

**Decision:** **Accept single-region operation.** A full us-west-2 regional outage is a tolerated failure mode for a solo-operated, single-user personal platform:
- **RPO ≈ 0 within-region** — DynamoDB PITR + S3 versioning protect against the *likely* incident (corruption/deletion), and a PITR restore has been rehearsed (`docs/DISASTER_RECOVERY.md`).
- **RTO for a region loss = hours-to-days, and that's acceptable** — the "service" is a daily-brief email + a personal site; a multi-hour outage during a (rare) regional event has no real cost. Ingestion is **gap-aware**, so once the region returns the next scheduled run backfills automatically — no manual catch-up.
- **Cost/complexity not justified** — cross-region DDB global tables + S3 CRR + warm Lambda/CloudFront failover add real monthly cost (against the $75 ceiling, ADR-063) + standing complexity to defend against an event whose blast radius is "my email is late."

**Revisit triggers:** a second/paying user, an SLA commitment, or the platform becoming something whose multi-hour unavailability actually matters.

**Consequences:** The single-region posture is now a decision, not a silent gap. The DR doc covers the within-region scenarios (the ones that happen); region-loss is explicitly out of scope by choice.

---

## ADR-084: Test-coverage philosophy + the ratchet cadence

**Status:** Accepted (2026-06-09) · refines ADR-080

**Context:** Offline line coverage sits at ~**10%**, which looks alarming against a reflexive "aim for 80%." The number is honest but needs its rationale on the record so it isn't mistaken for a gap to inflate.

**Decision — coverage strategy is layered, not line-%-driven:**
- **Why offline line coverage is low by design:** the bulk of `lambdas/` is integration *glue* — "call an upstream API → reshape → write DynamoDB." Driving that to 80% offline means mocking every `boto3`/`urllib` call and asserting the code calls the mocks as instructed — testing the mocks, not reality (high effort, false confidence). Line coverage is a poor proxy for safety in an integration-heavy serverless platform.
- **The real safety net (what replaces line-%):** ~1,600 **contract/structural** tests (the breakages that actually occur here — an unmapped Lambda, a missing role grant, an unwired tool, a schema drift), **pure-logic unit tests** (scoring, character engine, the ingestion `transform`/normalize layer — #79), and **live integration** (post-deploy I1–I9 + auto-rollback, canary, qa-smoke, freshness-checker, the `life-platform-ops` dashboard + alarms). The platform runs daily on real data; real failures alarm within minutes.
- **The accepted risk:** a handler-logic bug that contract tests miss surfaces *live* (caught fast by alarms/rollback), not at dev time. We buy that down where it pays — **pure logic** — not by mocking glue.

**Ratchet cadence (the teeth ADR-080 lacked):**
1. **Coverage floor** raised **8 → 9%** (current offline ~10%; the floor tracks ~1 pt under actual to block backsliding without being brittle). Re-baseline upward whenever a batch of pure-logic tests lands.
2. **mypy-clean set** (currently 11 modules, `tests/test_mypy_clean_modules.py`) grows **outward by intent** — add a module the same PR it's made type-clean; no blanket target.
3. New `transform()`/scoring/normalization code ships **with** its unit test (the highest-ROI layer).

**Not done (accepted):** a **pre-commit framework** (`.pre-commit-config.yaml`) was evaluated and **deferred** — it installs to `.git/hooks/pre-commit`, which already holds the bespoke `sync_doc_metadata` doc-header hook; integrating the two is more work than the solo-dev value justifies, and **CI already enforces** ruff/black/mypy on every push.

**Consequences:** "10% coverage" now reads as a deliberate, documented strategy rather than negligence; the ratchet has concrete mechanics; the pre-commit trade-off is explicit.

---

## ADR-085: Infra-liveness is a separate signal from data-freshness (ER-01)

**Status:** Accepted (2026-06-09) · closes the 44-day-outage finding · implements the S-06(b) split as mandatory

**Context:** The 2026 Garmin outage ran **44 days** unnoticed. The existing `freshness_checker` + `slo-source-freshness` alarm are **behavioral-freshness** checks — "is the newest `DATE#` record recent?" On a personal platform that signal is structurally ambiguous: "no new data" can mean *the user didn't log / didn't wear the device* (benign) **or** *the ingestion Lambda has been erroring on every run for weeks* (critical). That ambiguity is exactly why the gap was ignored until it was 44 days wide (the S-06 / N-01 "structurally noisy alarm" problem).

**Decision — track infra-liveness as a second, independent metric:**
- For each **active OAuth/API pull source**, the SIMP-2 `ingestion_framework` now records a per-run outcome to a `USER#system / INGEST_HEALTH#{source}` sentinel — `last_success_ts`, `last_attempt_ts`, `consecutive_failures`, `last_error_class` (auth / throttle / transport / parse) — plus an EMF metric (`LifePlatform/IngestLiveness`). `last_attempt_ts` is stamped whenever the **Lambda ran**, decoupled from whether new data came back. The auth-breaker-suppressed path records a continued failure, so a source 401-ing every run grows its streak **with zero new data**.
- The daily `pipeline_health_check` `check_ingest_liveness` mode (an extension, **not** a new Lambda) reads the sentinels and asserts two arms via the pure `ingest_health.evaluate_source_health`:
  - **failure-streak arm** (running-but-erroring): `consecutive_failures >= 3` → alert. Tight, fires fast; reuses the canary's 2-consecutive-fail buffer precedent so single blips stay silent.
  - **attempt-staleness arm** (cron silently stopped / Lambda dead): no attempt in ~26h → alert. Generous, so overnight gaps (hourly sources pause 10 PM–4 AM) never false-fire; this is the arm that notices a de-scheduled cron.
- **Two metrics, two alarms, kept separate:** behavioral `StaleSourceCount` (`slo-source-freshness`, unchanged) and infra `UnhealthySourceCount` (`ingest-liveness-unhealthy`, new). `freshness_checker` stays behavioral-only by design.

**Why not just tune the freshness alarm:** the two questions are genuinely different — "did the user feed this?" vs. "did the pipeline run?" — and conflating them is what produced a signal noisy enough to ignore. The decision core is a pure, offline-tested module (`lambdas/ingest_health.py`) so the streak/staleness logic is verified in isolation across all four error classes.

**Consequences:** a source whose OAuth has rotted alerts within ≤2 daily heartbeats even if the user logged nothing; a genuinely-unfed-but-healthy source stays silent; a silently-removed schedule is caught by attempt-staleness. The 44-day-class incident now has a dedicated detector. Layer bumped **v76 → v77** (new `ingest_health` module). New alarm: 16 → 17.

---

**Verified:** 2026-06-09 (ADR-085 infra-liveness heartbeat — INGEST_HEALTH sentinel + ingest_health decision core + check_ingest_liveness mode + ingest-liveness-unhealthy alarm; layer v77; ADR-083 single-region; ADR-084 coverage philosophy)

---

## ADR-086: Public honesty surfaces — and the line we will not cross (the ghost-projection refusal)

**Status:** Accepted (2026-06-13)

**Context:** The platform's thesis is the "anti-Blueprint" — an honest documentary, not a transformation highlight reel. A batch of public features built 2026-06-13 (the chronicle podcast, the cockpit time scrubber, the inference receipt, the Wrong Page, the survival curve, cycle post-mortems, the visitor mirror) all draw on a shared principle worth recording, because the principle is what makes the features defensible and one of them is a deliberate *refusal*.

**Decision — the honesty surfaces and the rule behind them:**
- **Every public AI-derived surface shows its own uncertainty and its own misses.** The Wrong Page (`/api/wrong`) publishes the validator's caught claims + the per-coach prediction ledger (confirmed/refuted/inconclusive/expired), uncurated. The survival curve (`/api/survival`) publishes a Laplace-smoothed odds-of-reaching-day-30 with the `n=2 is narrative, not statistics` caveat *in the payload itself*. The inference receipt (`/api/inference_receipt`) publishes the live AI meter against the $75 ceiling. Coach narratives now carry each coach's own track record and are instructed to own misses in their own voice.
- **Engagement is measured by deliberate acts only** (weigh-ins, food logs, journal entries) — never passive wearable streams, which flow whether or not the user shows up. The survival/post-mortem "collapse" definition (4+ consecutive silent days) follows from this.
- **History is cross-cycle and immutable.** The time scrubber serves any past morning's sheet (pilot/prior-cycle records included); past responses are cached 24h because the past does not change.
- **Visitor inputs never leave the browser.** The mirror computes percentiles client-side against the published distribution; nothing typed is sent, stored, or logged.

**The line we will not cross (ghost counterfactuals, feature #5 — HELD, not built):** the originally-pitched "had sleep held ≥7.5h, the model projects weight *here*" would extrapolate a counterfactual **time series** from a **cross-sectional Pearson r**. That is correlation presented as causation with a fabricated forward line — the precise move every other surface on the site exists to refuse. **Decision:** never ship the projection form. If built, #5 must be a **within-sample contrast only** ("on the N days sleep was ≥7.5h, recovery averaged A; on the M days below, B; r=…, q=…; a contrast, not a projection"), gated on FDR-significant correlations actually existing in the engine (currently zero — cycle 3 is too young), and verified against live data before shipping. Held until ~2 weeks of cycle-3 data exist.

**Consequences:** the public surfaces are credible *because* they expose failure; the refusal is on the record so a future "just add the projection line, it looks cooler" request is met with the documented reason it stays out. The honesty is the product.

---

## ADR-087: Podcast audio realism is bounded by a two-stage (script → TTS) pipeline; monitor for a NotebookLM-grade API

**Status:** Accepted (2026-06-14)

**Context:** The podcast ("The Panel" + Episode 0) should feel like a real NotebookLM-style conversation — natural overlaps, interjections, laughter, banter. Our architecture is deliberately two-stage: **Bedrock (Sonnet) writes a script** (a list of `{speaker, line}` turns), then **Gemini 2.5 multi-speaker TTS reads that finished script** single-pass (`lambdas/gemini_tts.py`). NotebookLM, by contrast, uses Google's internal Audio-Overview model that *generates the performance holistically* — it can overlap speakers, improvise backchannel, and laugh because writing and performing are one model.

**Decision — accept the Gemini two-stage approach for now, and name the ceiling explicitly:**
- **The audio model is a real ceiling.** Gemini TTS performs *exactly* the turns it is given, sequentially. It will not truly overlap speech, interrupt, or laugh unless the script implies it — and even then it renders read text, not improvised performance. This is a property of the public API, not our prompt. We have **pushed the lever we control** — the script + style prompts now instruct genuine back-and-forth (short interjections, reactions, gentle interruptions, varied turn length; no bracketed stage directions) — which is where most of the perceived "podcastiness" comes from.
- **Why not the better tech:** Google's **Studio MultiSpeaker** voice (closest to NotebookLM's conversational audio) is **allowlist-only** (`403 PERMISSION_DENIED`), and there is no public "Audio Overviews" generation API. Gemini 2.5 multi-speaker is the best generally-available primitive and is what we ship.
- **Auth/account constraint (related):** the Gemini key lives on a **personal Google account** because the managed `mattsusername.com` Workspace domain blocks AI Studio (admin policy).

**Monitor trigger (revisit this ADR when):** Google ships a public **Audio Overviews / conversational-audio generation API**, OR grants **Studio MultiSpeaker allowlist** access, OR Gemini TTS adds true multi-speaker overlap / non-verbal control. Any of these → swap the synth backend in `gemini_tts.py` (the script stage + the whole QA pipeline stay; only the voicing call changes). Until then the realism gap is a known, accepted limitation, not a bug.

**Consequences:** expectations are set — the show is "two AI voices reading a genuinely conversational script," not generated banter; the upgrade path is a single isolated backend swap; and the gap is tracked rather than re-litigated each time an episode "doesn't feel quite like NotebookLM."

---

## ADR-088: Hevy Title Counters — performed-derived N (per-phase) + reset-epoch Y; force_title lockdown

**Date:** 2026-06-16
**Status:** Implemented (code shipped + tested; layer rebuild + cdk deploy + S3 config upload + MCP redeploy pending — see RUNBOOK §"Hevy Title Renderer — Deploy Steps (ADR-088)").
**Supersedes:** the ADR-067 Amendment (2026-05-31). **Related:** ADR-066 (write-loop), ADR-067 (title + WHY-note), ADR-069 (draft_custom), `lambdas/routine_title.py`, `lambdas/hevy_common.py`, `mcp/tools_hevy_routine.py`, `config/training_phases.json`.

**Decision.** The compiler is the single source of truth for a routine's title `<Phase> - <Type> - <N> - <Y>`. The chat model commits with **no title**; the renderer names it. The counters are now honest and performed-derived:

- **N** = PERFORMED workouts of this type since the current phase started (`current_started`), **+1**. Resets when the phase advances. A planned-but-skipped session never inflates it (we count performed, not pushed).
- **Y** = distinct PERFORMED workouts since `reset_epoch_date`, **+1**. Reset-relative (zeroed by each experiment reset), honest (skips don't inflate). Deduped by `workout_uid` across Hevy + MacroFactor.
- **Type resolution WITHOUT parsing titles** (work order continuity rule): a stored `archetype` sticker if present, else the archetype of the nearest pushed routine whose `target_date <= the workout date` (the routine index carries `archetype`). Because we count *performed* workouts (each once via `workout_uid`), the routine-index noise — duplicate drafts, future-dated planned routines — cannot inflate the count.
- **Title lockdown:** `manage_hevy_routine` ignores any caller-supplied `title` unless `force_title=true` (logs a warning). `force_title` defaults off; the rendered convention is the only normal path. The tool description + schema instruct callers: *do not pass a title.*

**Why this reverses the 2026-05-31 amendment.** That amendment made N all-time-per-type-since-experiment-start (no phase reset) and counted *pushed* routines. The 2026-06-16 work order restores per-phase N and makes both counters performed-derived for honesty (the experiment reset + skipped-session cases both demand it). Phase collisions (`Foundation - Push - 3` vs `Build - Push - 3`) are accepted — the phase prefix disambiguates.

**Findings that shaped the design (verified against live data):**
- The convention *had* shipped, but `_action_dry_run` never passed `title_context`, so it previewed the raw `ir.title` placeholder (`Push — {date}`) — the source of the "regressed" report. Fixed: dry_run now renders the convention (truthful preview); dry_run + commit share `_resolve_title_inputs`.
- Performed-workout records carry **no archetype field** (only `title`/`exercises`/`workout_uid`), so performed-by-type can't be computed by title-parsing (forbidden) — hence the resolve-by-routine join. `hevy_common.normalize_workout` now also preserves Hevy's `routine_id` as `hevy_routine_id` for a future exact link.
- `reset_epoch_date` / Foundation `current_started` = **2026-06-16** (the actual first post-reset performed push — the work order assumed 06-15; corrected against the record). Seed consequence (correct, not a bug): the next generated push reads `Foundation - Push - 2 - 2`, the next pull `Foundation - Pull - 1 - 2`.

**Type resolution (micro-decision now closed):** N counts *performed* workouts; each workout's type resolves in priority order: (1) a stored `archetype` sticker, (2) the **exact** routine it was performed from — `workout.hevy_routine_id` (preserved by `normalize_workout`) matched against the routine-index entry's `hevy_routine_id` (added to `routine_repo.put_versioned`), (3) nearest pushed routine by date. The exact link removes the deviated-session ambiguity the date heuristic could mis-tag; the date fallback still covers ad-hoc/legacy workouts with no routine link. No ingestion coupling, no extra count-time DDB calls (the link rides on the already-loaded index).

**Phase advancement (operator):** to advance a phase, edit `config/training_phases.json` — flip `current` and bump `current_started` to that date (resets N per type) — then re-upload to S3 (`config/`). No code deploy. `reset_epoch_date` only changes on an experiment reset.

---

## ADR-089: Cut benchmarking (BENCH-1) — descriptive divergence vs his own proven cut, weekly-computed, no predictor

**Date:** 2026-06-19
**Status:** Implemented (code + tests shipped; CDK deploy of `episode-detect` + one-time backfill + MCP redeploy pending — Matthew runs all deploys per the work order). **Related:** `docs/coaching/WORKORDER_BENCH1_benchmarking.md`, `docs/coaching/PROVEN_BLUEPRINT.md`, `lambdas/compute/episode_detect_lambda.py`, `mcp/tools_benchmark.py`. **Privacy:** PRIVATE — nothing in BENCH-1 may surface to Elena Voss or any public surface.

**Context.** PROVEN_BLUEPRINT mined Matthew's 14-year Withings/Strava/Hevy history: 16 distinct ≥15 lb loss episodes, **0 that held** (regain ≈ 0.79× as fast as loss; walking volume collapses ~8 wk post-trough). Losing is proven; holding has never been solved. BENCH-1 operationalizes that finding as a tool the coach can consult.

**Decision.**
- **New partition (two thin derived computed sources), not a separate store** (Omar). `weight_episodes` (one item per detected episode) + `training_reference` (singleton: by-band proven volumes + the proven trajectory curve). Both keyed + serialized exactly like `computed_metrics` (PK `USER#…#SOURCE#{source}`, SK `DATE#…`, Decimal), read via `query_source`. Written **without** a `phase` attribute = cross-phase reference data: survives an experiment reset and passes the ADR-058 default filter. No TTL.
- **Weekly compute, not nightly** (Viktor). `episode-detect` Lambda runs Sunday (EventBridge `cron(0 17 ? * SUN *)`) + manual-invoke; reads full history (bypassing the phase filter — detection spans pre-genesis). The live `pace` comparison is computed at tool-call time from the precomputed reference + recent Withings, so the daily value never waits on the weekly job.
- **One view-dispatched MCP tool** (Anika), `get_benchmark` (`pace` | `episodes` | `maintenance`) — protects the SIMP-1 tool budget.
- **No predictor** (Henning, hard scope). There is no "will-he-hold" model — `n_held = 0`, no positive class. BENCH-1 is purely *descriptive* divergence (current vs proven). Every numeric block carries `confidence` + `n`; small-n ⇒ `confidence: "low"`; no causal language in any output string.
- **Forward framing** (Nathan, hard scope). Output strings never tally failures (no "0 of 16 held", no regain count) — they surface the forward signal ("walking is X vs the ~Y/wk that worked at this weight"). A unit test asserts the `maintenance` view's rendered signal contains no failure-count string.

**Implementation note (algorithm correction).** The work order's pasted `turning_points` ZigZag snippet has a `direction=0` initialization bug that locks no extreme → records **zero** pivots (verified: 0 episodes on the real series). It was replaced with the standard ZigZag (running high/low since the last pivot), which reproduces the work order's validated values exactly: 16 loss / 15 regain, mean loss 2.96 / regain 2.41 lb/wk, 0 held, reference cut 116.4 lb / 33.6 wk (2024-09→2025-04), walks_wk 11.5 → 4.38 post-trough. Pinned by a datadrops-gated test (skips in CI; `datadrops/` is gitignored).

**Cost (Dana):** pennies/mo — one weekly pure-Python Lambda (no Bedrock), two thin derived records.

**Out of scope (board-rejected on this work order):** any holding/regain predictor or classifier; any public surface; a separate analytical store; nightly recompute; causal language; rendering the reversal count in a brief/digest. Re-propose separately if ever revisited.

---

## ADR-090: Derived meal layer — best-effort meal grouping as a recomputable projection over raw MacroFactor

**Date:** 2026-06-19
**Status:** Implemented (Phase 0–1 live: layer v86 + MCP + freshness deployed, 780 items / 114 days backfilled 2026-06-19; Phase 2 LLM namer deferred). **Related:** `docs/SPEC_MEAL_GROUPING_2026-06-19.md`, `docs/reviews/REVIEW_MEAL_GROUPING_2026-06-19.md`, `lambdas/meal_grouper.py`, `lambdas/meal_templates_seed.py`, `lambdas/meal_projection.py`, `config/food_vocabulary.json`, `mcp/tools_meals.py`, `deploy/backfill_meals.py`.

**Context.** The raw MacroFactor food log is an ingredient ledger (per-food rows). To support meal-level analytics now and a public "your most-eaten meals" view later, we group entries into the meals they were eaten as. Phase 0 confirmed three ways (ingestion code, raw CSV header, stored DDB item) that **the export carries no Breakfast/Lunch/Dinner/Snack bucket** — so timestamp + content inference is the primary (only) segmenter. A 114-day history scan measured the real same-timestamp collision rate at ~4% (the naive detector's 93% was word-split/anchor-set false positives), validating the anchor-SET design.

**Decision.**
- **Raw is sovereign; meals are a derived, recomputable projection** in a distinct source `macrofactor_meals` (clean provenance + freshness, not folded into `computed_metrics`) — Omar. Three invariants: raw untouched · every meal `inferred`+`confidence` · conservation-of-food (`sum(rollups) == raw totals`, asserted per day; the backfill halts on any mismatch). `member_refs`/`sides` point into raw; `rollup` is a read cache.
- **Deterministic-first is the system of record** (Anika/Priya). Normalize → `GAP_MIN=15` time-gap segment (reuses the `get_glucose_meal_response` algorithm — single source of truth) → anchor-SET content-split (known multi-protein dishes = one core; an orphan protein attaches as a `side`, never a phantom meal) → template-centroid match. Confidence is **coverage** (fraction of the cluster the template explains, by items + calories), so a minor seeded anchor under an unseeded-dominant cluster falls below `CONF_MIN=0.7` → `uncategorized` (counted in totals, excluded from analytics) rather than a confidently-wrong name. `algo_version` enables safe full-history recompute.
- **Aggregates key on `signature`/`template_id`, never the display name** (Henning, hard constraint) — a flaky/regenerated name can never corrupt a count. `most_eaten` is n-floored; snacks aggregate by canonical member token, not the "Snack" occasion.
- **Canonical vocabulary is a first-class object** (`config/food_vocabulary.json`, staged into the layer alongside the grouper). Spelling-of-the-same-food-only rule: distinct dishes stay distinct (Phase-2 LLM names them); only spelling variants of one food collapse.
- **One fat MCP tool** `manage_meals` (SIMP-1): `get_day` / `most_eaten` / `regroup_day` / `list_templates`.
- **Scoped delete on the LLM-facing MCP role** (Yael). `regroup_day` prunes stale meal ordinals, which needs `DeleteItem` — but the single-table store means "the whole table" is every source (raw health data included). So `DeleteItem` is granted via a **dedicated statement conditioned to `dynamodb:LeadingKeys = USER#matthew#SOURCE#macrofactor_meals`**, never table-wide; the no-write-to-raw test is code, this condition is the actual IAM boundary. Mirrors the `site_api_ai` `RATE#*` LeadingKeys pattern.
- **Format-drift guard** — MacroFactor's default export is a daily-summary (empty `food_log`); when it silently reverts the date stays "fresh" but the grouper starves. `freshness_checker_lambda` re-enables `macrofactor` (format-aware: alert if the last N records have `entries_count==0`) + a `MacroFactorFormatDrift` metric; surfaced in `get_freshness_status`.

**LLM (Phase 2, deferred).** A Haiku namer supplies a cosmetic label to residual `uncategorized` clusters only — signature-cached, promote-to-template (≥3 → `learned`, then $0), Batch-API backfill, monthly cap that fails safe to `uncategorized`. Never on the hot path, never a read-path dependency; frozen-as-data + correctable. Lifetime cost is sub-$0.35 backfill + pennies/mo decaying to zero.

**Out of scope (this build):** editing meals back into MacroFactor (it stays authoritative for what was logged); the public meal view + level-up loop (Phase 3, gated on the level-up loop per the Product board); per-bite timing.

**Known follow-up (pre-existing, surfaced during the IAM scoping):** `delete_platform_memory` and `clear_sick_day` call `table.delete_item` but the MCP role never carried `DeleteItem` before this ADR — those deletes are latently `AccessDenied`. Not fixed here (each needs its own partition-scoped `LeadingKeys` statement); tracked for a follow-up.

---

## ADR-091: Source-state honesty guard as a cross-coach standard (no confident verdict on data you can't see)

**Date:** 2026-06-19
**Status:** Standard adopted; reference implementation live for `training_coach` (DI-1.3). **Related:** WORKORDER_DI1, `lambdas/source_state.py`, `lambdas/intelligence_common.py` (`movement_assessability` / `apply_movement_honesty_guard`), `mcp/tools_health.py::tool_get_readiness_score` (the prior-art guard this generalizes).

**Context.** Dr. Chen (`training_coach`) wrote six consecutive days of "you're under-training" — a confident *negative* verdict — while the movement sources that verdict depended on were dark: Strava deliberately paused (402 paywall) and Garmin rate-limited (429). The coach reasoned from the *absence* of data ("0 sessions, all rest days") as if it were *evidence of absence*. The readiness tool already had the right shape (`is_forward_dated` + `staleness_warning`: surface the real data date, don't assert on data that doesn't exist yet) but it lived in one tool. The failure mode is general: any coach can manufacture a false verdict when its primary signal is stale/paused/rate-limited, and the nightly thread's continuity loop then *re-confirms* the artifact. This is the Henning standard — honesty over assertion — written into code.

**Decision.**
- **A domain verdict must gate on its primary source's state.** Before a coach emits a negative/deficiency verdict ("under-training", "sedentary", "not sleeping enough", "under-eating protein", …), it checks the operational state of the source(s) that verdict rests on via the single resolver `source_state.resolve_source_state` (`live` / `paused` / `rate_limited` / `stale`; freshness wins for `live`). If the authoritative source is not `live`, the coach states **"not assessable + which source + why"** and withholds the verdict — while still reporting what the *available* signals do show.
- **Two layers, the deterministic one is the guarantee.** (1) a prompt constraint keeps the generated narrative honest; (2) a **deterministic write-time backstop** sanitizes the persisted `position_summary` (an LLM instruction alone is not a guarantee). `movement_assessability` + `apply_movement_honesty_guard` are the reference pair; other domains get an analogous `<domain>_assessability` gate over the same resolver.
- **Build the verdict on the authoritative signal, not a proxy.** Training stimulus comes from the workout log (Hevy first), never from steps; the guard pattern travels with a "primary-signal-first" pull order (§4a for training; each coach names its own).
- **`paused` ≠ `stale` ≠ `broken`.** A deliberately-off source is legible as off-by-design (`source_state.DECLARED_PAUSED_SOURCES`), so neither a coach nor an alarm treats an intentional pause as silent failure (DI-1.1; the pipeline health check excludes paused sources from the liveness alarm and from the masking healthcheck "ok").
- **Correlational only.** No causal language in any guarded output string; the guard withholds, it does not assert the opposite.

**Alternatives rejected.** *Per-coach ad-hoc staleness checks* — drift and silent divergence; the whole point is one resolver + one guard pattern. *Suppress a coach entirely when any source is down* — throws away the assessable signal (Hevy was fresh the whole time); the guard withholds only the part that depends on the dark source. *Prompt-only honesty* — non-deterministic; an LLM told "don't say under-training" still sometimes does, hence the write-time backstop. *Fix it in the readiness tool only* — leaves every other coach exposed to the same artifact.

**Rollout.** `training_coach` is the reference (DI-1.3, live after the next layer deploy). The remaining operational coaches (`sleep`, `nutrition`, `glucose`, `physical`, `mind`, `labs`, `explorer`) adopt the gate incrementally — each wires its primary source(s) into an assessability check before any deficiency verdict. Incremental by design: no big-bang rewrite, and every adoption is a small, independently-testable diff with a regression test mirroring `test_coach_guard_withholds_undertraining_when_strava_paused`.

**Out of scope.** Any new activity/effort/quality scoring model; rewriting coach generators beyond the pull-order + the assessability gate; causal claims; a public surface.

---

## ADR-092: Detect silent ingestion gaps — source-of-truth reconciliation + interior-gap scan (DI-2)

**Status:** ✅ Active — 2026-06-21

**Context.** A Strava `Walk` ingestion bug (the UTC-fetch-window vs. local-date-filter mismatch fixed in #180) silently dropped four evening-PT walks. It went unnoticed for days because **every freshness/health check in the platform reads only DynamoDB** — `freshness_checker`, the `get_freshness_status` MCP tool, `qa_smoke`, and ingest-liveness all compare against the latest `DATE#` record per source. They see only the **high-water mark**, so a gap *behind* it is structurally invisible: same-day Hevy `WeightTraining` kept the latest date advancing while the walks were missing, and the source read green the whole time. Two distinct blind spots: (a) a *silent drop* — an activity the upstream API has that never landed in the store; (b) an *interior hole* — a daily source going dead mid-window then resuming.

**Decision.** Add two complementary detectors, each emitting a CloudWatch metric with a digest alarm.

- **(A) Source-of-truth reconciliation** (the only thing that catches a silent drop): a daily `{"reconcile": true}` path **inside the existing Strava ingestion lambda** (reuses its auth/client/DDB — no new secret-access surface, preserving the one-lambda-holds-Strava-creds boundary) pulls a trailing 14-day activity set from the Strava API and diffs it against the store. Gaps → `LifePlatform/IngestReconciliation::MissingActivityCount{Source=strava}` → alarm `ingest-reconciliation-strava`. EventBridge `cron(20 17 * * ? *)` (10:20 AM PT, UTC-fixed). The diff is **dedup-aware** — an API activity counts as present if the store has the same `strava_id` *or* an activity within 120s (mirrors the ingestion `_dedup`), so a collapsed GPS-drop twin is not a false gap. Reconcile failures return 200 (never trip the unrelated `ingestion-error-strava` alarm); a rotated `refresh_token` is persisted.
- **(B) Interior-gap detection** (the daily-source hole): `freshness_checker` scans each **daily** source's trailing 14d of `DATE#` records and flags any date missing *inside* the present `[first, last]` span (trailing/leading absence is recency, left to the staleness check). Only sources expected every day are judged (`DAILY_SOURCES = whoop, apple_health, eightsleep, habitify`); sparse sources (strava activities, withings weigh-ins, food_delivery) have legitimate empty days and are excluded so rest days don't false-fire. → `LifePlatform/Freshness::InteriorGapCount` (suppressed on sick days) → alarm `freshness-interior-gap`.

**Why both, and why reconciliation can't be skipped.** A trailing-refresh / re-ingest would only heal *late-arriving* data; it would NOT have caught the #180 bug, because that drop was deterministic — the activity was never returned by any `fetch_day` pass, so re-running the fetch drops it again. Only a diff against the upstream source reveals a deterministic logic drop. Interior-gap detection (DDB-only) is cheaper and broader but is blind to sparse-source drops like Strava (a missing day there is usually just a rest day) — hence it covers the *other* blind spot, not this one.

**Alternatives rejected.** *Generic "missing calendar date" alerting for all sources* — false-positives on every sparse source's rest day. *A separate reconciliation lambda* — would need its own copy of the Strava client + a second holder of `life-platform/strava`, widening the credential surface for no benefit; the ingestion lambda already has everything. *A CLI-created EventBridge rule* — would orphan the rule from CDK (violates ADR-081's "all infra in CDK"); the rule lives in `ingestion_stack`. *Self-healing on reconcile (auto re-ingest the missing IDs)* — a logic bug would just re-drop them and churn; the alarm (human signal) is the durable value, and #180 already fixed this class at the source.

**Out of scope.** Reconciliation for other activity sources (Whoop/Garmin) — the pattern generalizes but each is a separate opt-in; fixing the freshness/liveness checks to be completeness-aware beyond the interior-gap heuristic.

**Follow-up closed (2026-06-21, B3).** The `get_freshness_status` MCP tool — originally out of scope above as high-water-mark only — now carries the same interior-gap scan (`find_interior_gaps` + `DAILY_SOURCES_INTERIOR`, TD-14 parity with `freshness_checker_lambda`), surfacing `interior_gaps` / `interior_gap_count` so an interactive freshness read can no longer report a mid-window hole as green. Lands with the Stage-1 data-integrity batch alongside the `get_muscle_volume` completeness signal (B2a) and the anti-rotation/carry → Core classifier fix (B2b).

---

## ADR-093: Recovery-adaptive night-before authoring — tier-agnostic branches + freshness gate

**Status:** ✅ Active — 2026-06-21

**Context.** Routines are authored the night before but trained the next morning (Matthew's routine is wake → car → gym — **zero platform interaction possible** before training, and he won't invent on-the-fly audibles). Two failures on 2026-06-21: (1) a routine authored on a **stale/incomplete** `get_muscle_volume` read (it hadn't aggregated the latest session → called calves "lagging" when optimal, core "zero" when mis-mapped) — a wrong baseline before recovery even mattered; (2) the routine was **hard-stamped one night's `recovery_tier`**, so it couldn't adapt when he woke GREEN 95%, and he had no way to fix it in the car. Two axes miscalibrated on a sunk-cost session.

**Decision.** Author **tier-agnostic** and **freshness-gated**. The routine carries all three recovery branches; the morning selects one off the wrist.

- **Freshness/completeness gate (the headline).** `manage_hevy_routine action=draft` runs an authoring gate *first* and refuses to compile (`status=blocked_stale_inputs` + structured `gaps`) when an input lags the latest ingested session. It reuses the Stage-1 `get_muscle_volume` `completeness.stale` signal (ADR-092 class — completeness, not max-date recency) + the Whoop recovery high-water mark. `override_freshness_gate=true` is an explicit, discouraged escape hatch. *"Author on incomplete data and the branches are just well-dressed garbage. Gate first, branch second"* (Henning).
- **Tier-agnostic branches keyed to the Whoop band (67/34).** The `ideal` routine becomes the self-adapting carrier: an always-present session block (the safe default + the rubric + "use the lower of band/feel — feel only downgrades") leads the first exercise's notes, and per-lift top-set RPE branches (🟢/🟡/🔴) render on the primary compounds. **YELLOW is the default** when the morning signal is absent/ambiguous (E1/E2). **Subtract-only preserved:** GREEN is the authored ceiling, YELLOW/RED are defined subtractions, and `green ≥ yellow ≥ red` is invariant-tested.
- **Week-position / fuel / tissue context.** `training_context(target_date)` (consecutive-day streak, deficit state from `get_deficit_sustainability`, tissue ramp) **collapses the GREEN ceiling to "quality, not load"** late-week (≥5-day streak), on a deep deficit, or early in a novel-pattern ramp (Marcus + Iris) — so a motivated morning can't ego-add.

**Deploy footprint (deliberate).** The logic lives in the MCP package (`mcp/recovery_authoring.py`, pure/testable; wired into `mcp/tools_hevy_routine.py`) and renders into the **existing** exercise `notes` field with structured branches stashed in the **existing** `inputs_snapshot` — so v1 ships via `deploy_mcp_split.sh` with **no shared-layer rebuild**. The routine-IR / `hevy_compiler` modules are layer-resident; promoting `branches` to a first-class IR field + compiler rendering (so the autonomous Phase-3 cron path and a future overnight re-stamp inherit it) is a noted follow-up requiring a layer bump.

**Rejected / deferred.** *Overnight re-stamp Lambda* (pre-highlight the matching branch post-Whoop-sync) — deferred for v1 (Matthew's §8 lock: self-selection only); it must fail-open to the always-present branches if built. *Composite readiness as the branch signal* — rejected; branches key to the simple wrist band he can actually see at 5am, not a compute he can't. *Gate as Claude's discipline* — rejected; the gate belongs in the tool (Priya/Jin).

**Out of scope.** The autonomous cron authoring path (`hevy_routine_cron_lambda`) still emits the legacy ideal/floor pair — v1 targets the chat/MCP night-before authoring Matthew actually does; bringing the cron onto the branch model is the layer-bump follow-up above.

---

## ADR-094: Derived training-note signal layer — never mutate raw Hevy notes; notes overlay numbers, never overwrite

**Status:** ✅ Active — 2026-06-21 (Phase 1; private)

**Context.** Matthew writes freeform notes on individual Hevy exercises (first session 2026-06-20). Raw, the signal evaporates after one read — there's no structured, queryable, *progressive* view. The value a raw read can't serve cheaply: the **per-exercise arc across sessions** (cycling L10 → L18 → intervals) and **pain that must never be lost in a distill**. Mirrors the meal-grouping derived-projection pattern (derived projection, raw sovereign, deterministic-first, bounded LLM tail).

**Decision.** A derived **note-signal projection** over the untouched raw Hevy notes, keyed by exercise so the timeline is one Query, written on-ingest.

- **Extractor (deterministic-first, bounded Haiku tail).** `lambdas/training_notes.py` (pure core: rule-pass for numeric progression / equipment / logging-quirk / sentiment / form / limiter + the pain net) + `lambdas/training_notes_llm.py` (the semantic tail — Haiku, constrained JSON, **hash-cache** so an unchanged note never re-extracts, **monthly cap ~300** with fail-safe to deterministic-only). Both are layer modules — the on-ingest hook lives in `hevy_backfill_lambda` and the read tool + backfill in MCP.
- **Projection.** `pk = USER#matthew#SOURCE#training_notes#EXERCISE#<template_id>`, `sk = DATE#…#WORKOUT#<id>`; source label `training_feedback_loop`. Idempotent upsert by the stable sk. Correction overlay at `…#WORKOUT#<id>#CORRECTION` wins on read.
- **Read.** `get_exercise_notes(exercise|template_id, lookback_days)` MCP tool (#136) → the date-sorted arc + a prominent `pain_flag`.

**Invariants (tests enforce).** (1) Raw untouched — writes ONLY `SOURCE#training_notes`, a provenance assert refuses the raw Hevy pk. (2) Inferred + labelled — `confidence` + `extracted_by` on every signal. (3) **Notes overlay numbers, never overwrite** — `rpe_caveat` is a coach-read overlay; the extractor emits no raw RPE/load and never touches the workout. (4) Conservation — every non-empty note → exactly one record; on LLM failure keep `note_raw` + deterministic signals + `degraded:true`, never drop. (5) **Pain never missed** — a deterministic lexicon is authoritative for `pain_flag` (the LLM can add but never clear it) and elevates (insight + training-coach thread + the prominent read-tool flag). `burn`/`sore`/`tight` are excluded from auto-pain (Phase-0 red-team: "forearm burn" is muscular) → coach review path.

**Rest adherence (Phase-0 finding).** Hevy's performed-workout API records **no actual rest** (no per-set rest/timestamps) — confirmed at the raw payload. **Prescribed** rest is on the routine (`rest_seconds`, round-trips via `get_routine`) and tracked as data, but prescribing rest is a multi-factor coach judgment, never auto-set from recovery (see the rest/params-multi-factor guidance). Actual-rest changes are captured qualitatively via the note (`rest_adherence` signal).

**Out of scope (Phase 1 is private instrumentation).** Phase 2 — the loop-back into routine descriptions + cross-exercise pattern detection (n-floored ≥3, correlative) — is what justifies the build (Viktor's gate) but ships only after Phase 1 is eyeballed against real notes for ~1–2 weeks. `deviation` (pushed-vs-performed diff) ships as a tested pure function but its ingest wiring waits on a template_id↔movement_key map (the pushed IR keys by internal `movement_key`, the performed workout by Hevy `template_id`). No public/website surface.

---

## ADR-095: Privacy-clean traffic measurement — weekly digest from CloudFront access logs

**Status:** ✅ Active — 2026-06-27

**Context.** The v5 site goal is graded partly on **returnability** (docs/PLATFORM_NORTH_STAR.md), but the platform had no way to know whether anyone visited or came back — and the site's stated ethos is "no tracking cookies, no third-party analytics." The need (measure traffic) collided with the principle (don't track people). The two obvious instruments both fail the principle or the bar: a JS analytics tag (GA/Plausible) is exactly the third-party tracking the privacy page disavows; web push needs a permission prompt + per-visitor subscription state. Neither fits a no-tracking, single-owner site.

**Decision.** Measure from **CloudFront standard access logs** — the first-party request records the CDN already keeps — and aggregate them weekly into an email. `lambdas/operational/traffic_digest_lambda.py` (cron Mon 9 AM PT) parses the trailing 7 days into page views / unique visitors / returning visitors / top pages / external referrers and sends via SES. **No raw IP is ever stored, logged, or emailed:** a visitor key is `sha256(ip|ua)[:16]`, computed in memory only to count distinct/returning, then discarded; output is aggregate totals. Bots, assets, /api, /legacy, and non-200s are filtered. Logs land in a dedicated bucket `matthew-life-platform-cf-logs` (90-day lifecycle, RETAIN) with **BUCKET_OWNER_PREFERRED** ownership so CloudFront's log-delivery account can be granted the write ACL. The privacy page documents the practice verbatim.

**Why this honors the no-tracking claim.** Access logs are infrastructure telemetry the server generates regardless — not client-side instrumentation injected into the visitor's browser, no cookie, no cross-site identifier, no third party in the page. Hashing-then-discarding the IP means the digest can say "N distinct, M returned on a 2nd day" without the system ever retaining who they were.

**Alternatives rejected.** *Third-party analytics JS* — the exact tracking the site disavows. *Web push for re-engagement* — needs a permission prompt + stored per-visitor subscriptions (visitor state the site otherwise never keeps). *Storing IPs for richer cohorting* — violates the discard-immediately rule for marginal value. *An error alarm on the digest Lambda* — omitted by design (a weekly digest failing is low-stakes; the CF logs are retained so the next run still sees the window), consistent with the other `alerts_topic=None` operational Lambdas.

**Deploy.** Infra is CDK (`LifePlatformOperational`); enabling CloudFront standard logging on dist `E3S424OXQZ8NBE` → the bucket (prefix `cf/`) is a one-time manual step. Runbook: docs/SITE_UPLEVEL_PLAYBOOK.md. Tests: tests/test_traffic_digest.py (incl. an assertion that no raw IP survives parsing). Both shipped 2026-06-27 (#217).

---

## ADR-096: Coherence as a monitored property — the Self-Management & Coherence Program

**Status:** ✅ Active — 2026-06-29 (Phases 1–4 + precision pass shipped, #245–258)

**Context.** Every liveness signal the platform had (freshness, auth-health, error alarms, render/visual QA) proved a system was ALIVE but said nothing about whether it was RIGHT. A run of silent-incoherence bugs all passed those checks: coach predictions 100%-inconclusive for weeks, recovery rendered 30 on one surface and 86 on another, the experiment arc counting 7 weeks against the 3 the UI showed, `handle_predictions` returning all-zeros, and coaches serving a resting-HR of 53 when the canonical value was 64. The common shape: an *implicit* producer/consumer contract drifted, and nothing was watching the contract — only its liveness.

**Decision.** Make coherence a first-class, monitored property, in four phases.
1. **Detect** — a read-only `coherence-sentinel` Lambda (daily 10:45 AM PT) runs pure invariants (`lambdas/coherence_invariants.py`), each unit-tested by replaying a real past outage: prediction-health, computed-coherence, canonical-facts cross-surface agreement, endpoint non-degenerate shape, cross-surface count-agreement. It emits `LifePlatform/Coherence` → the `coherence-overall` digest alarm and persists a findings artifact to `s3://matthew-life-platform/coherence-log/`.
2. **Contracts** — kill the drift at the source: `measurable_metrics.py` (the extractor allowlist DERIVED from `METRIC_SOURCES`, so they can't diverge) and `canonical_facts.py` (one facts schema + units, with a producer-contract test asserting `daily_metrics_compute` writes every field). Coaches are grounded on, and the Sentinel checks against, the *same* extraction.
3. **Deploy hygiene** — a clobber guard in `sync_site_to_s3.sh` and `deploy/session_postflight.py` (layer uniformity, config drift, and — added after this program found the failure mode live — asset completeness).
4. **Self-healing eyes on content** — the remediation agent ingests the Sentinel's artifact as a triage signal; the taxonomy routes every coherence finding to a human-PR or needs-human bucket and **never** to auto-merge (a test enforces that no content path is on the auto-merge allowlist).

**Key sub-decision — the deterministic invariants drive the alarm; the LLM semantic pass is advisory.** The Sentinel also runs a budget-gated Haiku "does the narrative cohere with the facts" pass. It earned its keep (it caught the RHR-53 hallucination), but it proved too unreliable to *gate* a daily-emailing CloudWatch alarm: even with a tightened prompt it lists items it concludes are fine in its `issues` array and returns `coherent:false` on borderline variance. A permanently-red alarm is ignored — which would defeat the program. So `coherence-overall` fires on the deterministic invariant verdict only (which, after the precision pass, covers the egregious numeric contradictions with grounding-aware tolerance — the original RHR-53 is caught deterministically now); the semantic read stays in the digest + a `semantic_incoherent` advisory flag for a human/agent to weigh.

**Precision over recall (for the alarm).** The deterministic `facts_agreement` check flags a metric only when a wrong value is cited AND the canonical value is cited nowhere in the narrative — so a grounded trend ("recovery dipped from 86 to 30") doesn't false-fire. The coach-side analyzer's self-correction (`_hard_canonical_contradictions` → regenerate-once) uses the same grounded-anywhere logic, so detection and grounding agree.

**Alternatives rejected.** *Let the semantic pass drive the alarm* (#252's original wiring) — too noisy; superseded by #257. *Backfill the 296 legacy dead predictions* — keyword-inference on old prose mis-directs ~⅓; let them expire. *Widen the auto-merge allowlist to let the agent fix content* — content correctness is exactly what must stay human-reviewed; the whole safety model is that the agent (read-only role) only opens PRs and a deterministic gate merges a narrow non-content allowlist. *Fix coach fabrication to zero* — it's a stochastic LLM frontier; the program bounds it (egregious cases self-correct + trip a precise alarm; soft cases are advisory) rather than claiming elimination.

**Deploy.** All shared modules (`coherence_invariants`, `measurable_metrics`, `canonical_facts`) are bundled with the `lambdas/` asset, NOT the layer (no layer dance). CDK: `LifePlatformOperational` (the Sentinel + IAM) and `LifePlatformMonitoring` (the alarm). See `handovers/HANDOVER_LATEST.md`, the `reference_cdk_asset_staging_glitch` operator note, and `docs/REMEDIATION_TAXONOMY.md`. Shipped across #245–258 (2026-06-28/29).

---

## ADR-097: Two GSIs for the reading domain — the first GSIs on `life-platform` (amends ADR-005)

**Status:** ✅ Active — 2026-06-29 (Mind pillar Phase A)

**Context.** The new reading/Mind domain (`docs/SPEC_READING_MIND_2026-06-29.md`) has access patterns that the single composite key cannot serve without a table scan: "everything I'm currently reading / queued" (by status, not by a known pk), "reading-session history over a date range" (across all books), and the daily "recall prompts that are due now" sweep (a time-ordered slice of a sparse subset). ADR-005 ("No GSI") was decided for a workload where every query was `pk = USER#…#SOURCE#X AND sk BETWEEN d1 AND d2` — true then, not true for reading.

**Decision.** Add exactly two Global Secondary Indexes to `life-platform`, additively. This **amends ADR-005** (which stands for every other domain — GSIs remain the documented exception, added only with an ADR):
- **GSI1 — recall due (SPARSE).** `GSI1PK="RECALL_DUE"`, `GSI1SK=<nextDue iso>`. Only `RECALL#` prompts with an active `nextDue` carry the GSI1 attributes, so the index holds just the un-answered prompts; the daily EventBridge sweep is `query GSI1 where GSI1SK <= now` — never a scan. Answering/retiring a prompt removes the attributes, dropping it from the index.
- **GSI2 — reading state/time.** `GSI2PK="READING_STATUS#<status>"` (on `READING#/STATE` rows) or `"READING_SESSION"` (on `SESSION#` rows); `GSI2SK=<iso>`. Serves current-reading, the queue, and history-by-date.

Both project `ALL` (reading items are small and the read paths want the full record). Sparseness is intrinsic — only items that carry the index pk attribute participate — so GSI1 stays tiny regardless of library size.

**Mechanism — CLI, not CDK (important).** The `life-platform` table is deliberately **not** CDK-managed (`core_stack.py` holds a read-only `from_table_name` lookup; the table is a stateful resource). GSIs therefore cannot be added through a CDK construct. They are created with `aws dynamodb update-table` via `deploy/deploy_reading_gsis.sh` (idempotent; one GSI per `UpdateTable`, each an online backfill that leaves the table readable/writable throughout). This is consistent with the platform norm that deploy steps are scripts the operator runs. No `core_stack.py` change is needed or possible for the GSIs.

**IAM.** No role change: the existing table grants already include `…/index/*` (`role_policies.py`), so consumers can query the new GSIs as soon as they exist. The Phase A cover-pipeline Lambda's policy mirrors that pattern.

**Cost.** Two on-demand GSIs with ALL projection on a single-user, ~tens-of-MB table is a few cents/month plus write amplification on reading writes only (a handful per day). Negligible against the $75 ceiling.

**Taxonomy.** All reading records are `CROSS_PHASE` (`phase_taxonomy.py`): a person's library and reading history is durable identity data that must survive an experiment reset — never tagged, never wiped, never phase-filtered (a test asserts the new families classify).

**Alternatives rejected.** *Keep ADR-005 absolute and scan* — the recall sweep and status/queue views would scan the whole table daily as the library grows; the sparse GSI1 is exactly the pattern DynamoDB sparse indexes exist for. *Model reading under `USER#…#SOURCE#reading` with date sks* — loses the by-status and global-by-date access without a GSI anyway, and fights the spec's entity design. *Add the GSIs via a new CDK-managed table* — the table is shared, live, and stateful; re-homing it is far riskier than an additive online index add.

**Deploy.** `deploy/deploy_reading_gsis.sh` (GSIs) then `deploy/deploy_reading_data.sh` (`cdk diff` → `cdk deploy LifePlatformOperational` for the cover-pipeline Lambda). No layer rebuild (reading modules bundle with the `lambdas/` asset). See `handovers/HANDOVER_LATEST.md`.

---

## ADR-098: Content-hash the full JS module graph, not just HTML references (extends ADR-039)

**Status:** Active
**Date:** 2026-07-03

**Context.** ADR-039 established content-hashed CSS/JS filenames served `max-age=31536000, immutable`, with `sync_site_to_s3.sh` computing an 8-char hash per file and rewriting references. But it rewrote references **only in `*.html`**. The v5 site is ES modules that import each other by absolute URL (`import ... from "/assets/js/charts.js"`), and those **intra-module import statements were never rewritten** — they kept pointing at the unhashed filename, which was *also* uploaded (`max-age=86400`, mutable, same name forever) as ADR-039's "fallback for dynamic loads."

The result: the entry module (e.g. `evidence.js`) was hashed and immutable, but the dependencies it imported (`charts.js`, `sigils.js`, `icons.js`, `ask.js`) resolved to mutable, 24h-cached URLs. When a deploy changed an entry module **and** a dependency together (as #260's graphic-identity change did), a returning browser could pair a **fresh hashed entry module with a stale cached dependency**. An ES module graph fails atomically — one bad/mismatched import throws at load time and the whole module never executes — so the page rendered only its static HTML shell with all JS-populated content blank ("the frozen page"). A hard reload bypassed the HTTP cache and fixed it; the stale copy survived a browser restart, so it reproduced reliably. See INCIDENT_LOG 2026-07-03 (P3).

**Decision.** Hash the **entire CSS/JS module graph** and rewrite **every** reference — HTML `<link>`/`<script>`, intra-module `import` statements, and CSS `@import`/`url()`. New helper `deploy/hash_site_assets.py` (replacing the inline bash hashing in `sync_site_to_s3.sh`):
- Builds the module dependency graph from the original file contents (the `/assets/(js|css)/name.ext` reference regex).
- Hashes **leaves-first** via a topological sort (raises on an import cycle): a dependency's hash is finalized before any dependent is hashed, so a dependent's rewritten content — and therefore its own hash — already reflects the hashed dependency URL. This is textbook cache-correct hashing.
- Writes `name.<hash>.ext` alongside each file (immutable upload) and rewrites the original in place too (kept as the short-cache fallback), so both copies are internally consistent.
- Skips `legacy/` (served verbatim with unhashed assets, per ADR-071).

Every asset URL is now content-hashed and immutable, so an entry module pins the exact hashed bytes of every transitive dependency. **Version skew across the module graph is structurally impossible** — the failure mode ADR-039 left open is closed.

**Why the graph approach over a hardcoded dependency list.** The helper discovers the graph from the source each deploy, so a newly-added import (e.g. current `evidence.js` imports an `ask.js` module that didn't exist when the bug was diagnosed) is hashed automatically with no script change. A hardcoded list would silently miss it and reintroduce the skew.

**Alternatives considered.**
- **Network-first / short-TTL on the mutable-named assets** (the minimal fix): shrinks the skew window from 24h to ~5 min but doesn't eliminate it, and keeps the SW's cache-first-on-"immutable" assumption technically false. Rejected in favor of the structural fix.
- **A bundler (esbuild/Vite)** that emits one hashed bundle per entry: eliminates the graph but adds a Node build dependency and toolchain — against the platform's no-build-framework norm (ADR-071). Overkill for ~10 modules.

**Outcome.** Deployed 2026-07-03 and live-verified: `/data/` and `/coaching/` serve a fully-hashed, self-consistent, immutable module graph (the shared `sigils` hash is byte-identical across pages), 0 dangling references, 0 unhashed HTML references, `version.json` build == `sw.js` VERSION. The service worker (`site/sw.js`) needs no change — its cache-first-on-immutable strategy is now genuinely correct for these URLs. The unhashed-original upload remains for true runtime `document.createElement('script')` loads (ADR-039's `countdown.js` case) but is otherwise dead weight, a candidate for later cleanup.

---

## ADR-099: GitHub Issues become the single source of truth for forward work (supersedes BACKLOG.md's role)

**Date:** 2026-07-03 · **Status:** Accepted

**Context.** `docs/BACKLOG.md` declared itself "single source of truth for everything not done," but the 2026-07 platform + product review's reconciliation found it ~27% wrong: 29 of 107 claimed-open items had already shipped, one "blocked" item (B-01) had been resolved for two weeks, and several time-gates had silently elapsed. A hand-maintained ledger drifts because closing an item is a separate manual act from shipping it. The review produced 83 verified findings + 41 verified-open ledger items that needed one unified, ranked home.

**Decision.** Forward work lives as **public GitHub issues** on `averagejoematt/life-platform` (the build-in-public wedge makes the backlog itself content):
- **Epics** (`type:epic`, `[EPIC]` title): outcome hypothesis, a leading measure, loop pillar, wedge alignment, definition of done, and a task-list of story issues.
- **Stories** (`type:story`): a user story, 3–5 verifiable acceptance criteria, evidence links, and an auditable score line.
- **Ranking:** hard gates first (the 185 test · the build cap · privacy absolutes · the honesty moat — a failure is parked in the review report, never filed). Then `Score = (Impact × Confidence) / Effort`, Impact = 0.35·returnability + 0.25·credibility-moat + 0.20·monetization-readiness + 0.20·durability (each 1–5); Confidence 0.5/0.75/1.0; Effort S=1 M=2 L=4. Score terciles map to the **Now / Next / Later** milestones. PM overrides are allowed and must be recorded in the issue (e.g. a live reader-facing defect outranks the effort denominator).
- **Idempotency + audit:** `docs/reviews/BACKLOG_MANIFEST_2026-07.json` records item-id → issue number → score.
- **Exclusions:** gated/won't-do/owner-capture items are NOT filed — they live in the review report's parked register, referenced by one `parked-register` issue.

**Maintenance convention (the anti-drift mechanism):** (1) a PR that ships a story carries `Fixes #N` so shipping closes the ledger entry atomically; (2) `/uplevel` Phase 0 seeds from `gh issue list --milestone Now`, never from a static doc list; (3) a monthly ~10-minute triage sweep closes-or-demotes stale issues; (4) new work enters as an issue or not at all. `docs/BACKLOG.md` is frozen as a historical archive with a banner.

**Alternatives considered.** Keeping BACKLOG.md with stricter discipline (rejected: discipline is what failed — the fix must be structural, and `Fixes #N` closes issues mechanically); GitHub Projects v2 board (deferred: milestones + labels are CLI-scriptable and sufficient; a board view can be layered on later without migration).

**Outcome.** 12 epics + 74 stories + 1 parked-register issue filed 2026-07-03 from the review (83 verified findings + 41 verified-open ledger items, duplicates merged), every body privacy-passed before creation.

## ADR-100: The budget ceiling protects readers — the public ask endpoints degrade LAST

**Date:** 2026-07-03 · **Status:** Accepted · **Amends:** ADR-063

**Context.** June 2026 closed at $79.80 — the first breach of the $75/month all-in ceiling — driven by dev-session AI re-runs, not production traffic. The review (finding cost-01) surfaced a shape problem underneath the number: ~$35/month of the ceiling is fixed non-AI overhead at zero readers, and the automatic budget defense turned off the PUBLIC ask endpoints at tier 2 (85% of budget) while internal content generation kept running. The first casualty of growth would have been the exact feature that converts a curious visitor into a returning reader — backwards for a platform whose north star is returnability.

**Decision.**
1. **The sacrifice order inverts: readers degrade last.** `website_ai` moves from tier 2 to tier 3 in `budget_guard._FEATURE_CUTOFF`. The degradation ladder is now: tier 1 pauses the heavy internal daily AI (coach narratives, ensemble); tier 2 additionally pauses the weekly chronicle (with the Panel podcast in lockstep); tier 3 — the hard stop — pauses everything, including the ask endpoints, which return their existing honest "paused for the rest of the month" message (never a degraded fake answer).
2. **The ceiling stays $75 for now, chosen on purpose rather than inherited.** The number is re-affirmed with unit economics attached (below), and a revisit trigger: **when the traffic digest shows ≥50 ask-questions/week sustained for a month, or ≥100 confirmed subscribers, re-size the ceiling as a product cost, not an instrument cost.**

**Unit economics (the per-reader sketch, 2026-07 Bedrock Haiku pricing ≈ $1/MTok in · $5/MTok out).** One `/api/ask` answer ≈ 3k in + 600 out ≈ **$0.006**. One full-board convene (8 personas × ~600 in + 300 out, system blocks prompt-cached) ≈ **$0.017**; the default trio ≈ $0.006. The 5/hr/IP rate limit caps a single visitor at ~$0.09/hour worst-case. At 100 board questions/day — far beyond current traffic — the month costs ~$50, which is the point of the revisit trigger: that problem is called growth, and the ceiling gets re-sized deliberately when it arrives.

**What this does NOT change.** The $75 AWS Budget alerts, the cost governor's tier computation, the tier-3 `BudgetExceeded` chokepoint in `bedrock_client.invoke()`, and the daily brief's protect-longest position all stand. Dev-session AI attribution (the actual June driver) is separate work (#366).

**Verification.** `tests/test_budget_guard_ladder.py` simulates tier escalation and asserts the ask endpoints still answer at tier 2 (where they previously went dark), every internal narrative feature is off at or before tier 2, and tier 3 blocks everything.

## ADR-101: Distribution before monetization — no paid-product work until an audience trigger

**Date:** 2026-07-03 · **Status:** Accepted · **Extends:** ADR-078 (the three-wedge strategy)

**Context.** The 2026-07 review measured the audience honestly: **~1 confirmed subscriber** (the other 425 records were the canary's synthetic signups). Every paid form of the build-in-public wedge — a template repo, a guide, a paid tier — requires an audience that does not exist yet, and building the paid shell first is the highest-fidelity avoidance pattern the personal board already warned about (SUMMIT 2026-06-07, the Viktor/Reeves dissent). Meanwhile the review found the distribution plumbing itself broken at every stage (RSS on a dead feed, chronicle invisible to search, the day-2 email failing since launch). The honest first-dollar path runs entirely through distribution and the transformation itself.

**Decision.**
1. **No paid-product work — pricing, checkout, paid tiers, paid artifacts, sponsorship outreach — until a concrete trigger fires:** EITHER **100 confirmed (human) subscribers** OR the **wedge-A gate** (~30 lb visible progress + a ~6-month sustained list) per ADR-078, whichever comes first. "Confirmed subscribers" means the post-cleanup real-human count (#355), not raw records.
2. **The interim routing rule:** any monetization-flavored proposal — from a session, an agent, a review, or enthusiasm — is either (a) converted into its distribution equivalent (make the thing findable/followable/shareable) or (b) declined with a pointer to this ADR. It is never parked as "later monetization" — that re-opens the debate this record closes.
3. **What continues freely:** wedge-B *content* (writing, the method pages, the public repo story, the agents showcase) — the capped, documents-what-exists work ADR-078 already sanctions — and all audience-accrual mechanics (subscribe, RSS, share kits, SEO).

**Revisit trigger.** The trigger firing (either arm) re-opens monetization as a deliberate session with this ADR and ADR-078 on the table — not as a side effect of a feature branch.

**Consequences.** The backlog's parked register points here as the single written rationale for every parked monetization item; future sessions route around the question instead of re-litigating it; the growth epics (#338, #339) become the only sanctioned path toward the first dollar.

## ADR-102: Single-table DynamoDB, chosen on purpose — keep it, do not migrate (ER-08)

**Date:** 2026-07-03 · **Status:** Accepted · **Relates:** ADR-005 (single-table), ADR-097 (the two reading GSIs)

**Context.** Everything lives in one DynamoDB table (`life-platform`, `pk USER#matthew#SOURCE#{source}` / `sk DATE#…`). The choice was never recorded, and internal notes justified revisiting it with a premise the 2026-07 review verified to be FALSE: the analytics do not scan the table. The correlation engine runs bounded, paginated `Key`-condition queries over date windows (e.g. `weekly_correlation_compute` fans out per-source `fetch_range` queries over a 90-day lookback) and precomputes results; the codebase contains **exactly one `.scan()`** — in `delete_user_data_lambda` (data deletion, where a scan is the correct tool). Measured shape: ~42 MB, ~31.6k items, PAY_PER_REQUEST, PITR on. Storage and read cost are a rounding error against the $75 ceiling.

**Decision. Keep single-table DynamoDB. Do not migrate.** The model fits the access pattern this platform actually has — per-source, per-date-range reads feeding Python compute — and five more years of daily data (~×5 item growth) changes nothing material about that fit.

**The honest costs (named so nobody is surprised by them):**
1. **Query expressiveness.** Cross-source joins are hand-rolled in Python over a multi-source window fan-out. Every "correlate X with Y" is N queries + an in-memory join, not one expression. This is a real tax on exploratory/ad-hoc analytics — the MCP query layer partly exists to compensate.
2. **Single-tenant key design.** `USER#matthew` is hardcoded throughout the key schema and much of the code. Any multi-reader/multi-tenant pivot (the shelved wedge C) is a re-key, not a config change. That is an accepted consequence of ADR-078 shelving wedge C, not an oversight.
3. **Out-of-IaC config surface.** The table is imported by name in CDK; its GSIs/PITR/billing/TTL live outside code review (tracked separately as backlog #371/#379 — the managed-where ledger + drift sentinel).

**Revisit trigger (concrete, not "someday"):** introduce a READ-SIDE analytical layer (DuckDB/Athena over the S3 `raw/` mirror — alongside DynamoDB, never replacing it) only when ad-hoc analytics are a demonstrated recurring need: **three or more working sessions in one quarter blocked on a question the query layer cannot express**. A one-query spike (`spikes/er08_duckdb_readside/`) is the sanctioned sizing tool if the trigger nears. Docs claiming the correlation engine "scans the table daily" are corrected as of this ADR.

## ADR-103: The complexity-posture ledger — every subsystem carries its frame (ER-07)

**Date:** 2026-07-03 · **Status:** Accepted

**Context.** A one-person platform has accumulated systems at home in a mid-size org: experiment-phase machinery, three AI boards, a self-healing agent, a coherence sentinel. The 2026-07 review's most consistent theme was "subtract more than add" — but subtraction needs recorded verdicts, or every session re-litigates posture per subsystem. This ledger assigns each major subsystem one of three postures: **load-bearing** (the product or its safety depends on it), **portfolio** (justified as a publicly-demonstrated pattern — the ADR-078 wedge-B frame — even if utilization is low), or **retire-candidate** (named removal path or trigger, never an open-ended "someday").

**The ledger (2026-07-03):**

| Subsystem | Posture | Notes / trigger |
|---|---|---|
| Phase machinery (ADR-077 taxonomy, restart pipeline) | **Load-bearing** | The experiment's reset semantics; coverage-asserted |
| Coherence sentinel + canonical_facts/measurable_metrics contracts | **Load-bearing** | The honesty moat's enforcement layer |
| The 8-coach board + stance engine + orchestrator | **Load-bearing** | The COACHING pillar — the product |
| Budget governor + budget_guard | **Load-bearing** | The $75 ceiling's enforcement (ADR-063/100) |
| Freshness / ingest-liveness / reconciliation detectors | **Load-bearing** | The silent-failure coverage class |
| Character engine + sheet | **Load-bearing** | Public flagship page since #326–#328 |
| Deploy guardrails (clobber guard, postflight, layer gate) | **Load-bearing** | Each earned by a real incident |
| Weekly Panel podcast pipeline | **Load-bearing** (STORY) | Currently dark — revival is backlog #374, not retirement |
| Reading pillar (2 GSIs, tools, page) | **Load-bearing (small)** | The owner's real instrument; Phase-E stays finish-gated |
| MCP server | **Load-bearing but overweight** | The instrument itself is core; ~105 unused tools are the retire-candidate INSIDE it (#398) |
| Remediation agent (auto-merge apparatus) | **Portfolio** | Safety design is exemplary; ~zero output at current scale. #396 decides: earns `auto` or returns to `shadow`. Becomes load-bearing only if it ships real fixes monthly |
| Personal/Product deliberation boards (BOARDS.md summits) | **Portfolio** | Decision-quality tooling demonstrated in public; no runtime footprint |
| AI-vision QA (Bedrock semantic screenshots) | **Load-bearing** | Gating CI since 2026-06-05 |
| Stats/forecast machinery (stats_core, deterministic hypothesis tester, calibration ledger) | **Load-bearing** | Added 2026-07-04 (ADR-105, epic #525) — the credibility moat's enforcement layer for the platform's own science |
| `personal-baselines` monthly compute + `personal_baselines.py` (percentile bands from own variance) | **Load-bearing** | Added 2026-07-05 (#543, ADR-105 rule 4) — replaces hand-set readiness/momentum cutoffs with bands over Matthew's own distribution; floor-guarded (thin data → today's constants). Retire only if the platform stops making banded verdicts |
| `/legacy` preserved v3 site | **Portfolio (archive)** | Zero maintenance; never linked; retire only if storage/privacy cost appears |
| ~105 unused MCP tools + the 64-entry orphan allowlist | **Retire-candidate** | Path: the #398 AUDITED_AT ratchet prune, batches of 10–20 |
| apple_health XML import path (`apple-health-ingestion` lambda) | **RETIRED 2026-07-04** (#474/D-5) | Latent full-replace clobber of HAE-merged records; its S3 trigger never existed. Lambda + role deleted; `backfill/archive/backfill_apple_health.py` hard-guarded. HAE webhook is the sole apple_health writer; any future XML import must be rewritten onto `merge_day_to_dynamo` |
| `sleep-reconciler` / `sleep_unified` unified-sleep merge | **RETIRED 2026-07-05** (#487/A-2/A-3, ADR-113) | The per-field merge read record fields that never existed (stored the Whoop record + one Eight Sleep score, not the promised best-source-per-field merge) and ran 1–2 nights stale, mislabelling the public `/data/sleep` "night of" header. Zero compute consumers; never in this ledger. Lambda + EventBridge rule + IAM role + `/api/sleep_reconciliation` + the front-end panel removed; the header date now sources from live `/api/sleep_detail as_of_date`. Orphan `sleep_unified` DDB partition kept (reclassed SYSTEM_STATE in phase_taxonomy so reset traversal still holds). **LifePlatformCompute needs a deploy** to drop the live function |
| Eight Sleep **bed-temperature** pipeline + its 5 consumer surfaces | **RETIRED 2026-07-05** (#489/A-4, ADR-118) | The `/v2/users/{id}/intervals` fetch 404'd every run (135×/week) and silently swallowed it; no `bed_temp_*` written for 4+ months. Removed the dead fetch, the `get_sleep_environment_analysis` MCP tool (entirely a temp optimizer), the `/data/sleep` environment chart + `sleep_detail` temp fields + the A3 corr card, the chronicle email temp lines, and the AI/coach/validator dead-field reads. Reactivation lead recorded in ADR-118 (read temp off the working `/v1/trends` `sleepQualityScore.tempBedC`). The rest of Eight Sleep (staging/HR/HRV/restlessness) is untouched and still load-bearing |
| `chronicle-podcast` season-1 lambda (unscheduled zombie) | **Retire-candidate** | Trigger: delete after one further back-catalogue re-render need-window (2026-Q3 review) |
| `hevy-webhook` FunctionURL lambda (parked — Hevy has no webhooks) | **Retire-candidate** | Trigger: Hevy ships webhooks, else remove at the 2026-Q4 review |
| State of Mind subsystem (HAE How-We-Feel → `som_*` on apple_health → 5 consumer surfaces) | **Kept / load-bearing-pending-data** (was retire-candidate lean, D-6) | ADR-121 (#507): owner chose to restart the How-We-Feel logging habit, not prune. The machinery is intact and, post-#507, correctly keyed to the apple_health partition; the only gap is the manual daily-logging habit. Trigger flips to retire only if the habit does not resume by the 2026-Q4 review |

**The standing rule.** Any NEW enterprise-pattern infrastructure must name its frame — load-bearing (what product/safety need), portfolio (what pattern it demonstrates publicly), or it does not land — in its PR description or ADR. "It would be cool to have" is not a frame.

**Maintenance.** Posture changes are one-line edits to this table with a dated note; the quarterly review re-reads it. Referenced from the docs index so sessions consult it instead of re-litigating.

## ADR-104: Honest numbers everywhere — behavioral-absence semantics + the grounded-generation gate

**Date:** 2026-07-03 · **Status:** Accepted

**Context.** Two believability failures shared one root — the platform could say things the data didn't support. (1) The character sheet showed every pillar at level 13 after 20 days of near-total disengagement: `_weighted_pillar_score` scored missing data as neutral 50 (blending thin data toward 50), so every pillar's EMA target sat ≈50 ≫ the post-reset level 1 and climbed +2 every 3 days in lockstep — inactivity was invisible and the level-down path unreachable. (2) The AI-narrative defenses were wildly uneven: the observatory experts were grounded + self-correcting, but the V2 daily coach render (the highest-traffic coach surface) injected hard-coded goals with zero deterministic number gate; `/api/ask`, `/api/board_ask`, the chronicle, insights and digests were similarly ungated, and the ai_output_validator ±25% numeric check was a no-op at 12 of its 13 call sites (nobody passed `health_context`). A read-only shadow sweep measured the cost: **11 hard canonical contradictions in 112 stored V2 narratives over 14 days (~10%)** vs 0 in the gated field notes.

**Decision — one principle, two arms.** *Numbers are earned deterministically; the LLM only narrates them* (ADR-062 extended to its logical end).

**Arm 1 — the character engine (v1.2.0):**
- **Behavioral absence = 0, not neutral.** Components flagged `behavioral: true` in `config/character_sheet.json` (habit compliance, journaling, nutrition logging, training frequency/zone2/diversity) score 0 at full weight when absent — an unlogged habit is a miss. *Measured* components (device readings) keep the confidence blend — a sensor gap is not a failure. Sick/travel days keep the existing freeze.
- **Coverage gate:** a day below `leveling.level_change_min_coverage` (0.5) carries no leveling signal in either direction — thin data can never climb a level, and no-data pillars freeze (shown as "held") instead of crashing.
- **Raw-day gate:** a level-up requires the day's own raw score to be at the new level — the EMA sets the target, but you climb only on days you actually performed (kills post-quit climbing on EMA momentum).
- **Graduated step bands** (`level_step_bands`: >25→3, >10→2, else 1, applied symmetrically) so pillars converge to what the data earns instead of marching at one shared pace.
- **Provenance, computed never narrated:** per-pillar `drivers` (top/dragging/absent/no_data) + `data_coverage` + `coverage_hold` flow engine → DDB → `/api/character` → per-pillar "why" lines and a presence-wired quiet-stretch beat on `/data/character/`. The mechanics copy and "The math" prose interpolate the new rules from the live config.
- History is **recomputed from genesis** after deploy (`deploy/restart_character_rebuild.py --apply`) so the page is believable immediately; `scripts/character_simulate.py` is the read-only tuning harness (it also caught a real field-mapping bug: the engine read pre-v2 Whoop field names, leaving sleep — the best pillar — permanently below the coverage floor).

**Arm 2 — the grounded-generation gate (`lambdas/grounded_generation.py`, layer + bundled):**
- One pure module composing the proven pieces: `authoritative_facts_block()` (the analyzer's exact wording), `grounding_findings()` = grounding_guard's canonical contradictions **plus an er03-style allow-list number gate** (every number in the output must appear in the input ∪ facts — this kills "climbed from X to Y" fabrication because the invented endpoint isn't in anything the model was given; small counts/durations/years are benign), and `regen_once()` (the keep-if-strictly-improved harness extracted from the analyzer).
- **Retrofitted:** the V2 coach render (canonical facts injected + gate + regen-once, fail-soft), `/api/ask` (gate + one regen, then an honest fallback — reader-facing is fail-closed), `/api/board_ask` (gate, no regen — 6 paid calls — in-voice refusal on findings), and the analyzer (adopts the shared harness + gains the allow-list).
- **The dormant validator woke up:** `validate_ai_output` auto-loads canonical facts as `health_context` when none is passed (cached, fail-soft, `AI_VALIDATOR_AUTOLOAD=off` kill-switch keeps the unit suite hermetic) — the ±25% check is now live at every call site.
- **Permanent measurement:** the Coherence Sentinel's facts pass now also reads the V2 coaches' served `OUTPUT#` narratives (fresh-only, avoiding day-boundary skew); `scripts/grounding_shadow_sweep.py` re-measures the per-surface fabrication rate for before/after comparison.

**The absence-policy audit (per-engine verdicts).** "Missing data = neutral" is *correct* for `compute_readiness` and `adaptive_mode` (their inputs are device readings; a gap is not a failure, and email-tone should not punish a sync lag) and was *wrong* for the character sheet (its behavioral components measure the owner's actions). Verdict recorded here so it isn't re-litigated: readiness/adaptive keep neutral-on-missing; character distinguishes behavioral (0) from measured (neutral); presence/engagement_core already narrates the gap and is the honest voice the character page now joins.

**Honest residual.** The allow-list closes the *numeric* fabrication class deterministically. Trend claims whose endpoints all appear in the input, and qualitative embellishment, remain prompt-rule + advisory-semantic territory (the Sentinel's Haiku pass stays advisory). field_notes keeps its own dict-shaped regen flow (already on the shared guard); the STANCE# writer gate is a named fast-follow.

**Consequences.** The character page tells the truth under disengagement (differentiated levels, visible down-levels, frozen unknowns, per-pillar "why"); every persisted narrative surface now has a deterministic number defense with a measured baseline (V2 ~10% → expected ≈0 for the contradiction class); a reader can never be served a number the platform can't trace to its own data. Costs: one extra generation call only when a draft fails the gate; layer bump (grounded_generation, canonical_facts, flat-copied grounding_guard).

## ADR-105: The rigor bar — uncertainty on every claim, every forecast graded, deterministic before narrative

**Date:** 2026-07-04 · **Status:** Accepted

**Context.** The 2026-07 intelligence review (epic #525) found the analytical layer honest in intent but thin in method: the hypothesis engine is branded "scientific method" yet contains no math (testing is a Haiku verdict over 7 daily rows, promotion is 3 consecutive subjective votes, confidence is LLM-self-assigned and never calibrated); daily series are treated as i.i.d. everywhere, so even the one surface with real p-values + BH-FDR is anticonservative; `pearson_r` exists in ≥3 copies with three different min-n; no user-facing claim carries an interval; every threshold is hand-set. Each of these is fixable per-story, but without a recorded posture every session re-litigates how much rigor is "enough" — the exact failure mode ADR-103 exists to prevent. This ADR records the bar once, early in the epic-A sequence, so E-A PRs cite it instead of re-arguing it.

**Decision — four standing rules.** ADR-062/104's principle (*numbers are earned deterministically; the LLM only narrates them*) extended to the platform's own science:

1. **Every user-facing statistical claim carries its uncertainty and sample size — or an explicit "descriptive only" tag.** A correlation without a CI and effective n, a projection without an interval, a "significant" without a corrected p is not shippable. Where the math genuinely doesn't apply (a raw count, a min/max, an anecdote), the surface says descriptive, not scientific.
2. **Every forecast or prediction the platform emits enters the calibration ledger and is graded.** No prediction surface may be write-only: if the platform says "likely", a later row records whether it happened, and the calibration scoreboard reads that ledger. Ungraded prediction features do not land.
3. **An LLM verdict about data is always preceded by a deterministic computation it narrates.** The hypothesis-v2 pattern: the test spec is frozen at creation (pre-registration), the effect size + CI are computed in Python, the verdict is a deterministic comparison — Haiku writes prose about a decision already made, never the decision. This is ADR-104's grounded-generation arm applied to inference rather than narration.
4. **New thresholds derive from personal variance — or document why not.** Percentile bands over Matthew's own distribution beat hand-set cutoffs (a 40-point readiness floor means nothing if his p10 is 55). Population-derived constants (ACWR zones, clinical lab ranges) are legitimate but must say so where they're used.

**Statistical floor (what "deterministic" means here).** One shared, tested module (`lambdas/stats_core.py`, story #529) is the only sanctioned implementation: a single `pearson_r`, one p-value, moving-block-bootstrap CIs, autocorrelation-corrected effective sample size (AR(1)/Bartlett), BH-FDR for families of tests. New stats code imports it; adding a parallel implementation requires an ADR. Daily physiological series are autocorrelated — effective n, not raw n, feeds significance.

**Complexity posture (the ADR-103 row, recorded here).** The stats/forecast machinery this epic adds — `stats_core`, the deterministic hypothesis tester, the calibration ledger — is **load-bearing**: it is the enforcement layer of the credibility moat, exactly as the coherence sentinel is for narrative honesty. It is not portfolio; if the platform stops making statistical claims, the machinery goes with them, not before.

**Consequences.** E-A PRs (#529–#543) reference this ADR instead of restating posture; the methods page (story #538) renders these rules as the public methodology; reviewers can red an unlabeled point estimate on sight ("where's the interval?") without a per-case debate. Cost: near zero — all of it is deterministic Python inside the existing compute cadence (ADR-063 safe), and the narrative layer gets *cheaper* where verdicts stop being LLM calls.

## ADR-106: Coach portraits — commissioned engraved identity

**Date:** 2026-07-04 · **Status:** Accepted (program); every portrait batch stays behind the contact-sheet gate below · **Extends:** ADR-040 · **Amends:** DESIGN_SYSTEM_V5 §8 (adds §8.7) · **Story:** #585 (epic #576)

> **Amendment 2026-07-05 (pilot approval, #587):** the sanctioned style moved from engraved
> stroke-only to **flat-vector character illustration** (shape language, per-recipe colour
> palettes incl. flat skin tones — runbook §1 as amended). §2's "stroke-only contours + one
> accent layer" reads accordingly: ink contours over validated flat fills, accent = the coach
> channel. Everything load-bearing here — the AI-gen boundary, provenance, the human gate, the
> photoreal NO-GO, disclosure — is unchanged.

**Sign-off.** Matthew authorized shipping this ADR in-session 2026-07-04 ("work through all open issues tagged to fable", with merge + deploy permission granted for the session). The hard taste gate — contact-sheet approval before any portrait ships to a live page — remains explicitly and solely his (#587); this ADR does not pre-approve any artwork.

**Context.** The coach cast (ADR-040: openly-fictional advisors, never real public figures) is rendered everywhere by deterministic geometric sigils (§8.2). Three standing rules were written to protect the truthfulness moat, and none of them contemplated stylized persona illustration: DESIGN_SYSTEM_V5 §8 says "no raster, no AI image gen" (written against glossy decoration and version-skewed binary assets); SS-11 rejects people-images fail-closed (written against *photographs of real humans* landing as editorial covers); PG-14 recorded NO-GO on photoreal (written against synthetic photorealism of *Matthew*, an honesty + privacy bar). The portrait program (epic #576) wants engraved, code-animated, openly-fictional bust illustrations for the coaches — which violates none of those rules' *reasons* but reads as violating their *letters*. Without a drawn line, either the program can't start or, worse, it starts and then drifts past the original protections. This ADR draws the line exactly.

**Decision.**

1. **AI image generation is permitted only as a one-time commissioning tool, only for openly-fictional personas** (the ADR-040 cast). It may produce *reference candidates* during a commissioning session. A generated raster is never a shipped artifact, never checked into `site/`, and never regenerated at build or runtime. Direct hand-authoring of vectors (no AI raster step at all) is equally sanctioned and preferred where quality allows.
2. **The shipped artifact is a code-drawn, layered SVG recipe checked into the repo** (`config/portraits/<persona_id>.json`, schema per story #586): stroke-only contours on `currentColor`, one accent layer on `var(--coach)`, fixed layer ids, theme-adaptive, animated by code (blink/breath/draw-in), rendered by `portraits.js` with `portrait(c) || sigil(c)` fallback. Schema conformance is enforced by a unit test; a recipe that fails validation does not render.
3. **Human curation is mandatory.** Portraits ship only after Matthew approves a **contact sheet** (all personas in the batch side-by-side, light + dark, 40/56/96 px — the sheet is approved, never portraits in isolation). Kill criterion: **two failed revision rounds → that coach stays sigil-only** and the rollout stories close. The runbook (`docs/design/PORTRAIT_RUNBOOK.md`) is the procedure.
4. **Provenance is required.** Every recipe carries a `_meta` block: generation model (or `hand-drawn`), prompt/session reference, date, tracer, and the sign-off record. A recipe without provenance fails validation.
5. **SS-11 and the PG-14 photoreal NO-GO remain fully in force.** SS-11 keeps rejecting people-imagery on editorial surfaces — portraits do not ride the editorial-image pipeline at all. Photoreal rendering of anyone, fictional or not, stays NO-GO; the sanctioned style is the engraved-bust vocabulary in the runbook's style bible, and a reverse-image sanity check (no resemblance to a findable real person) is part of every commissioning round.
6. **Disclosure is structural.** Portrait `aria-label`s follow the convention "Illustrated portrait of `<name>`, a fictional AI persona"; team/about surfaces carry the one-line disclosure sentence (runbook §6). A reader can never mistake a portrait for a photograph of a real advisor.

**Alternatives considered.** (a) *Stay sigils-only* — zero risk, but the cast's growing narrative surface (chronicle bylines, podcast, disputes) outgrows abstract marks; rejected as the permanent answer, retained as the fallback and the kill-criterion outcome. (b) *Commission human artwork* — best provenance, but cost/iteration friction for a $75/month-ceiling platform; not precluded by this ADR (the recipe schema doesn't care how the reference was made), just not required. (c) *Runtime generative portraits* — violates determinism (§8.2's byte-identical bar) and reintroduces AI-gen output as a shipped artifact; rejected outright.

**Complexity posture (ADR-103 row).** The portrait system (`portraits.js`, recipe schema, runbook) is **portfolio** — it deepens persona believability but nothing load-bearing depends on it; the fallback chain means deleting every recipe reverts the site to today's sigils with zero breakage. The *rules in this ADR* (AI-gen boundary, disclosure, photoreal NO-GO) are **load-bearing** and survive even if the portraits are retired.

**Consequences.** The program can proceed without re-litigating the §8 boundary each session; §8's letter now matches its reasons ("raster only as build-time derivatives of checked-in vectors"); any future drift (a raster avatar, an undisclosed portrait, a photoreal experiment) is a red-on-sight ADR violation rather than a judgment call. Cost: the commissioning workflow is manual by design — that friction *is* the curation gate.

---

## ADR-107: The coverage floor actually ratchets + a mypy tier-2 for the public serving surface

**Date:** 2026-07-05 · **Status:** Accepted · **Refines:** ADR-080/084 · **Story:** #419

**Context.** ADR-084 raised the coverage floor 8% → 9% and promised "re-baseline upward whenever a batch of pure-logic tests lands" — but that never happened. By 2026-07-05 the offline suite had grown to ~3,000 tests (from ~1,600 at ADR-084), real offline line coverage (`lambdas/`+`mcp/`, FAKE-creds parity per `docs/CONVENTIONS.md` §4) had risen to **~28%**, and the CI comment/flag had drifted apart (comment said "baseline ~9%, floor 8%"; the flag actually enforced 9% — nobody had updated the comment when the flag was last bumped). Separately, `mypy`'s enforced clean-module set (`tests/test_mypy_clean_modules.py`) had zero `lambdas/web/` entries — the site-api Lambda package that serves averagejoematt.com, and where BUG-01..BUG-04-class defects have actually shipped, had no type gate at all.

**Decision.**
1. **Coverage floor raised 9% → 25%** (comment and flag now agree; ~3-point margin under the measured ~28.3% to absorb minor cross-run/platform variance without being brittle). Scope unchanged: `lambdas/`+`mcp/` only.
2. **A self-ratcheting mechanism (recurring bump toward current-minus-one) is explicitly deferred**, not built in this pass — this ADR fixes the one-time drift and the honesty gap; a scheduled/remediation-agent task that re-measures and PRs a floor bump on a cadence is the next story, so the promise from ADR-084 doesn't quietly rot a second time.
3. **`mypy` tier-2 added: the public serving surface.** Eight already-clean `lambdas/web/*.py` modules join the enforced set: `site_api_common.py`, `site_api_coach.py`, `site_api_intelligence.py`, `site_api_reading.py`, `site_api_vitals.py` (two real `except X as e` / comprehension-variable shadowing sites renamed to fix a genuine `[misc]` error), `site_stats_refresh_lambda.py`, `og_image_lambda.py`, `og_moments.py` (needed a `[mypy-PIL.*] ignore_missing_imports` — Pillow ships no stubs). **Explicitly out of scope:** the two 3,000-line endpoint handlers (`site_api_data.py`, `site_api_observatory.py`) and everything that transitively imports them (`site_api_lambda.py`) — recorded as the next tier-2 ratchet step, not attempted here; and `site_api_ai_lambda.py`/`site_api_social.py`/`email_subscriber_lambda.py`/`subscriber_onboarding_lambda.py`, which all fail on one pre-existing, shared cause (`platform_logger.py`'s `Logger` subclass narrows `msg: object → str` on every level method, an LSP-violating `[override]`) that lives outside the web/ surface and is deferred rather than folded into this narrow pass.

**Consequences.** The coverage gate's comment now tells the truth, and the new floor locks in ~16 points of already-earned regression protection that was sitting unenforced. The public serving surface gets its first type gate exactly where recent live bugs shipped, without pretending the two largest handlers are clean. The self-ratchet promise and the `platform_logger.py`/big-handler mypy gaps are named, tracked follow-ups, not silently reabsorbed into "later."

---

## ADR-108: Coach quality gate promoted advisory → blocking, on the measured signal (N-06)

**Date:** 2026-07-05 · **Status:** Accepted · **Story:** #390 (epic #348) · **Amends:** the P5.5 wiring note in ADR-057/`docs/V2_AUDIT_PLAN.md` P3.1

**Context.** `coach-quality-gate` (Haiku-scored: anti-pattern phrases, decision-class-ceiling compliance, voice distinctiveness, cross-coach similarity) was wired into the COACH-V2 pipeline on 2026-05-19 but left deliberately advisory — `ai_calls._run_coach_v2_pipeline` invoked it `InvocationType="Event"` (fire-and-forget) *after* `output` was already finalized and returned, so the report was computed and logged but never read by anything; `PASS_SCORE_THRESHOLD=60` never gated a single publish. `docs/BACKLOG.md` N-06 scheduled a 30-day re-evaluation for 2026-06-19 to decide promote/adjust/stay-advisory; the date passed with no decision recorded, which is what this story closes.

**The re-evaluation (done as part of this story, not before it).** The gate writes no DDB record of its own (its docstring claimed `COACH#{id}/QUALITY#{date}` but the code is read-only — comment drift, not a real trail), so the only durable history was CloudWatch Logs. A Logs Insights query over `/aws/lambda/coach-quality-gate` for the full 30-day window (2026-06-05 → 2026-07-04, 206 real logged verdicts across all 8 coaches) found:

- **Score distribution:** min 62, max 92, mean 87.4, median 92 — **the score never once dropped below 60 or 40** in 30 days of real production output. The `PASS_SCORE_THRESHOLD=60` (and the BACKLOG's proposed 40) would have fired **zero times** — a "promote on score < 60/40" reading of N-06 would have shipped dead code.
- **The `passed` field is not purely score-derived.** `coach_quality_gate.py`'s own logic only forces `passed=False` when `score < 60`, but the Haiku evaluator independently sets `passed=False` on anti-pattern/decision-class/cross-coach findings even when the score stays ≥60 (observed: scores of 62–72 with `passed=False` for concrete phrase/decision-class/similarity violations). **21 of 206 outputs (10.2%) had `passed=False`** despite every one of them scoring ≥60 — this compound verdict, not the score cutoff, is the gate's real signal.

**Decision.** Promote to blocking, keyed off the gate's own `passed` field (unchanged: `PASS_SCORE_THRESHOLD=60` stays as-is — the measurement confirmed it as a non-binding floor rather than showing it needs retuning). Implementation, `ai_calls._enforce_quality_gate` (called from `_run_coach_v2_pipeline`, `lambdas/ai_calls.py`):
1. `coach-quality-gate` is now invoked **synchronously** (`InvocationType="RequestResponse"`), moved earlier in the pipeline (before `coach-state-updater`, not after) so the recorded/published text is whatever the gate actually approved.
2. **Regenerate-or-hold, bounded at 1 retry** (`_QUALITY_GATE_MAX_REGENERATIONS = 1` — mirrors the existing `grounded_generation.regen_once` "one corrective rewrite" convention already used elsewhere in the same pipeline for ADR-104's numeric-grounding gate). On `passed=False`, a corrective note built from the report's own findings (`_quality_gate_correction_note`) is appended to the original prompt and one regeneration is attempted; the regenerated draft is re-scored.
3. **Hold, don't auto-publish-with-a-note.** If the retry still fails, `_run_coach_v2_pipeline` returns `None` — the pipeline's pre-existing "None = don't publish this cycle" contract (same path used for orchestrator/voice-spec failures) keeps a known-failing narrative out of the daily brief entirely, rather than shipping it flagged. A `CoachQualityGateHeld` CloudWatch metric (dimensioned by `CoachID`) fires on every held cycle for operator visibility.
4. **Fails open on infra, never on a real verdict.** `_invoke_quality_gate_sync` treats an unreachable Lambda, a timeout, or a malformed payload as `passed=True` (never blocks on the gate itself being unavailable) — only an actual sub-threshold verdict from a gate that responded can hold a cycle.

**Why not adjust the threshold instead.** The measured score floor (62) sitting well above 60 could read as "the threshold is too lenient, tighten it" — but that's the wrong lesson: Haiku's score output is coarse (only ever landed on ~4 distinct values in 206 samples: 62/72/87/92) and isn't the dimension carrying the real fail signal in this data. Retuning a cutoff that's never been near the observed floor risks tuning to noise. The `passed` compound verdict already does the discriminating work the score was supposed to do; blocking on it is a smaller, better-evidenced change than picking a new number.

**Consequences.** ~10% of coach-generation cycles now cost one extra Sonnet regeneration call (bounded, one retry) instead of zero; a small fraction of those will still hold (no publish that cycle) rather than ship a flagged-but-live narrative — acceptable per the daily brief's existing "AI sections are optional, brief works without them" design. `coach-quality-gate`'s own scoring logic is unchanged (it remains a pure, reusable scorer); only the caller's handling of its verdict changed. The "reads only, no DDB writes" gap in the gate's own docstring is noted but not closed here (out of scope for N-06; the CloudWatch metric is sufficient operator visibility for this promotion) — a future story could add a persisted `QUALITY#` trail if per-output history becomes valuable beyond the CloudWatch metric + log line.

---

## ADR-109: The honesty gates cover DERIVED/proxy values too — TSB first, via the scheduled scan not the tight guard (M-8)

**Date:** 2026-07-05 · **Status:** Accepted · **Story:** #493 (epic #462) · **Extends:** ADR-104 (grounded-generation gate), ADR-105 (deterministic computation before any LLM verdict)

**Context.** The ADR-104/105 honesty moat has two deterministic layers over the numbers a coach can publish: the **tight generation-time guard** (`intelligence/grounding_guard.hard_canonical_contradictions`, block-and-regen, scoped to the three measured vitals RHR/recovery/HRV) and the **scheduled cross-surface scan** (`coherence_invariants.check_facts_agreement`, run daily by the Coherence Sentinel over the day's served narratives, wide tolerances, emits a digest + CloudWatch metric). Data-source health review finding **M-8** (P3): both layers only covered *measured* values. **TSB** (training stress balance = CTL−ATL, `training_load.py`) reached coach prompts (`ai_calls.py` daily-brief context line; character/readiness bands) ungated — a coach could publish a fatigue narrative on a TSB that contradicted `computed_metrics`, and nothing deterministic would catch it. TSB is also a *duration-proxy* estimate (M-3: the load basis is often not power-backed), so it is doubly exposed: ungated **and** an estimate.

**The scope question (the thing this ADR settles).** Should the honesty gates be extended to derived values *generally*, or is each derived value a case-by-case decision like weight already is? And *which* gate covers them?

**Decision.**
1. **Derived/proxy values are covered by the SCHEDULED cross-surface scan, never by the tight generation-time guard.** A false positive in the scheduled scan costs one line in an operator digest; a false positive in the tight guard forces a coach rewrite — and, worse, would "correct" the coach against a number that is *itself* an estimate. TSB is therefore a **deliberate, documented EXCLUSION from `grounding_guard`** (recorded in that module's `Scope:` docstring), exactly as weight is, and is **covered in `check_facts_agreement`** (M-8's acceptance).
2. **TSB gets a WIDE ABSOLUTE tolerance (±12 points), not a fractional one.** TSB is signed and crosses zero; a tolerance expressed as a fraction of the true value collapses to ~0 at the zero crossing (false positives) and is sign-blind. `coherence_invariants._ABS_TOL` / `_ABS_PLAUSIBILITY` hold the signed-metric bands; `check_facts_agreement` routes any key in `_ABS_TOL` through the absolute path. Only a *gross* miss (a coach citing a fresh +8 when the record says a deep-fatigue −22) fires — appropriate for a proxy.
3. **TSB is supplied to the Sentinel facts directly from `computed_metrics`, NOT added to `canonical_facts.build_canonical_facts`.** Keeping it out of the canonical schema keeps the tight guard's inputs and the `authoritative_facts_block()` injected into coach prompts unchanged — the two scopes stay cleanly separated (measured vitals + weight in canonical facts; derived values in the Sentinel's own facts dict).

**Why not extend the tight guard to derived values.** The tight guard's whole justification (its docstring) is that it is precision-tuned for *measured* physiological numbers where a hard contradiction is unambiguous and a false positive costs only a rewrite. A proxy estimate fails both premises. Extending it would import estimate-vs-estimate false positives into the highest-cost correction path.

**Consequences.** The coach-context TSB line is now covered by a deterministic check (satisfying ADR-105's deterministic-before-LLM rule) that runs in the daily Coherence Sentinel. The pattern generalizes: the *next* derived value to gate (candidates: CTL/ATL fitness/fatigue, ACWR, readiness score, day-grade sub-scores — all merged/derived and currently ungated the same way TSB was) follows the same recipe — add a bound pattern + an absolute-or-fractional tolerance to `_FACT_PATTERNS`, supply the fact to the Sentinel, leave the tight guard alone. This ADR is the written-down general rule so that decision is a lookup, not a re-litigation. Scope discipline: only TSB is gated in this change (#493); the other candidates are noted here for follow-up, not implemented.

---

## ADR-112: Board follow-up sessions — short-lived, server-side, opaque-token, no-PII (#546)

**Date:** 2026-07-05 · **Status:** Accepted · **Story:** #546 (epic #526) · **Amends:** the single-turn note in ADR-036 (the AI-endpoint split)

**Context.** `/api/board_ask` was single-turn: each reader question fanned out to the coach roster and returned, with no thread. The only follow-up memory anywhere was `/api/ask`'s 3-pair history, which is **client-held and untrusted** — the replayed assistant turns are attacker-controlled, so they can seed only weakly (they're re-safety-gated on every call, ADR-104). No genuine persona conversation could develop: a coach couldn't say "as I told you earlier," because it had no server-authoritative record of what it told the reader.

**Decision.** Add short-lived, server-side sessions to `/api/board_ask`, on the same public unauthenticated endpoint (a request carrying a `session_token` is a follow-up; the frontend posts both to one route).

**The session record (single-table, fits the no-GSI model):**
- **PK** `BOARDSESS#{token}`, **SK** `SESSION` — one item per thread.
- **token** = `secrets.token_urlsafe(24)` — opaque, unguessable, never sequential or derived from any request field; the token itself carries **no PII**.
- **Attributes:** `ip_hash` (the same 16-char hash already collected for rate limiting — the only quasi-identifier, and not PII), `followup_count` (Decimal, atomic), `threads` (map: coach_id → list of `{q, a}` turns), `created_at`, and `ttl` (Decimal epoch, **≤ 1h**). No email, no raw IP, no reader identity.
- **TTL** on the `ttl` attribute (DDB auto-purge) **plus** a defensive in-code expiry check in `_load_board_session`, because DDB TTL deletion is lazy.

**Security posture (public endpoint → untrusted input):**
1. **Opaque tokens only** — shape-gated by a regex *before* any DDB read, so probe/malformed tokens never touch the table.
2. **IP-bound** — a follow-up must present the originating `ip_hash`; a leaked token can't be replayed from another network.
3. **≤ 3 follow-ups per session** — checked before any model spend, then re-enforced atomically in the `UpdateItem` `ConditionExpression` (`followup_count < :cap`) so a burst can't double-spend past the cap.
4. **Per-IP `board_ask` rate limit still applies to every follow-up** (each costs a Bedrock call) — the cost ceiling is unchanged; worst case ≈ the existing per-IP allowance.
5. **Injection-hardening of the replayed transcript** — although the transcript is server-stored (stronger than `/api/ask`'s client history), it is treated as untrusted on replay: each stored question is re-tag-stripped and re-run through the WR-40 safety filter, each stored answer is re-scrubbed (`privacy_guard` + blocked-terms), and the new follow-up question is tag-stripped, length-capped, and safety-gated. The persona system block's existing identity-deflection + absolute-grounding rules (ADR-104) carry unchanged.
6. **Grounded gate stays fail-closed per turn** — the follow-up answer runs the same ADR-104 deterministic numeric gate (one corrective rewrite, else an honest in-voice refusal). Prior *grounded* answers seed the allow-list so referencing an earlier legitimate number isn't re-flagged as fabrication.

**IAM.** `role_policies.site_api_ai()` gains a `BOARDSESS#*`-scoped `PutItem`+`UpdateItem` statement (LeadingKeys) — the public role can touch only session records, never any other partition. Budget tier-2 pause is unchanged (checked before either path spends).

**Consequences.** A reader can now hold a genuine 3-turn thread with one coach who remembers the exchange, and moderated transcripts become publishable "office hours" content (the epic-#526 payoff). Cost is bounded by the pre-existing per-IP rate limit plus the ≤3 cap; the worst case is ~4× a single question's ceiling, explicitly capped. The session store is the first `BOARDSESS#*` partition and the second DDB-TTL user on the table (after `CACHE#matthew`). Deploy is via `deploy_site_api.sh` (the full `web/` dir — site-api is script-managed, not CDK).

---

## ADR-113: Retire the unified-sleep reconciler — a dead merge that mislabelled a public page (A-2/A-3, #487)

**Date:** 2026-07-05 · **Status:** Accepted · **Story:** #487 (epic #461, data-source health review 2026-07) · **Ledger:** ADR-103 row added (RETIRED)

**Context.** BS-08 (2026-03-17) added a `sleep-reconciler` compute Lambda meant to merge Whoop + Eight Sleep + Apple Health into one canonical nightly record at `SOURCE#sleep_unified`, "best source per field" (duration from Apple, staging/HRV from Whoop, environment from Eight Sleep), surfaced read-only at `/api/sleep_reconciliation` (#129, 2026-06-15) and rendered as a "Unified sleep — sources reconciled" panel on `/data/sleep`. The 2026-07 data-source health review found two defects that, together, make the surface a net negative:

- **A-2 (the merge is dead).** The conflict-resolution rules read record fields that do not exist. `reconcile_sleep` read `rem_percentage` / `slow_wave_sleep_percentage` / `light_sleep_percentage` / `awake_percentage` — the Whoop record's real fields are `rem_sleep_hours` / `slow_wave_sleep_hours` / `light_sleep_hours` / `time_awake_hours`; ditto `toss_and_turns` vs `toss_turn_count`, `hrv_score` vs `hrv_avg`; and the "Apple = clock duration" rule read sleep fields the Apple record has never carried. The stored "unified" record was therefore the **Whoop record plus one Eight Sleep score** — the promised ruleset never ran.
- **A-3 (structurally stale, and it mislabelled a public header).** `DEFAULT_LOOKBACK=1` with `range(1, 2)` reconciled *yesterday only* — never today's already-ingested wake date, and never re-reconciled a late/failed day. The record ran 1–2 nights behind (verified live 07-04: `/api/sleep_reconciliation night_of=2026-07-01` while `/api/sleep_detail as_of 2026-07-03`). The front-end preferred `uni.night_of` for the "Last night — the evidence" header, so **fresher figures were captioned with a stale night** — the same "two contradictory last-nights" defect the 2026-06-27 editorial review flagged.

**The fix-or-retire question.** Issue #487 framed it as binary: the reconciler does its promised per-field merge correctly and on time, or it stops existing. The module has **zero compute consumers** (nothing reads `sleep_unified`; its only surface was the one public panel) and was **absent from the ADR-103 complexity-posture ledger**.

**Decision: RETIRE.** Fixing would mean rebuilding the field map onto real record shapes, reusing `normalize_whoop_sleep`, dropping the inert Apple rule, and adding today + trailing re-reconcile — real effort to keep a surface that **duplicates `/api/sleep_detail`** (which already cross-references Eight Sleep + Whoop, fresher) and that **no compute path depends on**. Per ADR-103's "subtract more than add" posture, a dead subsystem with no consumers that actively *mislabels* a public page is a retire, not a repair. Retiring removes the mislabel entirely and is the lower-risk, simpler change.

**What was removed / changed.**
- Deleted `lambdas/compute/sleep_reconciler_lambda.py`; removed the `SleepReconciler` Lambda + its `cron(0 14 * * ? *)` EventBridge rule from `compute_stack.py` and `compute_sleep_reconciler()` from `role_policies.py`. **`LifePlatformCompute` needs a `cdk deploy`** to drop the live function + rule + role.
- Removed `handle_sleep_reconciliation` and the `/api/sleep_reconciliation` route (`web/site_api_data.py`, `web/site_api_lambda.py`); removed the "Unified sleep — sources reconciled" panel and the `uni` fetch from `evidence_sleep.js`.
- **The "night of" header now sources from the live `/api/sleep_detail as_of_date`** (the latest Eight Sleep night in the window) via `lastNightDate(s)` — an honest, never-stale field. Locked by `test_compute_surfacing.py::test_sleep_detail_night_of_date_sourced_live_not_from_unified` + `::test_sleep_reconciliation_handler_is_retired`.
- The orphan `sleep_unified` DDB partition is **left in place** (delete-safe; read by nothing) and **reclassified RAW_TIMESERIES → SYSTEM_STATE** (dead partition) in `phase_taxonomy.py` so the restart tooling still traverses the existing records without raising — same precedent as `google_calendar` / `composite_scores`.

**Consequences.** `/data/sleep` loses a redundant, chronically-mislabelled panel and keeps the fresher `/api/sleep_detail` figures under a correct date. One compute Lambda + rule + IAM role retire (a small cost/attack-surface reduction). No data is destroyed. If a genuinely-merged sleep record is ever wanted, it must be rebuilt against real record shapes with today-inclusive lookback and a compute consumer that justifies it — this ADR is the recorded verdict so that case starts from scratch, deliberately, rather than reviving dead code.

---

## ADR-119: Keep polling Whoop, do not adopt v2 webhooks (A-8, #508)

**Date:** 2026-07-05 · **Status:** Accepted · **Story:** #508 (epic #465, data-source health review 2026-07, finding **A-8** P3) · **Spike:** `docs/reviews/WHOOP_WEBHOOK_SPIKE_2026-07.md` · **Feeds:** #415 (source-reconciliation goal) · **Type:** SPIKE verdict — no production change

**Context.** Whoop ships v2 push webhooks (`workout|sleep|recovery.{updated,deleted}`, HMAC-SHA256 signed, 5-retry-over-~1hr at-least-once delivery — see the spike for the full vendor contract) that this platform does not use. The current posture is an hourly **18×/day** trailing re-fetch (`lambdas/ingestion/whoop_lambda.py`; `cron(0 {INGEST_HOURLY} * * ? *)` + a 9:30 AM PT recovery refresh), fetching 4 endpoints (`recovery`, `activity/sleep`, `cycle`, `activity/workout`) with `refresh_trailing_days=2` so late-arriving per-workout sub-records are healed. A-8 asks whether push should replace poll. The receiver shape a Whoop webhook would need already exists in-repo (`hevy_webhook_lambda.py` FunctionURL + `hevy_common.verify_webhook_signature` + the id-only "fetch canonical, never trust the body" discipline), so feasibility was never the question — desirability is.

**Decision: KEEP POLLING.** Webhooks are *additive* complexity for Whoop, not a replacement, for four reasons that all point the same way:

1. **Webhooks don't remove the fragile part.** The v2 payload is **id-only**; the receiver must still hold a valid OAuth access token to fetch the canonical record. Whoop's hardest edge — refresh-token rotation on every refresh, which is why the ingest lambda pins **`ReservedConcurrentExecutions=1`** and disables async retry (`ingestion_stack.py:82-95`) — is *worsened* by bursty concurrent deliveries, not removed.
2. **Webhooks can't cover the whole surface.** There is **no `cycle`/strain webhook event** in v2 (only workout/sleep/recovery). Strain would keep polling regardless, so webhooks add a *second* ingestion path rather than replacing the one we have.
3. **You still need a reconciling poll for reliability.** Whoop drops an event after ~5 retries/~1 hour with no vendor DLQ or replay. The current trailing re-fetch *is* the drop-healing backstop a webhook-primary design would still have to keep — so webhooks sit on top of polling, not instead of it.
4. **Nothing is forcing the move.** Whoop has no rate-limit breaker; the code documents polling as "safe and cheap." The only prize is latency (hour → seconds) on a source whose freshest signal (recovery) finalizes mid-morning and is consumed by the 11 AM daily brief / nightly compute — a latency win the platform doesn't actually spend.

Per ADR-103's "subtract more than add" posture, adopting webhooks here is added surface area (FunctionURL + IAM role + CDK + signature-verify + `trace_id` dedup + monitoring, all *alongside* the poll that must stay) for latency the platform doesn't consume. That is the wrong trade.

**Consequences.** No production change in this story; the trailing re-fetch remains the single Whoop ingestion path and its drop-healing is treated as the feature, not overhead. This is the recorded input to #415: Whoop stays **poll-reconciled**, not push-reconciled. No follow-up implementation issue is filed (that is only required on ADOPT). Revisit only on a concrete trigger — Whoop introducing rate limits that make 18×/day expensive, a product need for sub-hour recovery latency, or a webhook-native design that also covers `cycle` — at which point this ADR is the starting point that must be overturned deliberately.

---

## ADR-120: The OIDC automation identities are codified now, and the trust-tighten is staged as a watched follow-up (DEVOPS-02, #401)

**Date:** 2026-07-05 · **Status:** Accepted (codify half shipped; tighten half staged) · **Story:** #401 (epic #342 "Live infra matches code") · **Source:** DEVOPS-02 / verified_open_ledger

**Context.** The two highest-privilege identities in the account — the CI/CD deploy role (`github-actions-deploy-role`, assumed by *every* job in `ci-cd.yml`) and the self-healing remediation role (`github-actions-remediation-role`) — plus the GitHub OIDC identity-federation provider (`token.actions.githubusercontent.com`) existed **only as hand-managed AWS config**. `grep -rn 'github-actions' cdk/stacks/*.py` returned nothing: no source of truth, no review trail, no `git revert` rollback. Worse, both roles' trust was scoped to `repo:averagejoematt/life-platform:*` — assumable from **any branch of a public repo**. DEVOPS-02 (tighten the subject to main/production + split a read-only diagnosis role from the deploy role) was deferred *by design* for one honest reason: editing live trust policy by hand is scary — a wrong subject locks the automation out of the cloud entirely, and #401's own acceptance bar requires the tighten to be "validated by watching a real CI run complete end-to-end."

**Decision: split the one scary change into two small safe ones — codify now, tighten later.**

**Codify (this PR — a proven no-op to live).** The three identities are captured as checked-in JSON under `infra/iam/`, reflecting live **exactly** as it is today (trust still `repo:*`), plus a read-only verify script:
- `github-oidc-provider.json`, `github-actions-{deploy,remediation}-role.trust.json`, `…​.permissions.json` — the source of truth.
- `deploy/verify_oidc_iam.py` — read-only (`iam:GetRole` / `GetRolePolicy` / `GetOpenIDConnectProvider` only), semantic (order-insensitive) diff of checked-in JSON vs. live; `--strict` exits non-zero on drift. Verified CLEAN against live at commit time (5 targets, zero drift). This makes *any* future trust change a reviewable PR with `git revert` as the rollback — turning the scary hand-edit into a reviewable diff.

**Tighten (staged, NOT executed here — see `infra/iam/README.md`).** The proposed tightened trust lives at `infra/iam/proposed/*.trust.main-only.json` with a full apply/validate/rollback runbook. The load-bearing detail this documents: GitHub's OIDC `sub` claim differs per job — only the `deploy` job declares `environment: production` (→ `…:environment:production`), while `plan`/`smoke`/`visual-qa`/`post-deploy`/`rollback`/`notify` present `…:ref:refs/heads/main`. So the tightened **deploy-role** trust must allow **both** subjects or half the pipeline loses cloud access; the **remediation-role** (scheduled/dispatch on main only) needs just `…:ref:refs/heads/main`. The tighten, the read-only-diagnosis-role split, the end-to-end CI validation, the non-main access-simulation, and the S-E6-01 drift-sentinel wiring are tracked in a dedicated follow-up issue (#687) and MUST be executed attended, under a watched CI run, with the rollback in hand.

**Why not CDK?** Each CDK stack already mints its own least-privilege roles, but these two automation roles are the *bootstrap* identity that CDK deploys *through* — putting them inside a stack CDK deploys would be circular (the role must exist before the pipeline that would create it can run). Checked-in policy JSON + a verify script is the right altitude: reviewable and revertible without a chicken-and-egg deploy dependency.

**Consequences.** Zero live IAM mutation in the codify PR — behaviour is byte-identical, but the highest-privilege credentials in the account are now reviewable and git-revertible. The deferred, genuinely-risky tighten is now a small, well-documented, watched follow-up instead of an open-ended fear.

---

## ADR-117: A deploy-critical test lane gates the pipeline; auto-rollback covers the site (+ layer runbook)

**Date:** 2026-07-05 · **Status:** Accepted · **Stories:** #416, #418 (epic #341 "Ship green, know main == live") · **Extends:** the CI/CD gate ordering in `docs/CONVENTIONS.md`

**Context.** CI was a single strict chain — `lint → test → plan → deploy → visual-QA`. Because `plan` depended on the *entire* exhaustive suite (`test`), one unrelated red test skipped the deploy **and** the post-deploy visual/AI-QA gate that guards what readers actually see. With main red ~2/3 of the last 30 runs (20 failure / 9 success / 1 cancelled), the reader-facing safety net was dark on most pushes (#416). Separately, the auto-rollback net covered only backend Lambda **code** on a smoke failure; the two most-changed, most-reader-hurting surfaces — the **public site** and the **shared layer** — had manual-only recovery, and the site rollback script that existed (`deploy/rollback_site.sh`) was invoked by nothing and was itself stale (raw `safe_sync`, no re-hash, no `version.json` regen) for the v4 content-hashed-asset era (#418).

**Decision.**

1. **Split a deploy-critical test lane (#416).** A new CI job `test-critical` runs a fast, fully-offline pytest subset selected by the `deploy_critical` marker (`pytest -m "deploy_critical and not integration"`). `plan` now depends on `[lint, test-critical]`, **not** the exhaustive `test` job. The exhaustive suite still runs on every push (job `test`, in parallel, `needs: lint`) and still reds main + fires `notify-failure` — it simply no longer skips `plan → deploy → visual-QA`. Net effect: an unrelated red unit test no longer blacks out the reader-facing gate, while the full suite's red flag is preserved.

   **Inclusion criteria (so the lane doesn't rot into "everything" or "nothing").** A test is `deploy_critical` iff its failure means **the deploy artifact or its wiring is broken, or a core honesty/safety contract the running system depends on is violated** — i.e. it validates the *deploy contract*, not product/data correctness or AI narrative quality. Concretely, the lane is the structural/contract linters + the honesty gate: Lambda handler names & signatures, shared-layer module presence + consumer wiring, MCP tool registration, IAM role policies, secret-name references, DDB key patterns, CDK↔source consistency, and the deterministic AI-output faithfulness gate. **Explicitly excluded** (still run in the full suite, still red main, but must not gate deploy): statistical-rigor tests, narrative/AI-quality judgement, doc-drift, content/data-correctness. The authoritative file list + criteria live in `docs/CONVENTIONS.md` ("Deploy-critical test lane"); the marker is registered in `pytest.ini`. Live-AWS tests inside a marked file (e.g. `test_lv6`) carry `@pytest.mark.integration` and the `not integration` filter keeps them out of this creds-free lane.

2. **Extend auto-rollback to the site, and surface the layer runbook (#418).** A new job `rollback-site-on-failure` fires when a CI **site** deploy (`plan.site_changed == true`, `deploy` succeeded) is followed by a failed **smoke test OR failed visual/AI-QA** gate. It reverts the site to the previous commit (`HEAD~1`, the single-squash-merge convention) via the now-CI-wired `deploy/rollback_site.sh`, which was rebuilt to go through the **canonical** `sync_site_to_s3.sh` path — re-hashing the asset graph and re-stamping `version.json` (new `OVERRIDE_BUILD_SHA` env) so `/version.json` truthfully returns to the prior build — and re-invalidates CloudFront. Every rollback (Lambda or site) now publishes its own SNS notification, so a revert is never invisible. **Shared-layer rollback stays manual by design** — republishing/attaching a layer is a CDK operation, too risky to auto-fire — but is now an **explicit runbook line** in both the rollback notification and `notify-failure` when `layer_changed`, not a buried log echo.

**What is guarded / unchanged.** The `production` **manual-approval gate on `deploy` is untouched** — auto-rollback reverts, it never auto-deploys past the gate. The site rollback fires on the visual-QA gate (the reader-facing net); the Lambda rollback stays smoke-only (visual-QA is gating-not-rollback for backend code, unchanged from the 2026-06-05 posture).

**Verification status.** Items that need a real CI run are honestly pending: the "visual-QA executes on a deliberate red unit test" proof (#416) and the "one end-to-end site rollback drill returns /version.json to the prior stamp" proof (#418) require a live pipeline run and cannot be demonstrated from a worktree. The mechanism is implemented and locally validated (lane selects 11 files / ~1215 tests in ~3s all green; YAML + both shell scripts parse clean); the drills are the recorded post-merge verification step.

**Consequences.** The reader-facing visual-QA gate stops being hostage to unrelated red tests; the site gains an automatic revert on a bad deploy; the layer's manual recovery is now loud instead of silent; and `rollback_site.sh` is fixed from a latent no-op into a correct, CI-invoked path. Complexity posture (ADR-103 row): **load-bearing** — this is CI safety machinery; if the platform stops deploying through CI it goes with it, not before.

---

## ADR-116: The CloudWatch alarm bill pays rent — surgical orphan cleanup, coverage never traded for dollars (cost-05, #411)

**Date:** 2026-07-05 · **Status:** Accepted · **Story:** #411 (epic #344 "The budget serves readers") · **Audit:** `docs/reviews/CLOUDWATCH_AUDIT_2026-07.md`

**Context.** Monitoring is the #2 cost line after AI — June `AlarmMonitorUsage` $10.46 + `MetricMonitorUsage` $4.41 ≈ $15/mo, roughly June's budget overage. Standard alarms bill $0.10/alarm-month; the billing pattern (108.65 alarm-months) suggested churn/duplication. The audit inventoried every live alarm and billable custom metric against what the 8 CDK stacks actually synthesize.

**What the reconciliation found.** **136 live metric alarms**, **107 defined in CDK** (all 107 live; **0 code-not-live**), and **29 orphan alarms live-but-not-in-code** — legacy CLI-era `put-metric-alarm` remnants plus double-prefixed (`life-platform-life-platform-*`) duplicates. The issue's "~56 live" was a stale undercount; the ~108 billed alarm-months ≈ the 107 CDK-managed set averaged over June, with the 29 orphans (and newer batch additions) drifting today's total to 136. Two structural cost facts shaped every decision: **composite alarms cost *more* ($0.50 each), not less**, so "consolidate into a composite" cannot reduce the bill; and a single metric-math alarm cannot span the fleet (CloudWatch rejects `SEARCH` in alarms, caps math at ~10 metrics). **The only levers that reduce the alarm bill are (a) delete a redundant alarm, or (b) replace many alarms with one digest metric + one alarm.**

**Decision.** Surgical, reviewable, coverage-preserving:
- **RETIRE 18 orphans** (−$1.80/mo) — each is a provable duplicate of an IaC alarm on the same function, or covered by the freshness/liveness digest (the 8 per-source `*-ingestion-errors` remnants of the 2026-05-29 consolidation), or on a **dead metric** (`AskEndpointErrors`, emitted nowhere). Executed via `deploy/cloudwatch_retire_orphans.sh` (non-auto-run; the orchestrator runs it). The before/after failure-mode enumeration for the per-source→digest consolidation is in the audit §4 — the only mode the deleted alarms caught that the digest does not is a *single transient throw that self-heals*, explicitly the noise class the platform already removed.
- **ADOPT 2 orphans into IaC** (net-neutral count) — `compute-pipeline-stale` (`ComputePipelineStaleness`) and `hae-webhook-no-invocations-24h` (HAE webhook liveness, BREACHING) carry unique silent-failure coverage; codified in `monitoring_stack.py` under **new IaC-owned names** so `cdk deploy` never collides with the manual originals the script deletes.
- **KEEP 9 orphans live and untouched** — each is the *only* signal for its failure (MCP recursion failsafe, the canary's own liveness "watcher-of-watcher", per-utility-lambda self-health). Deleting them to save $0.90/mo would reopen a silent-failure gap. They remain out-of-IaC drift, flagged for a future adopt PR; left un-codified now to keep this monitoring deploy small.
- **KEEP all 107 CDK alarms**, including the **48 per-lambda `ingestion-error-*` alarms on the compute/email fleet.** These were the tempting big lever (~$4.80/mo) but are **NOT provably redundant**: verified in CDK that **only 1 of 32 compute and 1 of 17 email lambdas route to a DLQ** — the other ~47 have no dead-letter queue, so an async failure is retried twice and dropped silently, making each per-lambda alarm the sole failure signal. Retiring them today = a real gap. **Forbidden.**

**The honest gap to the $4–6 target.** This PR recovers ~$1.80/mo now. The remaining ~$4.70/mo is reachable only by first **wiring `dlq=core.dlq` to every compute/email lambda** (so terminal async failures land in the already-alarmed `life-platform-ingestion-dlq`) and *then* retiring the ~47 per-lambda first-error alarms in favor of the DLQ digest — a genuine per-N→digest consolidation with provable equivalence, but a compute+email deploy with its own blast radius that must not be rushed inside a monitoring-cost PR. Recorded here as the sanctioned follow-up. **The governing principle: honesty over completeness — a silent-failure gap is never worth a few dollars.** Custom metrics were inventoried too (audit §6): every emitted namespace backs an alarm or the two ops dashboards; none is safely retirable without a code change to stop emitting, and none is high-enough cost to justify the risk.

---

## ADR-115: DLQ escalation that actually escalates — a durable content-keyed retry ledger (REL-02/REL-03, #402)

**Date:** 2026-07-05 · **Status:** Accepted · **Story:** #402 (epic #346, harden the public surface) · **Area:** operational / reliability

**Context.** `dlq_consumer_lambda` drains `life-platform-ingestion-dlq` every 6 hours: it classifies each failed message transient-vs-permanent, re-invokes the source Lambda for transients, and archives + emails permanents. The v1 design had a self-defeating flaw for its one job — *announcing a permanently-broken message*:

- **REL-02 (the counter resets).** A transient retry re-invoked the source Lambda and then **always deleted the DLQ message**. If that retry failed, it re-landed on the DLQ as a **brand-new SQS message** with a fresh `MessageId` and `ApproximateReceiveCount` reset to `1`. The only "failed N times" signal the code had was `ApproximateReceiveCount`, which the delete→re-invoke→re-land cycle reset every pass — so the `receive_count >= 3` escalation could never accumulate and **a poison message could loop invisibly forever**.
- **REL-03 (drain-rate cap).** A fixed `MAX_MESSAGES_PER_RUN = 10` meant at most 10 messages per 6-hour run; a burst larger than 40/day outgrew the drain rate.

There was no live fire — the right moment to fix a safety net that cannot currently announce when it is catching the same thing over and over.

**Decision.** Track retries by a **stable, content-derived identity** in a **durable ledger** that survives the SQS churn, escalate on an accumulated count, and delete only on a confirmed outcome.

- **Stable identity.** `stable_message_id = sha256(function_name + "\n" + body)[:32]`. The SQS `MessageId`/`ApproximateReceiveCount` both reset across the re-land cycle, but the message **body** (the original async-invocation event we replay verbatim) is byte-identical across those cycles — so the content hash is the one anchor that persists.
- **Durable ledger.** A new single-table partition **`SYSTEM#dlq-ledger`**, SK `MSG#{stable_id}`, holds `attempts` (cumulative), `fn_name`, `first_seen`/`last_seen`, `last_receive_count`, a `body_preview`, an `escalated` flag, and a `ttl` (90-day auto-purge — the same DDB TTL attribute `rate_limiter` uses). **No GSI** — composite-key access only, per the single-table rule. Each pass does one atomic `UpdateItem ADD attempts :receive_count` (Decimal), so the count **preserves receive-count semantics** (a message SQS itself redrove several times contributes all of those attempts) *and* accumulates across delete/recreate cycles. Fail-soft: a DDB blip falls back to the message's own receive_count rather than dropping the message.
- **Delete only on a confirmed outcome.** A transient below threshold is re-invoked; the message is deleted **only if the invoke returns 2xx (accepted)**. An unconfirmed re-invoke leaves the message on the queue to redrive, so the durable count keeps climbing instead of resetting.
- **Escalation that pages.** A message escalates when it is classified permanent, is **unretryable** (no resolvable source function), **or** its cumulative `attempts` reaches `ESCALATE_THRESHOLD` (default 3). Escalation archives to S3, marks the ledger row `escalated`, and **pages the operator on the existing urgent SNS topic `life-platform-alerts`** — the same real-time channel as canary / daily-brief / cost-runaway (ADR-050), not a new one — plus the existing consolidated SES summary as a redundant record. Verified with a deliberately-poisoned test message.
- **Time-budget drain (REL-03).** The fixed 10-message cap is replaced by a **wall-clock budget** (`DRAIN_BUDGET_SECONDS`, default 90) bounded by the Lambda's own remaining time (15s safety margin) and an absolute 1000-message guard, looping `receive_message` until the queue is empty or the budget is spent — so a burst can't outgrow the drain rate in a single run.

**IAM (CDK — deploy `LifePlatformOperational`).** `role_policies.operational_dlq_consumer()` gains: `dynamodb:GetItem`/`UpdateItem` on the table (the ledger), `kms:Decrypt`/`GenerateDataKey` on the DDB CMK (the table is CMK-encrypted), and `sns:Publish` scoped to the `life-platform-alerts` topic. The `operational_stack` `DlqConsumer` construct wires a new `ALERTS_TOPIC_ARN` env var. All additions are least-privilege and resource-scoped.

**Consequences.** A permanently- or repeatedly-failing DLQ message now **pages** instead of silently retrying forever — the safety net can finally announce what it is catching. Transient failures that recover on retry produce **no new noise** (the ledger row just ages out on TTL). The ledger is the third `SYSTEM#`/TTL user on the table (after `RATE#*` and `BOARDSESS#*`) and is `phase_taxonomy`-neutral (a `SYSTEM#` operational partition, not experiment-scoped). Cost is negligible (one small DDB row per distinct failing message, 90-day TTL). The change is backward-compatible: normal transient recovery is unchanged; only the escalation trigger moved from a resettable SQS counter to a durable content-keyed count.

---

## ADR-118: Retire the Eight Sleep bed-temperature pipeline — a dead endpoint that silently fed five permanently-empty surfaces (A-4, #489)

**Date:** 2026-07-05 · **Status:** Accepted · **Story:** #489 (epic #461, data-source health review 2026-07) · **Ledger:** ADR-103 row added (RETIRED)

**Context.** `eightsleep_lambda.fetch_temperature_data` fetched bed/room temperature from `GET /v2/users/{id}/intervals` and merged `bed_temp_c/f`, `room_temp_c/f`, `bed_temp_min/max_c`, `temp_level_avg/min/max` into each nightly Eight Sleep record. The 2026-07 data-source health review found the surface dead (A-4, P2, confidence high):

- **The endpoint 404s on every run.** ~135 × `"Intervals endpoint error: HTTP 404"` in 7 days of logs; the fetch caught `HTTPError` and `return {}` — a *silent* swallow, so nothing paged and nothing surfaced the death.
- **No temperature has been written for 4+ months.** DDB spot-checks Mar–Jun show no `bed_temp_*` anywhere; live `/api/sleep_detail` returns `bed_temp_f: null`. Consequently the five consumer surfaces — the `get_sleep_environment_analysis` MCP tool, the `/data/sleep` environment chart + `sleep_detail`/`sleep_trend` temp fields + the "A3 bed temp → deep sleep" correlation card, the Wednesday chronicle email's "SLEEP ENVIRONMENT" temp lines, and the AI expert/context env analysis — all rendered a permanent empty state.

**Investigation (find-the-endpoint first, per #489's acceptance bar).** The `/v2/intervals` path is dead: the actively-maintained community client (`lukas-clarke/pyEight`, the OAuth2 API this lambda's auth flow is modelled on) no longer references an intervals endpoint at all. The *only* current temperature source in that library is the **`/v1/users/{id}/trends`** response — the same endpoint this lambda **already** fetches and parses for HR/HRV/respiratory-rate — where average bed/room temperature appears (per pyEight) under `sleepQualityScore.tempBedC` / `.tempRoomC`, plus a `timeseries.tempRoomC` array of `[ts, value]` pairs. I could **not confirm those fields are populated for this account** without a live-credential spike (no creds in this environment; the app plan / Pod generation may not report room temp), and the surfaces have been empty 4+ months. Per #489's own guidance — "if there's no clearly-working documented endpoint and it's been 404ing 4+ months, RETIRE is the honest outcome" — and per ADR-105 (no honest number I can't verify), the honest call is to **retire the dead temperature surfaces rather than leave them empty or revive on an unverified guess**.

**Decision: RETIRE the temperature surfaces; keep the rest of Eight Sleep.** Only temperature is dead — sleep staging, score, efficiency, HR/HRV, respiratory rate, latency, circadian timing, and restlessness (tosses) all flow through the working `/v1/trends` fetch and are untouched.

**What was removed / changed.**
- **Fetch (writer):** deleted `fetch_temperature_data` and its call in `fetch_day`; dropped the `**raw["temp"]` merge in `transform` (`lambdas/ingestion/eightsleep_lambda.py`). Deleting the swallow *is* the "no silent 404-swallowing" fix — the dead path no longer exists to swallow. (The main `/v1/trends` fetch already `raise`s on any non-401 error → visible via the lambda error metric.)
- **MCP:** removed the `get_sleep_environment_analysis` tool (it was *entirely* a bed-temp band optimizer — no non-temp half; without temp it could only ever return "Need ≥14 nights of paired data") from `tools_sleep.py` + `registry.py` (import + entry) + the dead `sleep_environment` SoT domain in `config.py`. Tool count drops 144 → 143; `sync_doc_metadata.py --apply` re-synced; `test_wiring_coverage.py` green.
- **Site `/data/sleep`:** removed the environment (bed temp vs deep sleep) chart in `evidence_sleep.js`; removed `bed_temp_f`, `optimal_temp_f`, `30d_avg_temp` and the optimal-temp bucketing from the `sleep_detail`/`sleep_trend` payloads and the "A3 bed temp → deep sleep" correlation card in `web/site_api_data.py`. **site-api needs its `web/`-dir deploy.**
- **Email:** the chronicle "SLEEP ENVIRONMENT" section kept its live restlessness (tosses) readout, renamed "SLEEP RESTLESSNESS", temp lines removed (`wednesday_chronicle_lambda.py`).
- **AI / coach / validator dead-field reads:** dropped `bed_temp_f` from `ai_context._build_sleep_data` (**shared-layer module**), `avg_bed_temp_f` from `ai_expert_analyzer_lambda`, the `eightsleep` EWMA metric list + `METRIC_DOMAIN` in `coach_computation_engine`, `KNOWN_SIGNALS` in `coach_stance.py` (**shared-layer module**) + the sleep-coach stance's `watches`/`cares_most`/`plan` (`config/coaches/sleep_coach_stance.json`), and the `at_least_one_of` list in `ingestion_validator`. Removing the field from these expected-signal lists prevents the B-3 failure mode (an always-absent "expected" field silently dragging coverage).
- **Out of scope (deliberate):** `hypothesis_engine_lambda`'s `bed_temp_f` read + `VALID_SPEC_METRICS` entry are left as-is — that read is guarded by A-5's regression test (`test_data_truth_batch.py`), a *separate* open issue, and it is a defensive None-yielding read (rows drop None), not a user-visible empty surface. Docs (`SCHEMA.md`, `MCP_TOOL_CATALOG.md`) mark the temp fields/tool retired.
- **Reactivation lead (recorded so a future session starts from evidence, not scratch):** a live-cred spike can log the raw `/v1/trends` `sleepQualityScore` for one night and check for `tempBedC`/`tempRoomC`; if present, temperature can be re-lit by extracting it in `parse_trends_for_date` (which already parses `sleepQualityScore.current` for HR/HRV) — no new endpoint, no auth change — and re-adding the consumer surfaces. If absent, the retirement stands.

**Consequences.** `/data/sleep`, the daily/weekly AI narratives, the chronicle email, and the MCP surface stop presenting a bed-temperature story that has had no data since ~March; one dead MCP tool and ~125 lines of dead fetch retire; the silent 404-swallow is gone. No stored data is destroyed (the historical `bed_temp_*` columns simply never existed at scale). The rest of Eight Sleep is unaffected. If temperature is genuinely wanted back, the trends-`sleepQualityScore` path above is the cheap, evidence-first route — this ADR is the recorded verdict so that case starts deliberately.

---

## ADR-121: Keep State of Mind — restart the habit, fix the mis-keyed consumers, don't prune (#507)

**Date:** 2026-07-05 · **Status:** Accepted · **Story:** #507 (epic #465, data-source health review 2026-07, finding D-6) · **Ledger:** ADR-103 row added (**Kept / load-bearing-pending-data** — explicitly reversing the retire-candidate lean).

**Context.** The State of Mind subsystem ingests Apple Health / How-We-Feel valence check-ins through the HAE webhook: the `process_state_of_mind` normalizer (~200 lines in `health_auto_export_lambda.py`) stores individual check-ins to `raw/matthew/state_of_mind/YYYY/MM/DD.json` and writes daily aggregates (`som_avg_valence`, `som_check_in_count`, `som_top_labels`, `som_top_associations`, …) onto the **apple_health** partition's `DATE#` records — the same single-partition pattern all HAE sub-datatypes use (CGM, BP, water, workouts; there is deliberately **no per-datatype partition**, see `freshness_checker_lambda.py`). The 2026-07 review (D-6) found `raw/matthew/state_of_mind/` holds exactly one file (2026-04-02) — the owner logged How-We-Feel once and stopped — while five-plus consumer surfaces reference the machinery. D-6 posed it as a decision: restart the automation, or ledger it retire-candidate and prune.

**Decision: KEEP.** The owner chose to restart the manual How-We-Feel logging habit ("I just need to start doing it"), so the ~200 lines of normalization and the consumer wiring stay. This **explicitly reverses** the retire-candidate lean D-6 floated; State of Mind moves to **Kept / load-bearing-pending-data** in the ADR-103 ledger. Objective mood valence is a genuinely useful signal (mood→sleep, mood→training-load, the Mind pillar) that no other source supplies; the blocker is a daily habit, not a design flaw. The retirement trigger is reset: prune only if the habit does not resume by the 2026-Q4 review.

**But the subsystem was not actually ready — a consumer-keying bug class made it silently no-op.** Making "kept" honest meant fixing the surfaces so a *new* reading flows end-to-end. Verification against the one-day fixture found the ingest→S3→apple_health(`som_*`) path sound, but **most consumers were keyed to a `state_of_mind` DDB partition that ingestion never writes** (it writes to apple_health), so they read an empty partition — and several also read field names the normalizer never emits (`valence` / `emotion_labels` / `life_areas` / `state_of_mind_count`). Corrected under #507 to read the apple_health partition + the canonical `som_*` fields: `character_engine.py` (Mind-pillar valence — was reading `valence`/`average_valence`, always None even with data), `character_sheet_lambda.py`, `daily_brief_lambda.py`, `evening_nudge_lambda.py`, `wednesday_chronicle_lambda.py`, `field_notes_lambda.py`, `ai_expert_analyzer_lambda.py`, `site_api_data.py`, `tools_social.py`, plus an S3-path fix in `tools_lifestyle.py` (`raw/state_of_mind/…` → `raw/{USER_ID}/state_of_mind/…`). The `site_api_observatory.py` and `site_api_intelligence.py` surfaces already carried an apple_health fallback and were left as-is. `coach_computation_engine.py` and `ai_context.py`/`ai_calls.py` already read the correct partition/fields. Honest empty states (ADR-104) preserved throughout: absence reads as `None` / "no State of Mind data", never a fabricated mood or a broken panel.

**Consequences.** No ingestion behaviour changes and no data migration — the fix is entirely on the read side, so it is byte-compatible with the existing one-day record and with any new check-ins the moment logging resumes. The restart runbook (`docs/RUNBOOK.md`, State of Mind section) documents the one manual step the owner must take. Because the fix touches `character_engine.py` (a shared-layer module), the coordinated deploy must rebuild+publish the layer and redeploy Compute/Email/Web/MCP consumers.

---

## ADR-114: One code-drawn card engine — every off-site card rides the same renderer (#595)

**Date:** 2026-07-05 · **Status:** Accepted · **Story:** #595 (epic #575, instrument uplevel · workstream H) · **Adopters:** #420 (character share card), #405 (per-chronicle share kit) · **Ledger:** ADR-103 row added (load-bearing — the shared off-site brand surface)

**Context.** The OG card is most readers' first pixel — the "ahead of the curve" judgement happens off-site, before anyone clicks. Historically each card surface drew its own Pillow chrome: `og_image_lambda` drew the ~12 daily page cards, `og_moments` (#404) drew the permalinked moment cards (week recap · board answer · graded prediction), and every new reach surface would have hand-rolled another bespoke drawer. Three reach stories were queued behind that duplication (#420 character sheet, #405 chronicle kit, plus future per-coach + calibration-scoreboard cards).

**Decision.** Extract one renderer — `lambdas/web/card_engine.py` — as the single place a 1200×630 brand card is drawn. It is a small template kit (brand tokens: palette, the bundled TTF faces, canvas, safe margins) + primitives (`base_canvas` · `draw_header` · `draw_metric` · `draw_footer` · wrapped title · `fmt` · `wrap` · a `draw_uncertainty` stat that prints a CI range + n so a projected number is never a bare point estimate the site itself wouldn't show, #551/ADR-105) + a **card-type registry** (`register_card` / `render`) that reach surfaces register into, mirroring the evidence registry. `og_image_lambda` now **re-exports** the engine's tokens/primitives under their historic names, so the daily cards render byte-identically to before the extraction (the primitives are literally the same functions now — pinned by `test_card_engine`). `og_moments.build_moment_card` keeps drawing moment cards through those same primitives.

**Adopters.**
- **#420 (character).** A `character` card type renders from the COMPUTED `character_stats.json` only — level, tier, XP, days active, per-pillar levels. Honesty/privacy (ADR-104 + phenoage privacy): a fixed field allowlist, no narrated line, and **no chronological age** (proven byte-identical with/without an age field in the payload). `/data/character/` gets the card as its `og:image` and a `share ↗` affordance (the existing `share.js` helper).
- **#405 (chronicle).** A `chronicle` card type renders the **honest-stats line as the creative** — a week graded 57 with a broken streak is the point, never sanitized. The daily og sweep (`og_moments._sweep_chronicles`) draws one card per published post from `generated/journal/posts.json`; the email-stack `chronicle_share_kit` builds the text/JSON kit (excerpt · stats line · canonical URL · caption · the card's stable URL) from already-published fields and surfaces it in the chronicle approval email + a stable generated location under `/moments/share-kits/`.

**Constraints honored.** SVG-native / self-hosted only — the engine reads the repo-bundled TTFs and fetches nothing external (strict CSP + no-external-HTTP). Pillow lives only in the web/operational packages (pillow-layer), so the honest-stats CARD is drawn by the daily og sweep (which has Pillow), while the email stack — which has neither Pillow nor a card need — only builds the text kit. Cards remain on the existing OG sweep schedule; generated files stay under the `generated/` prefix (ADR-046), served via the already-routed `/moments/*` CloudFront behavior (no CDK change).

**Consequences.** New off-site card types are now a registry entry + a fixture test, not a new bespoke drawer. The daily cards are unchanged pixel-for-pixel. Risk is contained: the engine imports no shared-layer platform modules, and every card path is fail-soft (a missing `character_stats.json` falls back to the historic minimal character card; a chronicle sweep error never blocks the daily cards).

---

## ADR-122: Todoist filters query the endpoint that actually filters — and the decision-fatigue threshold measures pressing load, not the backlog (E-1, #478)

**Date:** 2026-07-05 · **Status:** Accepted · **Story:** #478 (epic #460, data-source health review 2026-07)

**Context.** The Todoist ingestion Lambda and the MCP Todoist tools were migrated onto the v1 API (`https://api.todoist.com/api/v1`) but kept the REST-v2 habit of passing a `filter` query param to `GET /tasks`. On the v1 API `/tasks` silently **ignores** `filter` and returns the entire active list — so `overdue_count` and `due_today_count` were both ≈ the whole task list, not the filtered subset. Separately, `get_active_tasks` read a single `limit=200` page with no cursor follow, so `active_count` was **page-capped at 200**. Every downstream consumer of the Todoist snapshot (daily-brief decision-fatigue alert, `/data` task-load panels, the `get_decision_fatigue_signal` MCP tool) ran on these poisoned numbers from ~2026-05-10 (the v1 migration) onward.

Measured live 2026-07-05 to confirm the fix and ground the threshold re-eval:
- **Old (buggy):** active `/tasks?limit=200` (single page) → **200** (a cap, not a count); overdue `/tasks?filter=overdue` (param ignored) → the whole list.
- **New (fixed):** active paginated → **270**; overdue `/tasks/filter?query=overdue` → **184**; due-today `/tasks/filter?query=today` → **0**.

**Decision.**
1. **Filter queries use the dedicated server-side endpoint** `GET /api/v1/tasks/filter?query=<filter>` (the required param is `query`, not `filter` — verified against the live 400 `ARGUMENT_MISSING: query`). Both `todoist_lambda.get_filtered_tasks` and `mcp/tools_todoist._list_all_tasks` route filter strings there; the plain `/tasks` path is used only for the unfiltered active snapshot.
2. **The active fetch paginates** past the 200 page-cap via `next_cursor` (shared `_paginate_tasks` helper in the ingestion Lambda; the MCP `_list_all_tasks` loop already followed the cursor).
3. **The decision-fatigue threshold measures the decision-pressure set, not the backlog.** `_compute_decision_fatigue_alert` (BS-MP3, `daily_insight_compute_lambda`) fired on `active + overdue`. Fixing the endpoint does **not** by itself rescue that: `active + overdue` (270 + 184 = 454) double-counts (overdue ⊂ active) and is dominated by non-pressing backlog, so it clears any small threshold every single day — the load condition never discriminated. The load quantity is now **`overdue + due_today`** (the tasks past-or-at deadline), on which the default `>15` floor is a live signal again: it fires only when the *pressing* pile is genuinely large **and** T0 habits are slipping (<60%).

**The "15" is provisional, not empirical.** The prior comment claimed "compliance drops above 15 active+overdue" — but that was measured on the poisoned snapshots, so it was never real. Per **ADR-105 rule 4** the durable home is a personal-variance band over Matthew's own overdue distribution (`personal_baselines.py`, floor-guarded at `MIN_N=30`). That is **blocked until ~30 days of clean post-#478 ingestion accrue** — the pre-#478 records are point-in-time unrecoverable and are flagged `snapshot_unreliable=true` (`scripts/flag_todoist_unreliable_snapshots.py`; annotate, don't fake). The absolute `>15` floor (env `DECISION_FATIGUE_THRESHOLD`) holds until then, then migrates to the band — the same floor-guarded pattern #543 used.

**Consequences.** Overdue/due-today counts and the full active count become true for the first time since the v1 migration. The decision-fatigue alert stops firing on a constant and starts tracking the real pile. Historical Todoist metrics before the clean-data cutover stay in place but carry an honesty flag so no forecast or narrative treats them as real. No schema change; ingestion record shape is unchanged.
