# Life Platform — Architecture Decision Records (ADR)

> Permanent log of significant architectural, design, and operational decisions.
> Each ADR captures the decision, context, alternatives considered, and outcome.
> Last updated: 2026-03-09 (v3.3.9)

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

---

## ADR-001 — Single-Table DynamoDB Design

**Status:** Active  
**Date:** 2026-02-23  
**Context:** Needed a storage layer for 19 data sources with diverse schemas, accessed primarily by user+source+date patterns.

**Decision:** Single DynamoDB table (`life-platform`) with composite key `pk=USER#matthew#SOURCE#<source>` + `sk=DATE#YYYY-MM-DD`.

**Alternatives considered:**
- One table per source: simpler per-source schema, but cross-source queries require multi-table joins — a DynamoDB antipattern
- RDS/Aurora: relational model natural for health data, but over-engineered for a single-user platform; $30+/month minimum cost; operational overhead
- Multiple tables by domain: simpler mental model, but access pattern across sources (e.g. daily summary) becomes 19 separate API calls vs. 1

**Outcome:** Single-table works well. All access patterns are served by PK+SK queries. No GSI needed. One 400KB concern (large strava/macrofactor nested items): monitored by `item_size_guard.py` alarm.

---

## ADR-002 — Lambda Function URL over API Gateway for MCP

**Status:** Active  
**Date:** 2026-02-23  
**Context:** MCP server needed a public HTTPS endpoint for Claude clients.

**Decision:** Lambda Function URL with `AuthType=NONE` + in-Lambda HMAC Bearer token validation.

**Alternatives considered:**
- API Gateway REST: $3.50/month, latency overhead, additional config surface
- API Gateway HTTP: cheaper but still adds cost and config; Function URLs are free

**Outcome:** $0 for the endpoint. Security equivalent — auth enforced at Lambda boundary. No observable latency difference vs. API Gateway HTTP at this scale.

---

## ADR-003 — MCP Protocol for Claude Integration

**Status:** Active  
**Date:** 2026-02-24  
**Context:** Needed a way for Claude to query personal health data.

**Decision:** Implement Model Context Protocol (MCP) server as a Lambda with Streamable HTTP transport (spec 2025-06-18). Tools are functions that return structured data from DynamoDB. Remote access via Function URL + HMAC Bearer token.

**Alternatives considered:**
- REST API with custom Claude instructions: brittle, not composable, poor tool discovery
- Direct DynamoDB access from Claude: not supported, security concern
- S3 data dumps: stale by definition, not queryable

**Outcome:** 144 tools across 30 modules. Remote MCP allows access from Claude Desktop, claude.ai web, and Claude mobile. This is the core interface between Claude and the platform.

---

## ADR-004 — Source-of-Truth Domain Ownership

**Status:** Active  
**Date:** 2026-02-25  
**Context:** Multiple devices measure the same metrics (HRV from Whoop, Garmin, Eight Sleep, Apple Watch). Needed a clear winner per domain to avoid coaching contradictions.

**Decision:** Each health domain has exactly one authoritative source (SOT). When two sources measure the same thing, only the SOT is used for scoring, grading, and coaching. SOT map stored in user profile (DynamoDB), changeable without code deploys.

**Outcome:** 21 SOT domains. Sleep SOT changed from Eight Sleep to Whoop at v2.55.0 — the config-based approach made this a 30-second change, not a code deploy. `get_device_agreement` MCP tool cross-validates across devices for research purposes.

---

## ADR-005 — No GSI on DynamoDB Table

**Status:** Active  
**Date:** 2026-02-25  
**Context:** GSIs enable query patterns beyond PK+SK — e.g., query by date across all sources.

**Decision:** No GSI by design. All access patterns are served by PK+SK (source-specific date ranges). Added to project plan as "Insights GSI" if coaching insights partition exceeds 500 items.

**Outcome:** $0 extra cost. No query limitation encountered to date. Revisit at Month 6.

