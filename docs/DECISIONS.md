# Life Platform — Architecture Decision Records (ADR)

> Permanent log of significant architectural, design, and operational decisions.
> Each ADR captures the decision, context, alternatives considered, and outcome.
> Last updated: 2026-06-03 (v8.3.0 — + Garmin retired & budget-guard/AI-cost trim; ADR-074/075)
> 75 ADRs total (ADR-001 → ADR-075).

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
| ADR-005 | No GSI on DynamoDB table | ✅ Active | 2026-02-25 |
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
| ADR-039 | CSS/JS cache: content-hash filenames with 1-year immutable TTL | ✅ Active | 2026-03-29 |
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
| **P1.2 Orphaned WAF cleanup** | Audit was wrong. WAF protects HAE webhook, isn't orphaned. Still billing $4.75/mo but it's load-bearing. |
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

Feature → tier cutoffs (priority ordering "protect daily brief longest"):
- `coach_narrative`, `ensemble`, `chronicle`: tier 1
- `website_ai` (`/api/ask`, `/api/board_ask`): tier 2
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

**Date:** 2026-06-03
**Status:** Paused — commented out of `freshness_checker_lambda.py` SOURCES + OAUTH_SECRETS + `qa_smoke_lambda.py` (shown ⏸).
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
