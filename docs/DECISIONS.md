# Life Platform — Architecture Decision Records (ADR)

> Permanent log of significant architectural, design, and operational decisions.
> Each ADR captures the decision, context, alternatives considered, and outcome.
> Last updated: 2026-03-14 (v3.7.23)

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