---

## ADR-006 — DynamoDB On-Demand Billing

**Status:** Active  
**Date:** 2026-02-25  
**Decision:** On-demand (pay-per-request) over provisioned capacity.

**Rationale:** Workload is spiky — morning ingestion burst (13 Lambdas writing in a 2-hour window), then sparse MCP queries throughout the day. Provisioned minimum would cost $10-15/month with consistent waste. On-demand: ~$0.30/month.

---

## ADR-007 — Lambda Memory 1024 MB

**Status:** Active  
**Date:** 2026-02-26  
**Context:** MCP Lambda was running slowly on complex queries (5-10 second responses).

**Decision:** Bump MCP Lambda from 512 MB to 1024 MB. Lambda CPU allocation scales linearly with memory.

**Alternatives considered:**
- Provisioned concurrency: $10.80/month — eliminated cold starts but not slow execution
- Step Functions orchestration: overkill for synchronous query pattern
- Query optimization: done, but memory was the primary bottleneck

**Outcome:** +~$1/month. 2x CPU allocation halved heavy query times. Provisioned concurrency never needed.

---

## ADR-008 — No VPC

**Status:** Active  
**Date:** 2026-02-27  
**Decision:** All Lambdas deployed without VPC. Authentication enforced at Lambda boundary (HMAC tokens, AWS IAM resource policies).

**Rationale:** VPC adds cold start latency (+400-900ms for ENI attachment), NAT Gateway cost (~$30/month for outbound internet), and operational complexity. Single-user personal platform has no compliance requirement for network isolation. Auth-at-boundary is sufficient.

**Risk accepted:** Lambda IPs are public AWS ranges. Mitigated by IAM role scoping and HMAC token validation.

---

## ADR-009 — CloudFront + S3 Static Dashboard

**Status:** Active  
**Date:** 2026-02-27  
**Decision:** Web dashboard served as static HTML+JS from S3 behind CloudFront. No server-side rendering.

**Alternatives considered:**
- API Gateway + Lambda-rendered pages: ~$3-5/month, dynamic but complex
- Amplify: managed but opinionated, harder to customize
- Vercel/Netlify: external dependency, adds vendor risk

**Outcome:** ~$0.01/month. Custom domain (`dash.averagejoematt.com`). Lambda@Edge for password auth. Daily Brief writes `data.json` to S3; dashboard reads it client-side. Decoupled refresh: page can update without Lambda deployment.

---

## ADR-010 — Reserved Concurrency over WAF

**Status:** Active  
**Date:** 2026-02-28  
**Context:** Expert review flagged Lambda Function URL exposure without rate limiting.

**Decision:** Reserved concurrency (10) on MCP Lambda as primary abuse protection. API Gateway already has throttle (1.67 req/s, burst 10) for webhook endpoint.

**Alternatives considered:**
- WAF on Lambda Function URL: ~$5/month, limited effectiveness for single-user scenario
- API Gateway in front of MCP: adds cost and latency

**Outcome:** $0 cost. Reserved concurrency prevents runaway Lambda invocations in cost-abuse scenario. 80% of WAF protection for $0.

---

## ADR-011 — Whoop as Sleep Source-of-Truth

**Status:** Active  
**Date:** 2026-03-01 (v2.55.0)  
**Context:** Both Whoop and Eight Sleep track sleep. Initially Eight Sleep was SOT.

**Decision:** Whoop is SOT for sleep duration, staging, efficiency, and score. Eight Sleep retained for bed environment data only (temperature, toss-and-turns, bed presence).

**Rationale:** Whoop captures ALL sleep regardless of location (couch, travel, non-Eight Sleep beds). Eight Sleep only captures bed time. Whoop's wrist sensor is location-independent. Eight Sleep data retained and accessible via `get_sleep_environment` tool.

---

## ADR-012 — Board of Directors as S3 Config

