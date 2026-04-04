# Life Platform — Architecture Decision Records (ADR)

> Permanent log of significant architectural, design, and operational decisions.
> Each ADR captures the decision, context, alternatives considered, and outcome.
> Last updated: 2026-03-29 (v4.4.0)

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