**Status:** Active  
**Date:** 2026-03-01 (v2.56.0)  
**Decision:** 13 Board of Directors personas stored in `s3://matthew-life-platform/config/board_of_directors.json`, dynamically loaded by all email Lambdas via `board_loader.py` (5-minute cache).

**Alternatives considered:**
- Hardcode personas in each Lambda: requires redeploy to change persona voice/focus
- DynamoDB config record: more ops overhead for a relatively static config

**Outcome:** Persona changes (add/edit/remove) via MCP tools without Lambda redeployment. All 5 email Lambdas use the same config. Pattern extended to `character_sheet.json`.

---

## ADR-013 — Shared Lambda Layer

**Status:** Active  
**Date:** 2026-03-05 (v2.97.0)  
**Decision:** 8 shared modules (platform_logger, ingestion_validator, ai_output_validator, insight_writer, board_loader, etc.) packaged as a shared Lambda Layer attached to 16 Lambdas.

**Alternatives considered:**
- Shared S3 artifact at deploy time: slower deploys, more complex
- Duplicate code across Lambdas: fix-once-deploy-everywhere benefit lost

**Outcome:** Fix shared utilities once, propagate to all Lambdas on next layer build. Layer rebuild: `bash deploy/p3_build_shared_utils_layer.sh`.

---

## ADR-014 — Secrets Manager Consolidation

**Status:** Active  
**Date:** 2026-03-05 (v2.75.0)  
**Context:** 12 Secrets Manager secrets at $0.40/month each = $4.80/month. Most held a single key.

**Decision:** Consolidate to 8 secrets. Domain-specific bundles: `ai-keys`, `api-keys` (pending deletion), `todoist`, `notion` + OAuth secrets remain separate per service (whoop, withings, strava, eightsleep, garmin) + `mcp-api-key`.

**Governing principle (clarified 2026-03-11):** Bundle secrets only when the same credentials are consumed by the exact same set of Lambdas. The one justified bundle is `life-platform/ai-keys` (Anthropic API key + MCP bearer token — shared by all email, compute, and MCP Lambdas). Everything else is dedicated. Habitify, Todoist, and Notion each have their own secret because each is consumed by exactly one Lambda — bundling them saves $0.40/month at the cost of blast radius and coupling. OAuth secrets (Whoop, Withings, Strava, Garmin) are always dedicated because they auto-rotate and write back to their own secret. The original `api-keys` bundle was an over-optimisation; migrating away from it was correct.

**Current end state (v3.7.13):** 9 active secrets — `whoop`, `withings`, `strava`, `garmin`, `eightsleep`, `ai-keys`, `todoist`, `notion`, `habitify`. `api-keys` **permanently deleted 2026-03-14**.

**Lesson learned (dropbox-poll incident):** Lambdas with hardcoded `SECRET_NAME` env vars are latent risks after consolidation. Audit remaining Lambdas for any stale overrides. Key name prefixes (`dropbox_app_key` vs `app_key`) must match new bundle structure.

---

## ADR-015 — Compute→Store→Read Pattern

**Status:** Active  
**Date:** 2026-03-06  
**Context:** Daily Brief was computing day grade, character sheet, readiness score, and anomalies inline during a single Lambda invocation — creating a slow, complex monolith.

**Decision:** Standalone compute Lambdas (character-sheet-compute at 9:35 AM, daily-metrics-compute at 9:40 AM, daily-insight-compute at 9:42 AM) run before Daily Brief. Each writes a DDB record. Daily Brief reads pre-computed records with inline fallback.

**Outcome:** Daily Brief Lambda simplified (monolith split from 4,002 → 1,366 lines). Compute results available to other consumers (buddy page, dashboard). Failure isolation: compute Lambda can fail without taking down the Brief.

---

## ADR-016 — platform_memory DDB over Vector Store

**Status:** Active  
**Date:** 2026-03-07 (IC-1)  
**Context:** IC roadmap identified need for persistent cross-session memory for AI coaching. Options: vector store (Pinecone, pgvector), external embedding service, or DynamoDB key-value.

**Decision:** `platform_memory` DDB partition with structured key-value records. No external service, no embeddings at this stage.

**Rationale:** Corpus too small (2-3 weeks of data), vector store cost $70-100/month vs $25/month platform budget, DDB covers 80% of the use case. Revisit when journal corpus exceeds 150 entries (Month 4-5).

**What NOT to build (documented):** Vector store/RAG — premature. Fine-tuning — addresses style not reasoning. Local/small LLM — quality delta vs Claude is large on health coaching tasks.

---

## ADR-017 — Prompt + Context Engineering over Fine-Tuning

**Status:** Active  
**Date:** 2026-03-07  
**Decision:** All AI quality improvements via prompt engineering, context injection, and chain-of-thought structure. No fine-tuning.

**Rationale:** Fine-tuning addresses style/format consistency, not reasoning quality. The coaching quality gap is a reasoning and context problem. Fine-tuning on early data would overfit to initial state — the opposite of an adaptive system. `platform_memory` + progressive context injection is the correct pattern.

---

## ADR-018 — CDK for IaC over Terraform

**Status:** Active  
**Date:** 2026-03-09 (PROD-1, v3.3.5)  
**Context:** PROD-1 hardening item required Infrastructure as Code for repeatability and multi-user path.

**Decision:** AWS CDK (Python) over Terraform. 7 stacks deployed: Ingestion, Compute, Email, Operational, Mcp, Monitoring, Web.

**Rationale:** CDK is native Python (same language as platform), eliminates HCL context switch, better AWS resource type coverage. Lambda packaging via `Code.from_asset("../lambdas")` with handler auto-detection. `create_platform_lambda()` helper standardizes Lambda factory pattern.

**Lesson learned:** `Code.from_asset` path is relative to CDK app root (`cdk/`), so must reference `../lambdas` not `lambdas`. CDK deploy success ≠ execution success — always verify via CloudWatch logs post-deploy.

---

## ADR-019 — SIMP-2: Framework for New Lambdas, Skip Migration

**Status:** Active  
**Date:** 2026-03-09 (v3.2.1, deliberately closed)  
**Context:** SIMP-2 proposed consolidating 13 ingestion Lambdas into a shared `ingestion_framework.py`.

**Decision:** Framework built and validated on weather Lambda (POC). Migration of existing Lambdas stopped. `ingestion_framework.py` in shared Layer for new Lambdas only.

**Why migration was stopped:** 2 of 3 Phase 2 Lambdas (Strava, Garmin) are architecturally incompatible with per-day callback pattern — Strava uses range-based API, Garmin has native C deps. Full migration ROI doesn't justify regression risk at current scale. **Future pattern: new Lambdas fitting per-day poll pattern should use the framework; existing Lambdas stay as-is.**

---

## ADR-020 — MCP Tool Functions Before TOOLS Dict

**Status:** Active  
**Date:** 2026-02-26 (P1 fix)  
**Context:** P1 incident — MCP server broken since v2.31.0 with NameError on every invocation.

**Decision:** All MCP tool functions MUST be defined BEFORE the `TOOLS={}` dict in `mcp_server.py`. The dict is evaluated at module load time; forward references cause NameError.

**Lesson learned:** This is a Python module-level evaluation constraint, not a runtime error. Deploy success ≠ execution success. Post-deploy CloudWatch log check is mandatory.

---

---

## ADR-021 — EventBridge Rule Naming Convention (CDK)

**Status:** Active  
**Date:** 2026-03-10 (v3.4.0)  
**Context:** v3.4.0 deleted 40 manually-created EventBridge rules and replaced them with CDK-managed equivalents. Naming convention needed to be consistent and discoverable.

**Decision:** CDK-managed EB rules use lowercase-hyphenated names matching the Lambda function's logical purpose, e.g., `whoop-daily-ingestion`, `daily-brief-schedule`, `character-sheet-compute`. The rule name matches the CDK construct ID and, where applicable, the Lambda function name. CDK is the authoritative source for all EB rule names — manually-created rules are deleted after CDK adoption.

**Alternatives considered:**
- CDK auto-generated names (e.g., `IngestionStack-whoop-daily-ingestionXXXX`): Not human-readable; breaks RunBook references
- Keep manual rules alongside CDK rules: Causes duplication, alarm thrashing, and double-invocation risk

**Outcome:** 50 CDK-managed rules with consistent, human-readable names. Rule names are stable across CDK deploys (use `rule_name=` explicit naming, not auto-generated). ARCHITECTURE.md schedule tables reference these names.

**Lesson learned (EB rule recreation gap incident):** When migrating from manual → CDK rules, use CDK import or blue/green rule swap. Never delete-then-create for time-sensitive schedules. Delete old rules only after verifying CDK rules are active and have fired at least once.

---

## ADR-022 — CoreStack Scoping: Shared Infrastructure vs. Per-Stack Resources

**Status:** Active  
**Date:** 2026-03-10 (v3.4.0)  
**Context:** With 8 CDK stacks, deciding what lives in CoreStack vs. stack-specific resources.

**Decision:** CoreStack owns exactly three shared infrastructure primitives: (1) SQS Dead Letter Queue (`life-platform-ingestion-dlq`), (2) SNS alert topic (`life-platform-alerts`), (3) shared Lambda Layer. All other stacks import CoreStack outputs via cross-stack references. CoreStack deploys first and is never destroyed.

**What is NOT in CoreStack:**
- DynamoDB table and S3 bucket: stateful data resources, managed manually with PITR/versioning enabled. CDK-managing stateful resources introduces destroy risk. These are referenced by ARN in all stacks.
- CloudFront, ACM, API Gateway: managed in the Web stack or as standalone resources
- Per-Lambda IAM roles: defined in each stack via `role_policies.py` to keep least-privilege scoping close to the resource

**Rationale:** Shared infrastructure changes infrequently and affects all stacks. Per-resource policies belong with the resource. Stateful data must never be accidentally deleted by `cdk destroy`.

**Lesson learned (DLQ ARN incident):** On first CDK deployment of CoreStack, the DLQ ARN changed because CDK couldn't import the manually-created resource. Future pattern: for resources that already exist, use `from_queue_arn()` CDK import rather than creating new — preserves ARN stability.

---

## ADR-023 — Sick Day Checker as Shared Utility, Not Standalone Lambda

**Status:** Active  
**Date:** 2026-03-10 (v3.4.0)  
**Context:** Sick day detection logic (low step count, elevated resting HR, unusual sleep patterns, journal keywords) needed to be integrated into the compute pipeline.

**Decision:** `sick_day_checker.py` is a shared utility module in the Lambda Layer, imported by `daily-metrics-compute` and `daily-brief`. It is not a standalone Lambda with its own EventBridge schedule.

**Alternatives considered:**
- Standalone Lambda on a schedule: adds a 42nd Lambda, introduces timing dependency (must run before `daily-metrics-compute`), provides no benefit over a synchronous call
- Inline logic in `daily-brief`: couples sick-day logic to the presentation layer; `daily-metrics-compute` also needs the result for day grade computation

**Outcome:** Sick day detection is synchronous with compute. The result is stored in `computed_metrics` and consumed by both the Daily Brief (tone adjustment, suppressed coaching pressure) and the Character Sheet (component score modifiers). No scheduling overhead.

**Interface:** `from sick_day_checker import detect_sick_day` → returns `SickDayResult(is_sick: bool, confidence: float, signals: list[str])`. Consumed by `compute_anomaly_detector`, `daily_metrics_compute_lambda`, `daily_brief_lambda`.

---

*Last updated: 2026-03-13 (v3.7.15)*

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

**Outcome:** No change. Documented explicitly so future reviewers don’t re-open this question.
