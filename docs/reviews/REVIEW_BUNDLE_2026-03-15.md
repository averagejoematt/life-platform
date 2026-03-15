# Life Platform — Pre-Compiled Review Bundle
**Generated:** 2026-03-15
**Purpose:** Single-file input for architecture reviews. Contains all platform state needed for a Technical Board assessment.
**Usage:** Start a new session and say: "Read this review bundle file, then conduct Architecture Review #N using the Technical Board of Directors."

---

## 1. PLATFORM STATE SNAPSHOT

### Latest Handover

→ See handovers/HANDOVER_v3.7.40.md


---

## 2. RECENT CHANGELOG

# Life Platform — Changelog

## v3.7.40 — 2026-03-15: R13-F14 MCP canary 15min + R13-XR X-Ray tracing

### Summary
MCP endpoint is now probed every 15 minutes (R13-F14). Canary also fixed three bugs introduced by R13-F05 (wrong secret name, raw api-key header instead of HMAC Bearer, tool count threshold too high). X-Ray ACTIVE tracing wired into MCP Lambda via CDK (R13-XR).

### Changes

**R13-F14 — MCP canary 15-min probe**
- `lambdas/canary_lambda.py`: 3 bugs fixed
  - `MCP_SECRET` default: `ai-keys` → `mcp-api-key`
  - Auth: `x-api-key` header → HMAC-derived Bearer token (matches R13-F05 fail-closed logic)
  - Tool count threshold: `< 100` → `< 50` (we have 89; headroom for SIMP-1 cuts)
  - +`derive_mcp_bearer_token()` helper
  - +`mcp_only` event flag: skips DDB/S3 checks for 15-min MCP-only probe
- `patches/patch_canary_mcp_only.py`: one-shot patch script that inserted the `mcp_only` mode
- `deploy/create_mcp_canary_15min.sh` (new): EventBridge rule `rate(15 minutes)` → canary with `{"mcp_only": true}` + two CloudWatch alarms:
  - `life-platform-mcp-canary-failure-15min`: any CanaryMCPFail ≥ 1 in 15 min
  - `life-platform-mcp-canary-latency-15min`: p95 CanaryLatencyMCP_ms > 10s for 2 consecutive windows

**R13-XR — X-Ray tracing on MCP Lambda**
- `cdk/stacks/mcp_stack.py`: `tracing=_lambda.Tracing.ACTIVE` on MCP server Lambda
- `cdk/stacks/lambda_helpers.py`: `tracing` param added to `create_platform_lambda()`, forwarded to `_lambda.Function()`
- `cdk/stacks/role_policies.py` `mcp_server()`: +`XRay` PolicyStatement (`xray:PutTraceSegments`, `PutTelemetryRecords`, `GetSamplingRules`, `GetSamplingTargets`)
- CDK deployed: `LifePlatformMcp` ✅

### Test Results
- All 16 tests passing ✅

### Deployed
- `life-platform-canary` ✅ (fixed auth + mcp_only mode)
- `LifePlatformMcp` CDK stack ✅ (X-Ray ACTIVE tracing)
- EventBridge rule `life-platform-mcp-canary-15min` ✅
- CloudWatch alarms: `life-platform-mcp-canary-failure-15min`, `life-platform-mcp-canary-latency-15min` ✅

---

## v3.7.39 — 2026-03-15: LV1 fix — centralize layer version + LV5

### Summary
LV1 in the new layer consistency test caught a real defect: `SHARED_LAYER_ARN` with hardcoded `:10` was duplicated independently in `ingestion_stack.py` and `email_stack.py`. Fixed by introducing `cdk/stacks/constants.py` as the single source of truth. Both stacks now import from there. Added LV5 to prevent regression.

### Changes
- `cdk/stacks/constants.py` (new): `SHARED_LAYER_VERSION`, `SHARED_LAYER_ARN`, `ACCT`, `REGION` — single place to bump the layer version on every rebuild
- `cdk/stacks/ingestion_stack.py`: removed local `SHARED_LAYER_ARN` definition, imports from `constants`
- `cdk/stacks/email_stack.py`: removed local `SHARED_LAYER_ARN` and `REGION`/`ACCT`, imports from `constants`
- `tests/test_layer_version_consistency.py`: LV1 now excludes `constants.py` from scan; +LV5 ensures no other stack file has an inline layer ARN

### Test Results
- `test_mcp_registry.py`: 7/7 ✅
- `test_secret_references.py`: 4/4 ✅
- `test_layer_version_consistency.py`: 5/5 ✅ (LV1 was failing, now passes)

### Deployed
- No Lambda deploys — CDK source + test-only changes

---

## v3.7.38 — 2026-03-15: R13-F08 layer CI pytest + R13-F01 closed + R13-F02 I12/I13

### Summary
Layer version consistency linter added to CI (offline, LV1-LV4). R13-F01 closed — full CI/CD pipeline already existed. Two new live-AWS integration tests added: I12 (MCP tool call shape) and I13 (freshness checker data).

### Changes
- `tests/test_layer_version_consistency.py` (new): LV1–LV4, wired into ci-cd.yml
- R13-F01 CLOSED: `ci-cd.yml` already implements pytest+synth+diff+approve+deploy+smoke (was marked "not started" erroneously)
- `tests/test_integration_aws.py`: +I12 (MCP tools/call with `get_data_freshness`, validates JSON-RPC response shape), +I13 (freshness checker returns structured source data)

### Test Results
- All 15 tests passing before LV1 fix was applied (LV1 intentionally failed first)

---

## v3.7.37 — 2026-03-15: R13-F15 BH FDR correction + R13-F10 d2f annotation

### Summary
Benjamini-Hochberg FDR correction applied to weekly correlation compute. With 23 simultaneous tests at alpha=0.05, naive thresholding produces ~1.15 expected false positives per run; BH controls the false discovery rate instead. d2f() annotated with canonical-copy deferred note.

### Changes
- `lambdas/weekly_correlation_compute_lambda.py`: +`pearson_p_value()`, +`apply_benjamini_hochberg()`, wired into `compute_correlations()`. Each pair now gets `p_value`, `p_value_fdr`, `fdr_significant` fields.
- `lambdas/weekly_correlation_compute_lambda.py`: `d2f()` annotated with R13-F10 deferred note (canonical copy in `digest_utils.py`, switch after layer v12)

### Deployed
- `weekly-correlation-compute` ✅

---

## v3.7.36 — 2026-03-15: R13-F09 complete + R13-F06 + R13-F08-dur

### Summary
Three more R13 findings closed. Medical disclaimers now on all 6 health-assessment tools (complete). Cross-source correlation upgraded with n-gating, p-value, and 95% CI. Duration alarms deployed for Daily Brief and MCP Lambda.

### Changes

**R13-F09 — Medical disclaimers complete**
- `mcp/tools_lifestyle.py`: `_disclaimer` added to `tool_get_blood_pressure_dashboard` and `tool_get_blood_pressure_correlation` return dicts
- `mcp/tools_training.py`: `_disclaimer` added to `tool_get_hr_recovery_trend` return dict
- All 6 health-assessment tools now covered (health/cgm dispatchers from v3.7.35 + these 3)

**R13-F06 — Cross-source correlation n-gating + statistics**
- `mcp/tools_training.py` `tool_get_cross_source_correlation`: hard minimum raised 10→14
- N-gating: strong requires n≥50, moderate requires n≥30; smaller samples downgraded with explanation
- P-value added: two-tailed t-test (math.erf approximation, no scipy dependency)
- 95% CI added: Fisher z-transform method
- New output fields: `p_value`, `significance`, `ci_95`, `n_gating_note`

**R13-F08-dur — Duration alarms**
- `deploy/create_duration_alarms.sh` (new): creates two CloudWatch p95 duration alarms
  - `life-platform-daily-brief-duration-p95`: fires if p95 >240s for 3 consecutive 5-min windows
  - `life-platform-mcp-duration-p95`: fires if p95 >25s for 3 consecutive 5-min windows (near 30s soft timeout)
- Alarms notify `life-platform-alerts` SNS, treat missing data as not breaching

### Test Results
- `test_mcp_registry.py`: 7/7 ✅
- `test_secret_references.py`: 4/4 ✅

### Deployed
- `life-platform-mcp` ✅
- Duration alarms created via `deploy/create_duration_alarms.sh` ✅

---

## v3.7.35 — 2026-03-15: TB7-4 + R13-F05/F09/F12/F04 security hardening

### Summary
Security hardening sprint clearing the deadline-bound TB7-4 and four R13 findings. Secret permanently deleted, MCP auth made fail-closed, write rate limiting added, medical disclaimers injected, and a new CI linter prevents future Todoist-style secret reference bugs.

### Changes

**TB7-4 — `life-platform/api-keys` permanent deletion**
- Grep confirmed: all references were in `cdk/cdk.out/` (stale build artifacts), none in live source
- `aws secretsmanager delete-secret --force-delete-without-recovery` executed ✅
- Secret ARN `arn:aws:secretsmanager:us-west-2:205930651321:secret:life-platform/api-keys-t2ADCR` permanently gone

**R13-F05 — MCP OAuth fail-closed**
- `mcp/handler.py` `_get_bearer_token()`: returns sentinel `"__NO_KEY_CONFIGURED__"` instead of `None` when no API key is set
- `_validate_bearer()`: removed `if expected is None: return True` accept-all bypass
- Result: no API key configured → all requests rejected (was: all requests accepted)

**R13-F12 — Write tool rate limiting**
- `mcp/handler.py`: `_check_write_rate_limit()` added; 10 calls/invocation cap on 5 write tools
- Protected tools: `create_todoist_task`, `delete_todoist_task`, `log_supplement`, `write_platform_memory`, `delete_platform_memory`
- `mcp/utils.py`: `RATE_LIMIT` error code + default suggestions added

**R13-F09 — Medical disclaimers on health-assessment tools (partial)**
- `mcp/tools_health.py`: `_disclaimer` field injected via `tool_get_health()` dispatcher (covers dashboard, risk_profile, trajectory views)
- `mcp/tools_health.py`: `tool_get_readiness_score()` return dict gets `_disclaimer` directly
- `mcp/tools_cgm.py`: `_disclaimer` field injected via `tool_get_cgm()` dispatcher (covers dashboard, fasting views)
- BP dashboard + HR recovery tools not found in local source — carry to next session

**R13-F04 — CI secret reference linter**
- `tests/test_secret_references.py` (new): SR1–SR4 tests scan `lambdas/`, `mcp/`, `mcp_server.py` for secret name literals
  - SR1: all referenced names must be in KNOWN_SECRETS
  - SR2: no references to deleted secrets
  - SR3: all names follow `life-platform/*` convention
  - SR4: scanner sanity check (guards against silent false-green)
- `.github/workflows/ci-cd.yml`: new test step wired into CI `test` job after IAM/secrets linter
- All 4 tests pass ✅

### Test Results
- `test_secret_references.py`: 4/4 ✅
- `test_mcp_registry.py`: 7/7 ✅

### Deployed
- `life-platform-mcp` ✅

---

## v3.7.34 — 2026-03-15: R5 power-tuning + inbox hygiene (OK alarm removal)

### Summary
Two improvements from the same session. R5: AWS Lambda Power Tuning identified 768 MB as cost-optimal for `life-platform-mcp` (25% cheaper than the live 1024 MB setting). Inbox hygiene: removed OK recovery notifications from all Lambda alarms — inbox now only receives actionable alerts.

### Changes
- `cdk/stacks/mcp_stack.py`: MCP server + warmer both updated from 512 MB (CDK) / 1024 MB (live drift) → 768 MB. Comment notes power-tuning result.
- `cdk/stacks/lambda_helpers.py`: removed `alarm.add_ok_action()` — all CDK-managed Lambda alarms now ALARM-only
- `deploy/create_withings_oauth_alarm.sh`: removed `--ok-actions` flag
- `deploy/sync_doc_metadata.py`: `secret_count` updated 11→10, `DATA_DICTIONARY.md` rule removed (archived), `secrets_cost_note` updated
- Live Withings alarm updated directly in AWS (OK action removed)
- `npx cdk deploy LifePlatformMcp` ✅ — deployed in 30s

### Power Tuning Results
| Memory | Cost/invocation | Duration |
|--------|----------------|----------|
| 512 MB | higher | slower |
| **768 MB** | **$0.00000029 ✅ cheapest** | **21.8ms** |
| 1024 MB | ~25% more expensive | faster |
| 1536 MB | most expensive | fastest |

Visualization: https://lambda-power-tuning.show/#AAIAAwAEAAY=;yf+RQ65HrkHXo7NBA93VQw==;GCslNs+VmzRpcs80CGA1Nw==

---

## v3.7.33 — 2026-03-15: R48 doc consolidation (25 → 22 docs)

### Summary
Doc consolidation sprint. DATA_DICTIONARY merged into SCHEMA (SOT domains, metric overlap map, three-tier filtering, known data gaps added as header sections). FEATURES + USER_GUIDE replaced with fresh PLATFORM_GUIDE.md (accurate at v3.7.32, organized by domain, includes query guide and troubleshooting). ARCHITECTURE.md doc index updated.

### Changes
- `docs/SCHEMA.md` renamed to `Schema & Data Dictionary` — prepended SOT domains table, metric overlap map, three-tier filtering, and known data gaps sections from DATA_DICTIONARY.md
- `docs/PLATFORM_GUIDE.md` (new) — combines feature guide (organized by domain), natural language query guide (query → tool mappings for all domains), data update procedures, and troubleshooting. Replaces FEATURES.md (v2.91.0, stale) and USER_GUIDE.md (v2.91.0, stale).
- `docs/DATA_DICTIONARY.md` → archived to `docs/archive/DATA_DICTIONARY_archived_v3.7.32.md`
- `docs/FEATURES.md` → archived to `docs/archive/FEATURES_archived_v3.7.32.md`
- `docs/USER_GUIDE.md` → archived to `docs/archive/USER_GUIDE_archived_v3.7.32.md`
- `docs/ARCHITECTURE.md` doc index updated to reflect new structure

### Doc count
25 → 22 active docs (3 archived, 1 new)

---

## v3.7.32 — 2026-03-15: R20 webhook-key deletion + doc audit fixes

### Summary
R20 secrets consolidation: `webhook-key` scheduled for deletion (7-day recovery window, permanent ~2026-03-22). No Lambda ever read this secret. Saves ~$0.40/mo. Also patched PROJECT_PLAN.md and INFRASTRUCTURE.md with several stale fields found in post-session doc audit.

### Changes
- `docs/INFRASTRUCTURE.md`: `webhook-key` marked for deletion, secrets count 11→10, Lambda count corrected (44 = 43 CDK + 1 Edge), `evening-nudge` and `failure-pattern-compute` and `google-calendar-ingestion` added to Lambda lists
- `docs/PROJECT_PLAN.md`: version header updated to v3.7.31, Risk-7 and ADR-027 marked done, Key Metrics corrected (tools 89, lambdas 43), completed items table updated with today's work
- AWS: `life-platform/webhook-key` scheduled for deletion (7-day recovery window)

### Deployed
- No Lambda changes — documentation + secrets management only

---

## v3.7.31 — 2026-03-15: R57 centenarian benchmarks + R6 timeout + R54 evening nudge + R6

### Summary
Four features from the buildable backlog. R57: Attia centenarian decathlon tool benchmarks compound lifts against longevity targets. R6: 30s per-tool soft timeout prevents Lambda hard-timeout on broad scans. R54: Evening nudge Lambda checks supplement/journal/How We Feel completeness at 8 PM and sends reminder if anything’s missing. R1 confirmed already done (daily_brief v2.82.0 reads pre-computed metrics). Scripts written for R20 (secrets consolidation audit) and R5 (Power Tuning instructions).

### Changes

**R57 — `mcp/strength_helpers.py`**
- Added `_ATTIA_TARGETS` dict: 4 lifts (deadlift 2.0×BW, squat 1.75×, bench 1.5×, OHP 1.0×) with minimum/target/elite ratios + centenarian projection at 85.
- Added `_ATTIA_STATUS_TIERS`: exceeds_target / at_target / approaching / progressing / below_minimum.
- Added `attia_benchmark_status(lift_key, bw_ratio)` — returns full status dict with pct_of_target, gap, labels.

**R57 — `mcp/tools_strength.py`**
- Added `tool_get_centenarian_benchmarks(args)` — queries Hevy data for 4 compound lifts, fetches Withings BW, computes Attia benchmark status for each, returns overall % of targets + priority lift.

**R57 — `mcp/registry.py`**
- Changed `from mcp.tools_strength import *` to explicit imports (avoids namespace pollution).
- Added `get_centenarian_benchmarks` tool entry.

**R6 — `mcp/handler.py`**
- Added `import concurrent.futures`.
- Wrapped tool call in `ThreadPoolExecutor` with 30s timeout. On `TimeoutError`, returns `mcp_error(QUERY_TOO_BROAD)` instead of letting the Lambda time out at 300s.
- Exception handling and EMF metric emission preserved.

**R54 — `lambdas/evening_nudge_lambda.py`** (new)
- Checks 3 sources: supplements (DDB supplements partition), journal (Notion DDB query), How We Feel (apple_health state_of_mind fields + state_of_mind partition).
- Only sends email if at least 1 source is incomplete — no email on fully complete days.
- HTML email: amber header, amber nudge bar, missing items table, complete items below fold, quick-action guide.

**R54 — `cdk/stacks/email_stack.py`**
- Added `EveningNudge` Lambda: `evening-nudge`, schedule `cron(0 3 * * ? *)` (8:00 PM PDT), 60s timeout, 256 MB.

**R54 — `cdk/stacks/role_policies.py`**
- Added `email_evening_nudge()`: DDB GetItem+Query, KMS, SES, DLQ. No ai-keys (no AI calls).

**R20 — `deploy/consolidate_secrets.sh`** (new)
- Audit script: lists all secrets, checks whether any Lambda reads `life-platform/habitify` or `life-platform/webhook-key` directly. Prints deletion commands to run after confirmation.

### R1 confirmed done
R1 (split daily brief compute from render) was completed in v2.82.0. `daily_brief_lambda.py` reads from `computed_metrics` partition written by `daily-metrics-compute`. Inline fallback exists only as a safety net. Marking done in tracker.

### Deployed
- `life-platform-mcp` (R57 centenarian tool + R6 timeout) ✅ **pending — run deploy**
- `evening-nudge` Lambda ✅ **pending — `cd cdk && npx cdk deploy LifePlatformEmail`**

### Terminal commands to run
```bash
# 1. Run Risk-7 alarm (script already written, just needs executing)
bash deploy/create_compute_staleness_alarm.sh

# 2. Build new MCP stable Layer (ADR-027) + follow CDK update prompt
bash deploy/build_mcp_stable_layer.sh

# 3. Deploy MCP Lambda (R57 + R6)
bash deploy/deploy_and_verify.sh life-platform-mcp lambdas/mcp_server.py

# 4. Deploy evening-nudge via CDK
cd cdk && npx cdk deploy LifePlatformEmail && cd ..

# 5. Run secrets consolidation audit (R20 — read-only, no deletes)
bash deploy/consolidate_secrets.sh
```

### R5 (Lambda Power Tuning)
Run the AWS Lambda Power Tuning SAR tool against `life-platform-mcp`:
```bash
# Deploy the Power Tuning SAR (one-time)
aws serverlessrepo create-cloud-formation-change-set \
  --application-id arn:aws:serverlessrepo:us-east-1:451282441545:applications/aws-lambda-power-tuning \
  --stack-name lambda-power-tuning \
  --capabilities CAPABILITY_IAM \
  --region us-west-2

# Then invoke it targeting life-platform-mcp:
# Use the Step Functions console at:
# https://us-west-2.console.aws.amazon.com/states/home?region=us-west-2#/statemachines
# Input: {"lambdaARN": "arn:aws:lambda:us-west-2:205930651321:function:life-platform-mcp",
#          "powerValues": [512, 768, 1024, 1536],
#          "num": 10, "payload": {}, "parallelInvocation": true}
```

---

## v3.7.30 — 2026-03-15: R31 + R55 + R49 (review tracker closure)

### Summary
Review tracker sweep. 9 items verified already done in code (tracker was behind v3.7.x work). Net new: R31 MCP error standardisation, R55 Withings OAuth alarm, R49 three new docs. Review tracker now at 38/51 (75%) with only 7 low-priority TODOs remaining.

### Changes

**R31 — `mcp/utils.py` v1.1.0**
- Added `mcp_error(message, error_code, suggestions, detail)` — canonical error response factory for all MCP tools.
- Added `ERROR_CODES` dict with 7 codes: NO_DATA, DATE_RANGE, MISSING_ARG, SOURCE_UNAVAIL, PARTIAL_DATA, QUERY_TOO_BROAD, INTERNAL.
- Added `_default_suggestions(error_code)` — per-code recovery hints Claude can act on.
- Added `from typing import Any` import.

**R31 — `mcp/handler.py`**
- Imported `mcp_error` from `mcp.utils`.
- `handle_tools_call`: changed bare `raise` on tool exception to structured `mcp_error()` response returned as MCP content. Claude now always sees `{error, error_code, suggestions}` instead of a raw JSON-RPC -32603.
- Exception still logged with `exc_info=True` for CloudWatch visibility.

**R55 — `deploy/create_withings_oauth_alarm.sh`** (new)
- CloudWatch alarm `withings-oauth-consecutive-errors`: fires on ≥1 Withings Lambda error for 2 consecutive days.
- `TreatMissingData=notBreaching` — won't fire during maintenance mode or holidays.
- OK-action also wired to SNS (clears alert when Lambda recovers).
- Alarm description includes re-auth command for fast on-call response.
- **Run this script to deploy the alarm.**

**R49 — `docs/ONBOARDING.md`** (new)
- "Start here" doc: system overview, key mental models (single-table DDB, pipeline timing, CDK ownership), data sources table, dev setup, common tasks quick-reference, troubleshooting table, session handover protocol.

**R49 — `deploy/README.md`** (new)
- Deploy script catalog: all 20 active scripts with purpose + when-to-use.
- Step-by-step Lambda deploy procedures (standard, MCP special zip, Garmin native deps).
- CDK deploy guide with all 8 stack names and what they own.
- Alarm script and maintenance mode references.
- Archive policy.

**R49 — `docs/DATA_FLOW_DIAGRAM.md`** (new)
- 7 Mermaid diagrams: full system overview, daily brief critical path (with times), DynamoDB key schema (ERD), MCP request sequence, OAuth token refresh flow, weekly email cadence (Gantt), alarm coverage topology.

**`docs/reviews/2026-02-28/09-recommendation-tracker.md`**
- Summary updated: 29→38 done, 16→7 TODO.
- R18, R31, R49 marked DONE. R48 noted as deferred to R14 review.
- Prioritized TODO list rewritten — 7 remaining items with honest P1/P2/P3 tiers.
- Session note added explaining tracker lag vs code reality.

### Deployed
- `life-platform-mcp` (mcp/utils.py v1.1.0 + handler.py R31 exception wrapping) ✅ 2026-03-15T05:43:17Z
- `withings-oauth-consecutive-errors` alarm ✅ 2026-03-15

---

## v3.7.29 — 2026-03-15: SEC-3 MEDIUM + CLEANUP-4 + ADR-027 utils.py

### Summary
Joint board review session. Four board-flagged items completed: SEC-3 MEDIUM date range validation utility created and wired into MCP handler; CLEANUP-4 live NameError bug fixed in ingestion_validator (Decimal import missing at module level); ADR-027 unblocked with mcp/utils.py as first stable-tier module; deploy/ directory verified lean at 20 scripts. CLEANUP-1 and CLEANUP-2 retroactively confirmed done from prior sessions.

### Changes

**SEC-3 MEDIUM — `mcp/utils.py` (new file)**
- `validate_date_range(start_date, end_date, max_days=365)`: enforces YYYY-MM-DD format, calendar validity, start<=end ordering, 365-day default span cap (730-day hard max). Prevents unbounded DynamoDB range scans from MCP tool date inputs.
- `validate_single_date(date_str)`: validates a single date arg for point-in-time tools.
- `_DATE_RE` compiled once at module load.
- Stable module listed in `build_mcp_stable_layer.sh` STABLE_MODULES for ADR-027 Layer tier.

**SEC-3 MEDIUM — `mcp/handler.py`**
- Added `from mcp.utils import validate_date_range, validate_single_date`
- `_validate_tool_args` step 4: auto-applies date range validation to all tools with `start_date`/`end_date` args, single-date validation to tools with `date` arg. Zero per-tool changes needed.

**CLEANUP-4 — `lambdas/ingestion_validator.py`**
- `from decimal import Decimal as _Decimal` added at module level (was completely absent — live NameError on any validated write with type-checked fields).
- Docstring updated: `ValidationSeverity` ref removed, `validate_and_write` added to USAGE.

**ADR-027 progress**
- `mcp/utils.py` is first stable-tier module explicitly created for the Layer.
- Full Layer rebuild (ADR-027 execution) deferred to Apr 13 with SIMP-1 Phase 2.

### Deployed
- `life-platform-mcp` (mcp/handler.py + mcp/utils.py) ✅

### Carry to April 13
- CLEANUP-3: Google Calendar OAuth (`python3 setup/setup_google_calendar_auth.py`)
- ADR-027 full execution: `bash deploy/build_mcp_stable_layer.sh` + CDK update + all Lambda redeploys
- Architecture Review #13 (`python3 deploy/generate_review_bundle.py` first)
- SIMP-1 Phase 2 (<=80 tools, EMF data gated)

---

## v3.7.28 — 2026-03-15: SEC-3 fix + CLEANUP-1

### Summary
SEC-3 HIGH finding resolved: `_load_cgm_readings` now validates `date_str` format and calendar validity before constructing the S3 key, closing the path traversal risk. CLEANUP-1 complete: `write_composite_scores()` dead code (69 lines) removed from `daily_metrics_compute_lambda.py` per ADR-025 — function was never called since v3.7.25.

... [TRUNCATED — 1396 lines omitted, 1796 total]


---

## 3. ARCHITECTURE

# Life Platform — Architecture

Last updated: 2026-03-15 (v3.7.40 — 89 tools, 31-module MCP package, 20 data sources, 43 Lambdas, 10 secrets, 49 alarms, 8 CDK stacks deployed)

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
│  Health Auto Export (webhook — CGM/Dexcom Stelo, BP, SoM)  │
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
│  MCP Server Lambda (89 tools, 1024 MB) + Lambda Function URL│
│  ← Claude Desktop + claude.ai + Claude mobile via remote MCP│
│                                                             │
│  COMPUTE LAYER (IC intelligence features)                   │
│  character-sheet-compute · adaptive-mode-compute            │
│  daily-metrics-compute · daily-insight-compute (IC-8)       │
│  hypothesis-engine v1.2.0 (IC-18+IC-19 D3B, Sunday 12 PM PT)                 │
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
│  CloudFront → S3 static website (OriginPath /dashboard)     │
│  index.html (daily) + clinical.html + data/clinical.json    │
│  Daily Brief writes data.json · Weekly Digest writes        │
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
| Lambda Function URL (MCP) | MCP HTTPS endpoint | `https://votqefkra435xwrccmapxxbj6y0jawgn.lambda-url.us-west-2.on.aws/` (AuthType NONE — auth handled in Lambda via API key header) |
| Lambda Function URL (remote MCP) | Remote MCP HTTPS endpoint | `https://c5hljblvma4u2xd6wf6oe4clk40unthu.lambda-url.us-west-2.on.aws` (OAuth 2.1 auto-approve + HMAC Bearer) |
| API Gateway | HTTP endpoint | `health-auto-export-api` (a76xwxt2wa) — webhook ingest |
| Secrets Manager | Credential store | 11 secrets: 4 OAuth (`whoop`, `withings`, `strava`, `garmin`) + `eightsleep` + `ai-keys` (Anthropic + MCP) + `ingestion-keys` (Notion/Todoist/Habitify/Dropbox/webhook keys bundle) + `habitify` (dedicated) + `webhook-key` + `mcp-api-key` — **`api-keys` permanently deleted 2026-03-14** |
| SNS topic | Alert routing | `life-platform-alerts` |
| CloudFront (dash) | CDN + auth | `EM5NPX6NJN095` (`d14jnhrgfrte42.cloudfront.net`) → S3 `/dashboard`, Lambda@Edge auth (`life-platform-cf-auth`), alias `dash.averagejoematt.com`. **Note (R8-LT6):** Lambda@Edge auth functions are manually managed outside CDK — `web_stack.py` has zero Lambda@Edge references. Intentionally left unmanaged: Lambda@Edge requires us-east-1 deployment which complicates CDK stack boundaries. Document-only; no CDK migration planned. |
| CloudFront (blog) | CDN (public) | `E1JOC1V6E6DDYI` (`d1aufb59hb2r1q.cloudfront.net`) → S3 `/blog`, NO auth, alias `blog.averagejoematt.com` |
| CloudFront (buddy) | CDN (public) | `ETTJ44FT0Z4GO` (`d1empeau04e0eg.cloudfront.net`) → S3 `/buddy`, **NO auth** (intentionally public — Tom's accountability page, no PII), alias `buddy.averagejoematt.com`, PriceClass_100, HTTP/2+3 |
| ACM Certificate | TLS | `arn:aws:acm:us-east-1:205930651321:certificate/8e560416-...` — `dash.averagejoematt.com` (DNS-validated) |
| SES Receipt Rule Set | Inbound email routing | `life-platform-inbound` (active) — rule `insight-capture` routes `insight@aws.mattsusername.com` → S3 |
| CloudWatch | Alarms + logs | **~49 metric alarms**, all Lambdas monitored |
| CDK | Infrastructure as Code | `cdk/` — 8 stacks deployed: **Core** (SQS DLQ + SNS + Layer), Ingestion, Compute, Email, Operational, Mcp, Monitoring, Web. CDK owns all 43 Lambda IAM roles + ~50 EventBridge rules. `cdk/stacks/lambda_helpers.py` uses `Code.from_asset("../lambdas")`. DDB + S3 deliberately unmanaged (stateful). |}
| CloudTrail | Audit logging | `life-platform-trail` → S3 |
| AWS Budget | Cost guardrail | $20/mo cap, alerts at 25%/50%/100% |

---

## Ingest Layer

### Scheduled ingestion (EventBridge → Lambda)

Each source has its own dedicated Lambda and IAM role. EventBridge triggers fire daily. All cron expressions use fixed UTC — **PT times shift by 1 hour when DST changes**.

**Gap-aware backfill (v2.46.0):** All 6 API-based ingestion Lambdas (Garmin, Whoop, Eight Sleep, Strava, Withings, Habitify) implement self-healing gap detection. On each scheduled run, the Lambda queries DynamoDB for the last N days (default 7, configurable via `LOOKBACK_DAYS` env var), identifies missing DATE# records, and fetches only those from the upstream API. Normal runs with no gaps cost 1 DynamoDB query and 0 extra API calls. Rate-limit pacing (0.5–1s) between gap-day fetches prevents upstream throttling. The pattern is self-bootstrapping — existing records are the reference point, no last-sync marker needed. Sources not at risk (Apple Health webhook, MacroFactor Dropbox polling, Notion, Weather, Todoist) do not need gap detection.

| Source | Lambda | EventBridge Rule | Cron (UTC) | PT (PDT) | IAM Role |
|---|---|---|---|---|---|
| Whoop | `whoop-data-ingestion` | `whoop-daily-ingestion` | `cron(0 14 * * ? *)` | 07:00 AM | `lambda-whoop-role` |
| Garmin | `garmin-data-ingestion` | `garmin-daily-ingestion` | `cron(0 14 * * ? *)` | 07:00 AM | `lambda-garmin-ingestion-role` |
| Notion Journal | `notion-journal-ingestion` | `notion-daily-ingest` | `cron(0 14 * * ? *)` | 07:00 AM | `lambda-notion-ingestion-role` |
| Withings | `withings-data-ingestion` | `withings-daily-ingestion` | `cron(15 14 * * ? *)` | 07:15 AM | `lambda-withings-role` |
| Habitify | `habitify-data-ingestion` | `habitify-daily-ingest` | `cron(15 14 * * ? *)` | 07:15 AM | `lambda-habitify-ingestion-role` |
| Strava | `strava-data-ingestion` | `strava-daily-ingestion` | `cron(30 14 * * ? *)` | 07:30 AM | `lambda-strava-role` |
| Journal Enrichment | `journal-enrichment` | `journal-enrichment-daily` | `cron(30 14 * * ? *)` | 07:30 AM | `lambda-journal-enrichment-role` |
| Todoist | `todoist-data-ingestion` | `todoist-daily-ingestion` | `cron(45 14 * * ? *)` | 07:45 AM | `lambda-todoist-role` |
| Eight Sleep | `eightsleep-data-ingestion` | `eightsleep-daily-ingestion` | `cron(0 15 * * ? *)` | 08:00 AM | `lambda-eightsleep-role` |
| Activity Enrichment | `activity-enrichment` | `activity-enrichment-nightly` | `cron(30 15 * * ? *)` | 08:30 AM | `lambda-enrichment-role` |
| MacroFactor | `macrofactor-data-ingestion` | `macrofactor-daily-ingestion` | `cron(0 16 * * ? *)` | 09:00 AM | `lambda-macrofactor-role` |
| Weather | `weather-data-ingestion` | `weather-daily-ingestion` | `cron(45 13 * * ? *)` | 06:45 AM | `lambda-weather-role` |
| Dropbox Poll | `dropbox-poll` | `dropbox-poll-schedule` | `rate(30 minutes)` | every 30m | `lambda-dropbox-poll-role` |

**DST note:** All EventBridge Rule crons use fixed UTC — times shift ±1hr at DST boundaries (PDT = UTC-7 Mar–Nov; PST = UTC-8 Nov–Mar). Tables above reflect PDT (UTC-7).

### Operational Lambdas (EventBridge → Lambda)

These are not data ingestion — they compute, alert, or deliver intelligence.

**Compute Lambdas (run before Daily Brief — compute → store → read pattern):**

| Function | Lambda | EventBridge Rule | Cron (UTC) | PT (PDT) | IAM Role |
|---|---|---|---|---|---|
| Character Sheet Compute | `character-sheet-compute` | `character-sheet-compute` | `cron(35 17 * * ? *)` | 10:35 AM | `life-platform-compute-role` |
| Adaptive Mode Compute | `adaptive-mode-compute` | `adaptive-mode-compute-daily` | `cron(30 17 * * ? *)` | 10:30 AM | `lambda-adaptive-mode-role` |
| Daily Metrics Compute | `daily-metrics-compute` | `daily-metrics-compute-daily` | `cron(25 17 * * ? *)` | 10:25 AM | `lambda-daily-metrics-role` |
| Daily Insight Compute (IC-8) | `daily-insight-compute` | `daily-insight-compute-daily` | `cron(20 17 * * ? *)` | 10:20 AM | `lambda-daily-insight-role` |
| Hypothesis Engine (IC-18) | `hypothesis-engine` | `hypothesis-engine-weekly` | `cron(0 19 ? * SUN *)` | Sun 12:00 PM | `lambda-hypothesis-engine-role` |
| Weekly Correlation Compute (R8-LT9) | `weekly-correlation-compute` | `WeeklyCorrelationComputeRule` | `cron(30 18 ? * SUN *)` | Sun 11:30 AM | CDK-generated role |

**Operational & Email Lambdas:**

| Function | Lambda | EventBridge Rule | Cron (UTC) | PT (PDT) | IAM Role |
|---|---|---|---|---|---|
| Anomaly Detector v2.1 | `anomaly-detector` | `anomaly-detector-daily` | `cron(5 16 * * ? *)` | 09:05 AM | `life-platform-email-role` |
| Cache Warmer (dedicated) | `life-platform-mcp-warmer` | CDK-managed warmer rule | `cron(0 17 * * ? *)` | 10:00 AM | CDK-generated role |
| Whoop Recovery Refresh | `whoop-data-ingestion` | `whoop-recovery-refresh` | `cron(30 17 * * ? *)` | 10:30 AM | `lambda-whoop-role` |
| Freshness Checker | `life-platform-freshness-checker` | `life-platform-freshness-check` | `cron(45 17 * * ? *)` | 10:45 AM | `lambda-freshness-checker-role` |
| Monday Compass | `monday-compass` | `monday-compass` | `cron(0 15 ? * MON *)` | Mon 08:00 AM | `lambda-monday-compass-role` |
| Daily Brief | `daily-brief` | `daily-brief-schedule` | `cron(0 18 * * ? *)` | 11:00 AM | `lambda-daily-brief-role` |
| Weekly Digest | `weekly-digest` | `weekly-digest-sunday` | `cron(0 16 ? * SUN *)` | Sun 09:00 AM | `lambda-weekly-digest-role-v2` |
| Monthly Digest | `monthly-digest` | `monthly-digest-schedule` | `cron(0 16 ? * 1#1 *)` | 1st Mon 9:00 AM | `lambda-monthly-digest-role` |
| Nutrition Review | `nutrition-review` | `nutrition-review-schedule` | `cron(0 17 ? * SAT *)` | Sat 10:00 AM | `lambda-nutrition-review-role` |
| Wednesday Chronicle | `wednesday-chronicle` | `wednesday-chronicle` | `cron(0 15 ? * WED *)` | Wed 08:00 AM | `lambda-wednesday-chronicle-role` |
| The Weekly Plate | `weekly-plate` | `weekly-plate-schedule` | `cron(0 2 ? * SAT *)` | Fri 07:00 PM | `lambda-weekly-plate-role` |
| Dashboard Refresh (2 PM) | `dashboard-refresh` | `dashboard-refresh-afternoon` | `cron(0 22 * * ? *)` | 03:00 PM | `lambda-mcp-server-role` |
| Dashboard Refresh (6 PM) | `dashboard-refresh` | `dashboard-refresh-evening` | `cron(0 2 * * ? *)` | 07:00 PM | `lambda-mcp-server-role` |
| MCP Key Rotator | `mcp-key-rotator` | Secrets Manager rotation | 90-day auto | — | `lambda-key-rotator-role` |
| QA Smoke | `qa-smoke` | on-demand | — | — | `lambda-qa-smoke-role` |
| Data Export | `data-export` | on-demand | — | — | `lambda-data-export-role` |

**Note:** As of v3.4.0 (PROD-1 CDK), all Lambdas have **CDK-owned** dedicated per-function IAM roles (43 roles, one per Lambda). All policies defined in `cdk/stacks/role_policies.py`. SEC-1 complete — no shared roles remain.

### File-triggered ingestion (S3 → Lambda)

| Source | Lambda | S3 Trigger Path | IAM Role |
|---|---|---|---|
| MacroFactor | `macrofactor-data-ingestion` | `s3://matthew-life-platform/uploads/macrofactor/*.csv` | `lambda-macrofactor-role` |
| Apple Health | `apple-health-ingestion` | `s3://matthew-life-platform/imports/apple_health/*.xml` | `lambda-apple-health-role` |

### Event-driven Lambdas (S3 trigger, no schedule)

| Function | Lambda | Trigger | IAM Role |
|---|---|---|---|
| Insight Email Parser | `insight-email-parser` | S3 `raw/inbound_email/*` ObjectCreated | `lambda-insight-email-parser-role` |

**Insight Email Parser:** SES receives email at `insight@aws.mattsusername.com` → stores in S3 `raw/inbound_email/` → Lambda extracts reply text → saves to `USER#matthew#SOURCE#insights` with auto-tagging → sends confirmation. Security: ALLOWED_SENDERS whitelist.

### Webhook ingestion (API Gateway → Lambda)

| Source | Lambda | Endpoint | Auth |
|---|---|---|---|
| Health Auto Export | `health-auto-export-webhook` | `https://a76xwxt2wa.execute-api.us-west-2.amazonaws.com/ingest` | Bearer token (`life-platform/ingestion-keys` → `health_auto_export_api_key`) |

**Three-tier source filtering (v1.1.0):**
- Tier 1 (Apple-exclusive): steps, active/basal energy, gait metrics, flights, distance, headphone audio, water intake, caffeine
- Tier 2 (cross-device): HR, RHR, HRV, respiratory rate, SpO2 — filtered to Apple Watch/iPhone sources only
- Tier 3 (skip): nutrition (MacroFactor SOT), sleep environment (Eight Sleep SOT), body comp (Withings SOT)
- **Sleep SOT (v2.55.0):** Sleep duration/staging/score/efficiency → Whoop. Eight Sleep → bed environment only.
- **Webhook v1.4.0:** Blood pressure metrics (systolic, diastolic, pulse). Individual readings in S3 `raw/blood_pressure/`.
- **Webhook v1.5.0:** State of Mind detection. Check-ins in S3 `raw/state_of_mind/`, daily aggregates in DynamoDB.

**⚠️ `apple-health-ingestion` (S3 XML trigger) is a separate legacy Lambda — NOT the webhook. Debug webhook issues in `health-auto-export-webhook` logs.**

### Failure handling

DLQ coverage: all async Lambdas → `life-platform-ingestion-dlq` (SQS). Request/response pattern Lambdas (`life-platform-mcp`, `health-auto-export-webhook`) excluded. CloudWatch metric alarms: **~49 total**, all Lambdas monitored. Alarm actions → SNS `life-platform-alerts`. 24-hour evaluation period, `TreatMissingData: notBreaching`.

**Additional failure safeguards (v3.1.3):**
- **DLQ Consumer Lambda** (`dlq-consumer`): Drains `life-platform-ingestion-dlq` on a schedule, logs failed message details to CloudWatch with structured context for triage.
- **Canary Lambda** (`life-platform-canary`): Synthetic health check — writes a test record, reads it back, deletes it. Fires every 30 min. Alarms if roundtrip fails.
- **Item size guard** (`item_size_guard.py`): Intercepts all DDB `put_item` calls in ingestion Lambdas; truncates oversized items, emits `ItemSizeWarning` CloudWatch metric before write.

### OAuth token management

Whoop, Withings, Strava, Garmin: OAuth2 with self-healing refresh tokens. Each Lambda reads secret → calls API → on expiry, refreshes → writes updated credentials back to Secrets Manager. Eight Sleep: username/password JWT, refreshed each invocation. Notion, Todoist, Habitify: static API keys bundled in `life-platform/ingestion-keys` (COST-B pattern — single secret with per-service key fields). Habitify also has a dedicated secret (`life-platform/habitify`) per ADR-014. Dropbox poll and Health Auto Export webhook also read from `ingestion-keys`. See ADR-014 for the dedicated-vs-bundled governing principle.

---

## Store Layer

### S3 — raw data

```
s3://matthew-life-platform/
  dashboard/
    index.html                        ← daily dashboard (public read, CloudFront cached)
    clinical.html                     ← clinical summary (public read)
    data.json                         ← written by Daily Brief Lambda
    clinical.json                     ← written by Weekly Digest Lambda
  config/
    board_of_directors.json           ← 13-member expert panel (read by all email Lambdas via board_loader.py)
    character_sheet.json              ← Character Sheet config: pillar weights, tiers, XP, cross-pillar effects
    project_pillar_map.json           ← Todoist project → platform pillar mapping (Monday Compass)
    profile.json                      ← user profile (targets, habits, phases)
  raw/
    whoop/2026/02/22/response.json
    cgm_readings/2026/02/25.json      ← MCP reads this for glucose tools
    health_auto_export/2026/02/25_*.json
    inbound_email/<ses-message-id>    ← SES inbound (triggers insight-email-parser)
    state_of_mind/2026/02/27.json     ← How We Feel check-ins
    blood_pressure/2026/02/25.json    ← Individual BP readings
    ...
  uploads/
    macrofactor/*.csv                 ← triggers macrofactor Lambda
  imports/
    apple_health/*.xml                ← triggers apple-health Lambda
```

### DynamoDB — normalised data

Table: `life-platform` (us-west-2) | Single-table | On-demand billing | Deletion protection | PITR (35-day) | TTL on `ttl` attribute (cache partition)

```
PK (partition key):  USER#matthew#SOURCE#<source>
SK (sort key):       DATE#YYYY-MM-DD
```

**Key partitions:**
```
USER#matthew#SOURCE#whoop              DATE#YYYY-MM-DD   → Whoop recovery
USER#matthew#SOURCE#day_grade          DATE#YYYY-MM-DD   → Day grade + components
USER#matthew#SOURCE#habit_scores       DATE#YYYY-MM-DD   → Tier-weighted habit scores
USER#matthew#SOURCE#character_sheet    DATE#YYYY-MM-DD   → Character Sheet RPG scoring
USER#matthew#SOURCE#computed_metrics   DATE#YYYY-MM-DD   → Readiness, HRV, TSB (pre-computed)
USER#matthew#SOURCE#platform_memory    MEMORY#<type>#YYYY-MM-DD → IC feature outputs (IC-8 etc.)
USER#matthew#SOURCE#insights           INSIGHT#<ISO-ts>  → Insights ledger (IC-15/16)
USER#matthew#SOURCE#hypotheses         HYPOTHESIS#<ts>   → Hypothesis engine outputs (IC-18)
USER#matthew                           PROFILE#v1        → User profile/settings
CACHE#matthew                          TOOL#<cache_key>  → MCP pre-computed cache (TTL 26h)
```

No GSI by design — all access patterns served by PK+SK queries.

**⚠️ 400KB item size limit:** Monitor Strava activities, MacroFactor food_log, Apple Health records.

---

## Serve Layer

### MCP Server

**Lambda:** `life-platform-mcp` | **Tools:** 88 | **Memory:** 1024 MB | **Modules:** 31
**Local endpoint:** `https://votqefkra435xwrccmapxxbj6y0jawgn.lambda-url.us-west-2.on.aws/`
**Remote MCP:** `https://c5hljblvma4u2xd6wf6oe4clk40unthu.lambda-url.us-west-2.on.aws` — OAuth 2.1 auto-approve + HMAC Bearer (enables claude.ai + mobile)
**Auth:** `x-api-key` header check; key in `life-platform/ai-keys`
**Protocol:** JSON-RPC 2.0 / MCP spec 2025-06-18

31-module package structure:
```
mcp/
  handler.py, config.py, utils.py, core.py, helpers.py
  labs_helpers.py, strength_helpers.py, registry.py, warmer.py
  tools_sleep, tools_health, tools_training, tools_nutrition
  tools_habits, tools_cgm, tools_labs, tools_journal, tools_lifestyle
  tools_social, tools_strength, tools_correlation, tools_character
  tools_board, tools_decisions, tools_adaptive, tools_hypotheses
  tools_memory, tools_data, tools_todoist
```

Cold start: ~700–800ms. Warm: 23–30ms. Cached tools: <100ms.

**IAM role:** `lambda-mcp-server-role` — DynamoDB `GetItem`, `Query`, `PutItem` (cache writes); S3 `GetObject` on `raw/cgm_readings/*`. No `Scan`, no `DeleteItem`.

### Cache warmer

EventBridge triggers MCP Lambda at 10:00 AM PDT daily (`source: aws.events`). Pre-computes 13 tools → `CACHE#matthew` partition, 26-hour TTL. Runtime: ~90s (13 steps).

Cached tools (SIMP-1 updated, v3.7.18–19): `get_longitudinal_summary` (aggregate year + month), `get_longitudinal_summary` (records), `get_longitudinal_summary` (seasonal), `get_health` (dashboard), `get_health` (risk_profile), `get_health` (trajectory), `get_habits` (dashboard), `get_training` (load), `get_training` (periodization), `get_training` (recommendation), `get_character` (sheet), `get_cgm` (dashboard). Steps 9-13 added v3.7.19.

### Email / Intelligence cadence

**Daily (every day):**
| Lambda | Time (PDT) | Purpose |
|---|---|---|
| `anomaly-detector` v2.1 | 9:05 AM | Adaptive threshold anomaly detection (15 metrics, 7 sources). CV-based Z thresholds, day-of-week normalization, travel-aware suppression. |
| `daily-brief` v2.62 | 11:00 AM | 18-section brief: readiness, day grade + TL;DR, scorecard, weight phase, training, nutrition, habits, supplements, CGM spotlight, gait, weather, travel banner, blood pressure, guidance, journal coach, BoD insight, anomaly alert. 4 Haiku AI calls. Writes `dashboard/data.json` + `buddy/data.json`. |

**Weekly schedule:**
| Lambda | Day / Time (PDT) | Purpose |
|---|---|---|
| `monday-compass` v1.0 | Mon 8:00 AM | Forward-looking planning email. Todoist tasks by pillar, cross-pillar prioritization AI, overdue debt, Board Pro Tips, Keystone action. |
| `wednesday-chronicle` v1.1 | Wed 8:00 AM | "The Measured Life" — Elena Voss narrative journalism. Thesis-driven synthesis, Board interviews, S3 blog post. |

... [TRUNCATED — 172 lines omitted, 472 total]


---

## 4. INFRASTRUCTURE REFERENCE

# Life Platform — Infrastructure Reference

> Quick-reference for all URLs, IDs, and configuration. No secrets stored here.
> Last updated: 2026-03-15 (v3.7.40 — 43 Lambdas, 10 active secrets, 89 MCP tools, ~49 alarms)
> Note: `webhook-key` scheduled for deletion 2026-03-15 (7-day recovery window). Count reflects post-deletion state.

---

## AWS Account

| Field | Value |
|-------|-------|
| Account ID | `205930651321` |
| Region | `us-west-2` (Oregon) |
| Budget | $20/month (alerts at 25% / 50% / 100%) |
| CloudTrail | `life-platform-trail` → S3 |

---

## Domain & DNS

| Field | Value |
|-------|-------|
| Domain | `averagejoematt.com` |
| Registrar | *(check where you bought the domain — Namecheap, Google Domains, etc.)* |
| Hosted Zone ID | `Z063312432BPXQH9PVXAI` |
| Nameservers | `ns-214.awsdns-26.com` · `ns-1161.awsdns-17.org` · `ns-858.awsdns-43.net` · `ns-1678.awsdns-17.co.uk` |

### DNS Records

| Subdomain | Type | Target |
|-----------|------|--------|
| `dash.averagejoematt.com` | A (alias) | `d14jnhrgfrte42.cloudfront.net` |
| `blog.averagejoematt.com` | A (alias) | `d1aufb59hb2r1q.cloudfront.net` |
| `buddy.averagejoematt.com` | A (alias) | `d1empeau04e0eg.cloudfront.net` |

---

## Web Properties

| Property | URL | Auth | CloudFront ID |
|----------|-----|------|---------------|
| Dashboard | `https://dash.averagejoematt.com/` | Lambda@Edge password (`life-platform-cf-auth`) | `EM5NPX6NJN095` |
| Blog | `https://blog.averagejoematt.com/` | None (public) | `E1JOC1V6E6DDYI` |
| Buddy Page | `https://buddy.averagejoematt.com/` | Lambda@Edge password (`life-platform-buddy-auth`) | `ETTJ44FT0Z4GO` |

Dashboard and Buddy passwords are stored in **Secrets Manager** (not here).

---

## MCP Server

| Field | Value |
|-------|-------|
| Lambda | `life-platform-mcp` (1024 MB) |
| Function URL (remote) | `https://c5hljblvma4u2xd6wf6oe4clk40unthu.lambda-url.us-west-2.on.aws/` |
| Auth (remote) | HMAC Bearer token via `life-platform/mcp-api-key` secret (auto-rotates every 90 days) |
| Auth (local) | `mcp_bridge.py` → `.config.json` → Function URL |
| Tools | 89 across 31 modules |
| Cache warmer | 12 tools pre-computed nightly at 9:00 AM PT |

---

## API Gateway

| Field | Value |
|-------|-------|
| Name | `health-auto-export-api` |
| ID | `a76xwxt2wa` |
| Endpoint | `https://a76xwxt2wa.execute-api.us-west-2.amazonaws.com` |
| Purpose | Webhook ingestion for Health Auto Export (Apple Health CGM, BP, State of Mind) |

---

## S3

| Field | Value |
|-------|-------|
| Bucket | `matthew-life-platform` |
| Key prefixes | `raw/` (source data) · `dashboard/` (web dashboard) · `blog/` (Chronicle) · `buddy/` (accountability page) · `config/` (profile, board, character sheet) · `inbound-email/` (insight parser) · `avatar/` (pixel art sprites) |

---

## DynamoDB

| Field | Value |
|-------|-------|
| Table | `life-platform` |
| Key schema | PK: `USER#matthew#SOURCE#<source>` · SK: `DATE#YYYY-MM-DD` |
| Protection | Deletion protection ON · PITR enabled (35-day rolling) |
| Encryption | KMS CMK `alias/life-platform-dynamodb` (key `444438d1-a5e0-43b8-9391-3cd2d70dde4d`) · annual auto-rotation ON |
| Partitions (30) | whoop, eightsleep, garmin, strava, withings, habitify, macrofactor, apple_health, notion_journal, todoist, weather, supplements, cgm, labs, genome, dexa, day_grade, habit_scores, character_sheet, chronicle, coaching_insights, life_events, contacts, temptations, cold_heat_exposure, exercise_variety, adaptive_mode, platform_memory, insights, hypotheses |

---

## SES (Email)

| Field | Value |
|-------|-------|
| Sender / Recipient | `awsdev@mattsusername.com` |
| Inbound rule set | `life-platform-inbound` (active) |
| Inbound rule | `insight-capture` → routes `insight@aws.mattsusername.com` → S3 |

---

## SNS

| Field | Value |
|-------|-------|
| Alert topic | `life-platform-alerts` → email to `awsdev@mattsusername.com` |
| CloudWatch alarms | ~49 metric alarms (ALARM-only; base + invocation-count + DDB item size + canary + new Lambda alarms) |

---

## SQS

| Field | Value |
|-------|-------|
| Dead-letter queue | `life-platform-ingestion-dlq` |
| DLQ coverage | All ingestion Lambdas (MCP + webhook excluded — request/response pattern) |

---

## ACM Certificates (us-east-1, required by CloudFront)

| Domain | Purpose |
|--------|---------|
| `dash.averagejoematt.com` | Dashboard CloudFront |
| `blog.averagejoematt.com` | Blog CloudFront |
| `buddy.averagejoematt.com` | Buddy CloudFront |

All DNS-validated via Route 53 CNAME records.

---

## Secrets Manager (10 active secrets)

All under prefix `life-platform/`. No values stored in this doc — access via AWS console or CLI.

| Secret | Type | Fields / Notes |
|--------|------|----------------|
| `whoop` | OAuth | Auto-refreshed by Lambda |
| `eightsleep` | OAuth | Auto-refreshed by Lambda |
| `strava` | OAuth | Auto-refreshed by Lambda |
| `withings` | OAuth | Auto-refreshed by Lambda |
| `garmin` | Session | Auto-refreshed by Lambda |
| `ai-keys` | JSON bundle | `anthropic_api_key` + `mcp_api_key` (90-day auto-rotation) |
| `todoist` | API key | Todoist API token |
| `notion` | API key | Notion integration key + database ID |
| `habitify` | API key | Habitify API token. Own dedicated secret — NOT bundled in api-keys (different Lambda consumer set). |
| `google-calendar` | Google Calendar Lambda | OAuth2 refresh_token + client credentials. CMK-encrypted. Auto-refreshed by Lambda. Added v3.7.22. |
| ~~`webhook-key`~~ | ~~Reserved~~ | ~~**SCHEDULED FOR DELETION 2026-03-15** (recovery window 7 days). No Lambda ever read this secret (LastAccessed: None). Saves ~$0.40/mo.~~ |
| ~~`api-keys`~~ | ~~Legacy bundle~~ | ~~**PERMANENTLY DELETED 2026-03-14.** All Lambdas migrated to per-service secrets.~~ |

---

## Lambdas (44)

43 CDK-managed (us-west-2) + 1 Lambda@Edge (us-east-1)

### Ingestion (14)
`whoop-data-ingestion` · `eightsleep-data-ingestion` · `garmin-data-ingestion` · `strava-data-ingestion` · `withings-data-ingestion` · `habitify-data-ingestion` · `macrofactor-data-ingestion` · `notion-journal-ingestion` · `todoist-data-ingestion` · `weather-data-ingestion` · `health-auto-export-webhook` · `journal-enrichment` · `activity-enrichment` · `google-calendar-ingestion`

### Email / Digest (9)
`daily-brief` · `weekly-digest` · `monthly-digest` · `nutrition-review` · `wednesday-chronicle` · `weekly-plate` · `monday-compass` · `anomaly-detector` · `evening-nudge`

### Compute (6)
`character-sheet-compute` · `adaptive-mode-compute` · `daily-metrics-compute` · `daily-insight-compute` · `hypothesis-engine` · `failure-pattern-compute`

### Infrastructure (14)
`life-platform-freshness-checker` · `dropbox-poll` · `insight-email-parser` · `life-platform-key-rotator` · `dashboard-refresh` · `life-platform-data-export` · `life-platform-qa-smoke` · `life-platform-mcp` · `life-platform-mcp-warmer` · `dlq-consumer` · `life-platform-canary` · `data-reconciliation` · `pip-audit` · `brittany-weekly-email`

### Lambda@Edge (us-east-1)
`life-platform-cf-auth` (dashboard) · `life-platform-buddy-auth` (buddy page)

---

## EventBridge

All rules CDK-managed as of v3.4.0 (PROD-1). IAM role: `life-platform-scheduler-role`.

| Field | Value |
|-------|-------|
| Timezone | `America/Los_Angeles` (DST-safe) |
| Schedules | 50+ total (see PROJECT_PLAN.md Ingestion Schedule for timing) |
| Old manual rules | Deleted in v3.4.0 migration |

---

## KMS

| Field | Value |
|-------|-------|
| Key alias | `alias/life-platform-dynamodb` |
| Key ID | `444438d1-a5e0-43b8-9391-3cd2d70dde4d` |
| Key ARN | `arn:aws:kms:us-west-2:205930651321:key/444438d1-a5e0-43b8-9391-3cd2d70dde4d` |
| Purpose | DynamoDB table `life-platform` SSE (server-side encryption) |
| Rotation | Annual auto-rotation ON |
| Key policy | Root admin + all Lambda execution roles + DynamoDB service principal |
| CloudTrail | Every Decrypt/GenerateDataKey call logged |

... [TRUNCATED — 32 lines omitted, 232 total]


---

## 5. ARCHITECTURE DECISIONS (ADRs)

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


---

## 6. SLOs

# Life Platform — Service Level Objectives (SLOs)

> OBS-3: Formal SLO definitions for critical platform paths.
> Last updated: 2026-03-15 (v3.7.40)

---

## Overview

Four SLOs define the platform's reliability contract. Each SLO has a measurable Service Level Indicator (SLI), a target, and a CloudWatch alarm that fires on breach.

All SLO alarms publish to `life-platform-alerts` SNS topic. The operational dashboard (`life-platform-ops`) includes an SLO tracking widget section.

---

## SLO Definitions

### SLO-1: Daily Brief Delivery

| Field | Value |
|-------|-------|
| **SLI** | Daily Brief Lambda completes without error |
| **Target** | 99% (≤3 missed days per year) |
| **Window** | Rolling 30-day |
| **Alarm** | `slo-daily-brief-delivery` — fires if Daily Brief Lambda errors ≥1 in a 24-hour period |
| **Metric** | `AWS/Lambda::Errors` for `daily-brief`, Sum, 24h period |
| **Recovery** | Check CloudWatch logs → fix code or data issue → re-invoke manually |

**Why 99% not 99.9%:** Single-user platform with no revenue SLA. 99% allows for the occasional bad deploy or upstream API outage without false-alarming. One missed day is annoying, not dangerous.

---

### SLO-2: Data Source Freshness

| Field | Value |
|-------|-------|
| **SLI** | Number of monitored data sources with data older than 48 hours |
| **Target** | 99% of checks show 0 stale sources |
| **Window** | Rolling 30-day |
| **Alarm** | `slo-source-freshness` — fires if `StaleSourceCount > 0` for 2 consecutive checks |
| **Metric** | `LifePlatform/Freshness::StaleSourceCount`, custom metric emitted by `freshness_checker_lambda.py` |
| **Recovery** | Identify stale source → check ingestion Lambda logs → fix auth/API issue → manually invoke |

**Monitored sources (10):** Whoop, Withings, Strava, Todoist, Apple Health, Eight Sleep, MacroFactor, Garmin, Habitify, Google Calendar.

**Why 48h threshold:** Many sources only sync once daily. A 24h threshold would false-alarm on normal timezone drift. 48h catches genuine failures while tolerating expected gaps (e.g., no MacroFactor data on a day Matthew doesn't log food).

---

### SLO-3: MCP Availability

| Field | Value |
|-------|-------|
| **SLI** | MCP Lambda invocations that complete without error |
| **Target** | 99.5% |
| **Window** | Rolling 7-day |
| **Alarm** | `slo-mcp-availability` — fires if MCP Lambda error rate exceeds 0.5% over 1 hour |
| **Metric** | `AWS/Lambda::Errors` / `AWS/Lambda::Invocations` for `life-platform-mcp` |
| **Recovery** | Check CloudWatch logs → redeploy from last-known-good code |

**Why 99.5%:** MCP is the interactive query layer — errors directly block Claude from answering questions. Higher bar than batch email Lambdas.

**Cold start note:** Cold starts (~700-800ms) are not errors. The SLI measures availability (error-free completion), not latency. A separate informational metric tracks p95 duration.

---

### SLO-4: AI Coaching Success

| Field | Value |
|-------|-------|
| **SLI** | Anthropic API calls that return a valid response |
| **Target** | 99% |
| **Window** | Rolling 7-day |
| **Alarm** | `slo-ai-coaching-success` — fires if `AnthropicAPIFailure` count exceeds 2 in a 24-hour period |
| **Metric** | `LifePlatform/AI::AnthropicAPIFailure` (already emitted by `ai_calls.py`) |
| **Recovery** | Check Anthropic status page → if upstream outage, wait. If code issue, fix prompt/parsing |

**Why count-based not rate-based:** The platform makes ~15-20 AI calls/day across all Lambdas. A rate-based alarm with so few datapoints would be noisy. A count threshold of 2 failures/day means something is systematically wrong (not just a transient 429).

---

## CloudWatch Dashboard Widgets

The `life-platform-ops` dashboard includes an "SLO Health" section with:

1. **SLO Status Panel** — 4 metric widgets showing current alarm states
2. **Daily Brief Success Rate** — 30-day graph of daily-brief errors
3. **Source Freshness Trend** — 30-day graph of stale source count
4. **MCP Error Rate** — 7-day graph of MCP error count
5. **AI Failure Trend** — 7-day graph of Anthropic API failures

---

## SLO Review Cadence

- **Weekly:** Glance at ops dashboard SLO section during Weekly Digest review
- **Monthly:** Review any SLO breaches in Monthly Digest (future integration)
- **Quarterly:** Review whether SLO targets need adjustment based on platform growth

---

... [TRUNCATED — 11 lines omitted, 111 total]


---

## 7. INCIDENT LOG

# Life Platform — Incident Log

Last updated: 2026-03-13 (v3.7.10)

> Tracks operational incidents, outages, and bugs that affected data flow or system behavior.
> For full details on any incident, check the corresponding CHANGELOG entry or handover file.

---

## Severity Levels

| Level | Definition |
|-------|------------|
| **P1 — Critical** | System broken, no data flowing or MCP completely down |
| **P2 — High** | Major feature broken, data loss risk, or multi-day data gap |
| **P3 — Medium** | Single source affected, degraded but functional |
| **P4 — Low** | Cosmetic, minor data quality, or transient error |

---

## Incident History

| Date | Severity | Summary | Root Cause | TTD* | TTR* | Data Loss? |
|------|----------|---------|------------|------|------|------------|
| 2026-03-12 | **P3** | Mar 12 alarm storm — 20+ ALARM/OK emails in 24h across todoist, daily-insight-compute, failure-pattern-compute, monday-compass, DLQ, freshness | CDK drift: `TodoistIngestionRole` missing `s3:PutObject` on `raw/todoist/*`. Policy correct in `role_policies.py` but never applied to AWS (likely stale from COST-B bundling refactor). Todoist Lambda threw `AccessDenied` on every invocation → cascading staleness alarms. | Alarm emails (real-time) | ~1 day (detected next session) — `cdk deploy LifePlatformIngestion` (54s) | No — Todoist data gap Mar 12 only. No backfill attempted (single day, non-critical). |
| 2026-03-12 | **P4** | `freshness_checker_lambda.py` duplicate sick-day suppression block silently breaking sick-day alert suppression | Copy-paste bug: sick-day block duplicated, second copy reset `_sick_suppress = False` after first set it `True`. Suppression never fired on sick days. | Code review during incident investigation | Fixed in v3.7.10 — awaiting deploy |
| 2026-02-28 | **P1** | 5 of 6 API ingestion Lambdas failing after engineering hardening (v2.43.0) | Handler mismatches (4 Lambdas had `lambda_function.py` but handlers pointed to `X_lambda.lambda_handler`), Garmin missing deps + IAM, Withings cascading OAuth expiry | ~hours (next scheduled run) | ~2 hr (sequential fixes) | No — gap-aware backfill self-healed all missing data. Full PIR: `docs/PIR-2026-02-28-ingestion-outage.md` |
| 2026-03-04 | P3 | character-sheet-compute failing with AccessDenied on S3 + DynamoDB | IAM role missing s3:GetObject on config bucket and dynamodb:PutItem permission. Lambda silently failing since deployment | ~1 day | 30 min | No (compute re-run via backfill) |
| 2026-02-25 | P4 | Day grade zero-score — journal and hydration dragging grades down | `score_journal` returned 0 instead of None when no entries; hydration noise <118ml scored | 1 day | 20 min | No (grades recalculated) |
| 2026-02-25 | P3 | Strava multi-device duplicate activities inflating movement score | WHOOP + Garmin recording same walk → duplicate in Strava | ~days | 30 min | No (dedup applied in brief; raw data retained) |
| 2026-03-10 | **P2** | All three web URLs (dash/blog/buddy) showing TLS cert error — `ERR_CERT_COMMON_NAME_INVALID` | `web_stack.py` had `CERT_ARN_* = None` placeholders — CDK deployed distributions without `viewer_certificate`, causing CloudFront to serve default `*.cloudfront.net` cert. Introduced during PROD-1 (v3.3.5). | Hours (noticed by user) | 15 min (v3.4.9) | No (data unaffected; all URLs inaccessible via HTTPS) |
| 2026-03-08 | **P3** | `todoist-data-ingestion` failing since 2026-03-06 | Stale `SECRET_NAME` env var (`life-platform/api-keys`) set on the Lambda — when api-keys was soft-deleted as part of secrets decomposition, the env var override started producing `ResourceNotFoundException`. Code default was correct but env var took precedence. DLQ consumer caught accumulated failures at 9:15 AM on 2026-03-08. | ~2 days | 15 min (env var removed + Lambda redeployed) | No — Todoist ingestion gap 2026-03-06 to 2026-03-08. Gap-aware backfill (7-day lookback) self-healed all missing task records on next run. |
| 2026-03-08 | **Info** | `data-reconciliation` first run reported RED: 17 gaps across 6 sources | Bootstrap noise, not real failures. First run has no prior reference point — all "gaps" were expected coldstart artifacts (MacroFactor real data only from 2026-02-22, habit gap 2025-11-10→2026-02-22, etc.). | First run | No action needed — monitor next 3 runs for convergence to GREEN | No |
| 2026-03-09 | **P2** | All 23 CDK-managed Lambdas broken after first CDK deploy (PROD-1, v3.3.5) | `Code.from_asset("..")` bundles files at `lambdas/X.py` inside a subdirectory, but Lambda expects `X.py` at zip root — causing `ImportModuleError` on every invocation. Affected: 7 Compute + 8 Email + 1 MCP + 7 Operational Lambdas. | Next scheduled run post-deploy | ~1 hr (`deploy/redeploy_all_cdk_lambdas.sh` redeployed all 23 via `deploy_lambda.sh`) | No — gap-aware backfill + DLQ drained. Permanent fix: update `lambda_helpers.py` to `Code.from_asset("../lambdas")` (tracked as TODO) |
| 2026-03-10 | **P1** | CDK IAM bulk migration — Lambda execution role gap during v3.4.0 deploy | CDK deleted 39 old IAM roles before confirming CDK-managed replacement roles were fully propagated and attached. Two email Lambdas (`wednesday-chronicle`, `nutrition-review`) had no execution role for ~5 min during the migration window, causing invocation failures on any warmup or invocation in that window. Root fix: `cdk deploy` sequencing — always verify role attachment before deleting old roles. *Identified retroactively during Architecture Review #4.* | Deploy logs (real-time) | ~15 min (CDK re-apply with `--force`) | No — no scheduled runs in migration window |
| 2026-03-10 | **P2** | CoreStack SQS DLQ ARN changed on CDK-managed recreation — DLQ send failures across all async Lambdas | CoreStack created a new CDK-managed DLQ (`life-platform-ingestion-dlq`) with a different ARN than the manually-created original. CDK-deployed Lambda env vars referenced the new ARN, but 3 Lambdas that had the old ARN cached in env var overrides (`SECRET_NAME`-style pattern) continued sending to the deleted queue. Result: DLQ send failures and silent dead-letter drop for ~30 min. *Identified retroactively during Architecture Review #4.* | CloudWatch errors (~30 min lag) | CDK update pushed correct ARN to all Lambda configs | Possible: some DLQ messages lost during gap window |
| 2026-03-10 | **P3** | EB rule recreation gap: 2 ingestion Lambdas missed scheduled morning runs during v3.4.0 migration | Old EventBridge rules deleted first; CDK replacements deployed after. 2 ingestion Lambdas (`withings-data-ingestion`, `eightsleep-data-ingestion`) missed their 7:15 AM / 8:00 AM PT windows during ~10 min gap between deletion and CDK rule creation. *Identified retroactively during Architecture Review #4.* | Freshness checker alert (10:45 AM) | Gap-aware backfill self-healed on next scheduled run | No — backfill recovered all missing data |
| 2026-03-10 | **P3** | Orphan Lambda adoption: `failure-pattern-compute` Sunday EB rule not included in CDK Compute stack definition | When 3 orphan Lambdas were adopted into CDK (v3.4.0), the `failure-pattern-compute` Sunday 9:50 AM EventBridge rule was omitted from the Compute stack definition. Lambda did not execute for ~1 week (one missed Sunday run). *Identified retroactively during Architecture Review #4.* | Architecture Review #4 inspection | EB rule added to CDK Compute stack | No — failure pattern memory records simply not generated for that week |
| 2026-03-10 | **P4** | Duplicate CloudWatch alarms after CDK Monitoring stack adoption of orphan Lambdas | CDK Monitoring stack created new alarms for 3 newly-adopted Lambdas (`failure-pattern-compute`, `brittany-email`, `sick-day-checker`) that already had manually-created alarms — resulting in 9 duplicate alarms with overlapping SNS notifications and alert fatigue. *Identified retroactively during Architecture Review #4.* | Architecture Review #4 alarm audit | Manual alarms deleted; CDK alarms authoritative | No |
| 2026-03-09 | **P2** | All 13 ingestion Lambdas failing with `AttributeError: 'Logger' object has no attribute 'set_date'` | After `platform_logger.py` added `set_date()` to support OBS-1 structured logging, ingestion Lambdas had stale bundled copies of `platform_logger.py` missing the new method. 14 DLQ messages accumulated. Affected: whoop, eightsleep, withings, strava, todoist, macrofactor, garmin, habitify, notion, journal-enrichment, dropbox-poll, weather, activity-enrichment. | DLQ depth alarm + CloudWatch errors | ~30 min (`deploy/redeploy_ingestion_with_logger.sh` redeployed all 13 with `--extra-files lambdas/platform_logger.py`). DLQ purged in v3.3.8. | No — gap-aware backfill recovered all ingestion gaps. |
| 2026-02-25 | P4 | Daily brief IAM — day grade PutItem AccessDeniedException | `lambda-weekly-digest-role` missing `dynamodb:PutItem` | Since v2.20.0 | 10 min | Grades not persisted until fixed |
| 2026-02-24 | P2 | Apple Health data not flowing — 2+ day gap | Investigated wrong Lambda (`apple-health-ingestion` vs `health-auto-export-webhook`) + deployment timing | ~2 days | 4 hr investigation, 15 min actual fix | No (S3 archives preserved, backfill recovered) |
| 2026-02-24 | P3 | Garmin Lambda pydantic_core binary mismatch | Wrong platform binary in deployment package | 1 day | 30 min | No |
| 2026-02-24 | P3 | Garmin data gap (Jan 19 – Feb 23) | Garmin app sync issue (Battery Saver mode suspected) | ~5 weeks | Backfill script | Partial (gap backfilled from Feb 23 forward) |
| 2026-02-23 | P4 | Habitify alarm in ALARM state | Transient Lambda networking error ("Cannot assign requested address") | Hours | Manual alarm reset | No (re-invoked successfully) |
| 2026-02-23 | P4 | DynamoDB TTL field name mismatch | Cache using `ttl_epoch` but TTL configured on `ttl` attribute | ~1 day | 5 min | No (cache items never expired, just accumulated) |
| 2026-02-23 | P4 | Weight projection sign error in weekly digest | Delta calculation reversed (showing gain as loss) | 1 day | 5 min | No |
| 2026-02-23 | P4 | MacroFactor hit rate denominator off | Division denominator using wrong field | 1 day | 5 min | No |
| 2026-03-11 | **P2** | Brittany email failing on all deploys since v3.5.1 | Two compounding bugs: (1) `deploy_obs1_ai3_apikeys.sh` used inline `zip` with path prefix — Lambda package contained `lambdas/brittany_email_lambda.py` at a subdirectory rather than root, causing `ImportModuleError` on every invocation; (2) `EmailStack` in CDK had no layer reference — all 8 email Lambdas silently running on `life-platform-shared-utils:2` (missing `set_date` method added in v4). Root principle violation: deploy scripts must always delegate to `deploy_lambda.sh` (which strips path via temp dir); never inline zip logic. | Manual test during v3.5.4 session | ~30 min (v3.5.5): fixed zip via `deploy_lambda.sh` re-deploy; added `SHARED_LAYER_ARN` + layer reference to all 8 email Lambdas in `email_stack.py`; `npx cdk deploy LifePlatformEmail` to apply | No — no Brittany emails sent since initial deploy; email content unaffected once fixed |
| 2026-03-11 | P3 | All 8 email Lambdas on stale layer v2 (missing `set_date`) since EmailStack CDK migration | EmailStack created in PROD-1 (v3.3.5) with no `layers=` parameter — all email Lambdas referenced zero layers and fell back to stale bundled copies of shared modules. `set_date()` method (added in platform_logger v2 for OBS-1 structured logging) was unavailable, causing silent `AttributeError` risk on any email Lambda that called it. No confirmed runtime failures because email Lambdas that bundled their own logger copy used the older API. Discovered during Brittany email debug. | Discovered during v3.5.5 investigation | Fixed in v3.5.5 via EmailStack CDK layer patch | No confirmed impact — no `set_date` calls confirmed in email Lambdas prior to v3.5.5 fix |

*TTD = Time to Detect, TTR = Time to Resolve

---

## Patterns & Observations

**Most common root causes:**
1. **Deployment errors** (wrong function ordering, missing IAM, wrong binary, CDK packaging, inline zip path prefix) — 8 incidents
2. **CDK drift** (IAM policies correct in code but not applied to AWS) — 3 incidents (Mar 12 Todoist, Mar 04 character-sheet, Mar 09 CDK packaging)
3. **Stale config / env var overrides** (SECRET_NAME env var pointing at deleted secret) — 3 incidents
4. **Wrong component investigated** (two Apple Health Lambdas, alarm dimension mismatch) — 3 incidents
5. **Missing infrastructure** (EventBridge rule never created, IAM missing permission, CDK stack missing layer reference) — 3 incidents
6. **Data quality / scoring logic** (zero-score defaults, dedup, sign errors) — 4 incidents

**CDK drift watch-out (new pattern as of v3.7.10):** IAM policy changes in `role_policies.py` only take effect when the relevant stack is deployed. After any refactor touching role policies (secrets consolidation, prefix changes, etc.), always redeploy the affected stack immediately and verify with a smoke invoke. Do not assume CDK state matches AWS state without a deploy.

**CDK packaging watch-out:** `Code.from_asset("..")` bundles source files one directory deep in the zip — Lambda can't find the handler. Always use `Code.from_asset("../lambdas")` (points at the lambdas directory directly). When CDK-managing Lambdas for the first time, verify a sample function works before assuming all 23 are healthy. `deploy_lambda.sh` is immune to this bug.

**Stale lambda module caches:** When a shared module (like `platform_logger.py`) adds new methods, all Lambdas that bundle their own copy of that file need to be redeployed. CDK packaging re-bundles from source automatically; `deploy_lambda.sh --extra-files` is the manual equivalent for Lambdas not yet on CDK.

**Secrets consolidation watch-out:** When consolidating Secrets Manager entries, Lambdas with `SECRET_NAME` (or similar) set as explicit env vars will override code defaults and continue pointing at the deleted secret. Always audit Lambda env vars — not just code — when retiring secrets. Also verify key naming conventions match between old and new secret schemas.

**Key lesson (from RCA):** When data isn't flowing, check YOUR pipeline first (CloudWatch logs for the receiving Lambda), not the external dependency. Document the full request path so you investigate the right component.

---

## Open Monitoring Gaps

| Gap | Risk | Mitigation |
|-----|------|------------|
| No end-to-end data flow dashboard | Slow detection of silent failures | Freshness checker provides daily coverage |
| DLQ coverage: MCP + webhook excluded | Request/response pattern — DLQ not applicable | CloudWatch error alarms cover both |
| No webhook health check endpoint | Can't externally monitor webhook availability | CloudWatch alarm on zero invocations/24h |
| No duration/throttle alarms | Timeouts without errors go undetected | Daily brief and MCP are most at risk |
| No CDK drift detection | IAM policy changes in code may not be applied to AWS | Post-refactor: always redeploy + smoke verify affected stacks |

**Resolved gaps (v2.75.0):** All 29 Lambdas now have CloudWatch error alarms. 10 log groups now have 30-day retention. Deployment zip filename bug eliminated by `deploy_lambda.sh` auto-reading handler config from AWS.

**Resolved gaps (v3.1.x):** DLQ consumer Lambda (`dlq-consumer`) now drains and logs failures from `life-platform-ingestion-dlq` on a schedule — silent DLQ accumulation is now caught proactively. Canary Lambda (`life-platform-canary`) runs synthetic DDB+S3+MCP round-trip every 30 min with 4 CloudWatch alarms — end-to-end health check is now automated. `item_size_guard.py` monitors 400KB DDB write limits before they cause failures.


---

## 8. INTELLIGENCE LAYER

# Life Platform — Intelligence Layer

> Documents the Intelligence Compounding (IC) features: how the platform learns, remembers, and improves over time.
> For the IC roadmap and future phases, see PROJECT_PLAN.md (Tier 7).
> Last updated: 2026-03-09 (v3.3.9)

---

## Overview

The Intelligence Layer transforms the platform from a stateless data observer into a compounding intelligence engine. Rather than running the same analysis fresh each day and generating the same generic insight repeatedly, the IC system:

1. **Persists** insights and patterns to DynamoDB (`platform_memory`, `insights`, `decisions`, `hypotheses`)
2. **Compounds** — each new analysis reads previous findings as context
3. **Learns** Matthew's specific biology, psychology, and failure patterns over time
4. **Self-improves** — coaching calibration evolves as evidence accumulates

The architecture decision (ADR-016) is explicit: no vector store, no embeddings, no fine-tuning. Pure DynamoDB key-value + structured context injection + prompt engineering.

---

## Architecture

```
┌──────────────────────────────────────────────────────────────┐
│  PRE-COMPUTE PIPELINE (runs before Daily Brief)              │
│                                                              │
│  9:35 AM  character-sheet-compute                            │
│  9:40 AM  daily-metrics-compute → computed_metrics DDB       │
│  9:42 AM  daily-insight-compute → insight_data (JSON)        │
│           ├─ 7-day habit × outcome correlations              │
│           ├─ leading indicator flags                         │
│           ├─ platform_memory pull (relevant records)         │
│           └─ structured JSON handoff to Daily Brief          │
│                                                              │
│  SUNDAY   hypothesis-engine (11 AM PT)                       │
│           └─ cross-domain hypotheses → hypotheses DDB        │
└─────────────────────────────────┬────────────────────────────┘
                                  │ reads pre-computed data
┌─────────────────────────────────▼────────────────────────────┐
│  AI CALL LAYER (all email/digest Lambdas)                    │
│                                                              │
│  IC-3: Chain-of-thought two-pass (BoD + TL;DR)               │
│    Pass 1: identify patterns + causal chains (JSON)          │
│    Pass 2: write coaching output using Pass 1 analysis       │
│                                                              │
│  IC-7: Cross-pillar trade-off reasoning instruction          │
│  IC-23: Attention-weighted prompt budgeting (surprise score) │
│  IC-24: Data quality scoring (flag incomplete sources)       │
│  IC-25: Diminishing returns detection (per-pillar)           │
│  IC-17: Red Team / Contrarian Skeptic pass (anti-confirmation│
│          bias, challenges correlation claims)                │
└─────────────────────────────────┬────────────────────────────┘
                                  │ writes after generation
┌─────────────────────────────────▼────────────────────────────┐
│  MEMORY LAYER                                                │
│                                                              │
│  insight_writer.py (shared module in Lambda Layer)           │
│  → SOURCE#insights — universal write by all email Lambdas    │
│  → SOURCE#platform_memory — failure patterns, milestones,    │
│    intention tracking, what worked, coaching calibration      │
│  → SOURCE#decisions — platform decisions + outcomes          │
│  → SOURCE#hypotheses — weekly generated cross-domain hypotheses│
└──────────────────────────────────────────────────────────────┘
```

---

## Live IC Features (as of v3.3.9)

### IC-1: platform_memory Partition
**Status:** Live (v2.86.0)  
**What it does:** DDB partition `SOURCE#platform_memory`, SK `MEMORY#<category>#<date>`. The compounding substrate — structured memory written by compute Lambdas and digest Lambdas, read back into AI prompts as context. Enables "the last 4 weeks show X pattern" without re-querying raw data.

**Memory categories live:** `milestone_architecture`, `intention_tracking`  
**Memory categories coming:** `failure_patterns` (Month 2), `what_worked` (Month 3), `coaching_calibration` (Month 3), `personal_curves` (Month 4)

### IC-2: Daily Insight Compute Lambda
**Status:** Live (v2.86.0)  
**Lambda:** `daily-insight-compute` (9:42 AM PT)  
**What it does:** Pre-computes structured insight JSON before Daily Brief runs. Pulls 7 days of metrics, computes habit×outcome correlations, flags leading indicators, pulls relevant platform_memory records. Daily Brief receives curated intelligence rather than raw data.

**Key output fields in insight JSON:**
- `habit_outcome_correlations` — which habit completions correlate with better sleep/recovery
- `leading_indicators` — early warning signals (e.g., HRV declining 3 consecutive days)
- `memory_context` — relevant platform_memory records for today's conditions
- `data_quality` — per-source confidence scores (IC-24)
- `surprise_scores` — per-metric deviation from rolling baseline (IC-23)

### IC-3: Chain-of-Thought Two-Pass
**Status:** Live (v2.86.0)  
**What it does:** Board of Directors + TL;DR AI calls use two-pass reasoning. Pass 1 generates structured JSON identifying patterns and causal chains. Pass 2 writes coaching output using Pass 1 analysis. ~2× token cost but material quality improvement — model reasons before writing.

**Model routing (TB7-23, confirmed 2026-03-13):** Both Pass 1 (analysis) and Pass 2 (output) use `AI_MODEL` = `claude-sonnet-4-6` via `call_anthropic()` in `ai_calls.py`. There is **no quality asymmetry** between the two passes — both run on Sonnet. The Haiku reference at line 515 of `daily_insight_compute_lambda.py` is the IC-8 intent evaluator, which correctly uses Haiku (classification task, not coaching). IC-3 itself has no Haiku dependency.

### IC-6: Milestone Architecture
**Status:** Live (v2.86.0)  
**What it does:** 6 weight/health milestones with biological significance for Matthew stored in `platform_memory`. Surfaced in coaching when approaching each threshold. Example: "At 285 lbs: sleep apnea risk drops substantially (genome flag)." Converts abstract goal into biological waypoints.

**Current milestones:** 285 lbs (sleep apnea risk), 270 lbs (walking pace natural improvement), 250 lbs (Zone 2 accessible at real-workout pace), 225 lbs (FFMI crosses athletic range), 200 lbs (visceral fat normalization target), 185 lbs (goal weight).

### IC-7: Cross-Pillar Trade-off Reasoning
**Status:** Live (v2.89.0)  
**What it does:** Explicit instruction added to Board of Directors prompts to reason about trade-offs between pillars rather than analyzing each in isolation. Enables: "Movement is strong but Sleep is degrading — adding training volume at current TSB will compound sleep debt. Optimize sleep first."

### IC-8: Intent vs. Execution Gap
**Status:** Live (v2.90.0)  
**What it does:** Journal analysis pass comparing stated intentions ("going to meal prep Sunday") against next-day metrics. Builds personal intention-completion rate. Writes to `MEMORY#intention_tracking`. Coaching AI told when stated intentions have historically not been followed through.

### IC-15: Insight Ledger
**Status:** Live (v2.87.0)  
**What it does:** Universal write-on-generate — every email/digest Lambda appends a structured insight record to `SOURCE#insights` via `insight_writer.py` (shared Layer module). Accumulates the raw material for downstream IC features. Schema: pillar, data_sources, confidence, actionable flag, semantic tags, digest_type, generated_text hash (dedup).

### IC-16: Progressive Context — All Digests
**Status:** Live (v2.88.0)  
**What it does:** Weekly Digest, Monthly Digest, Chronicle, Nutrition Review, and Weekly Plate all retrieve recent high-value insights before generating. Weekly Digest gets 30-day window; Monthly gets quarterly; Chronicle gets narrative-relevant threads. Each digest reads as if written by someone who has followed Matthew for months. ~500-1,500 extra tokens per call.

### IC-17: Red Team / Contrarian Pass
**Status:** Live (v2.87.0)  
**What it does:** "The Skeptic" persona injected into Board of Directors calls. Explicitly tasked to challenge consensus — question whether correlations are causal, flag misleading data, identify when insights are obvious vs. genuinely novel. Counteracts single-model confirmation bias. Prompt-only change, zero cost.

### IC-18: Hypothesis Engine Lambda
**Status:** Live (v2.89.0)  
**Lambda:** `hypothesis-engine` (Sunday 11 AM PT)  
**What it does:** Weekly Lambda pulls 14 days of all-pillar data. Prompts Claude to identify non-obvious cross-domain correlations the existing 144 tools don't explicitly monitor. Writes hypothesis records to `SOURCE#hypotheses`. Subsequent insight compute + digest prompts told to watch for confirming/refuting evidence.

**Validation rules (v1.1.0):** Fields + domains + numeric criteria required. Dedup check against active hypotheses. 30-day hard expiry. Min 7 days sample. 3 confirming checks required for promotion to permanent check.

Access: `get_active_hypotheses`, `evaluate_hypothesis` MCP tools.

### IC-19: Decision Journal
**Status:** Live (v2.88.0)  
**What it does:** Tracks platform-guided decisions and their outcomes. `log_decision` MCP tool or inferred from journal + metrics. Builds trust-calibration dataset. Access via `log_decision`, `get_decision_journal`, `get_decision_effectiveness` MCP tools.

### IC-23: Attention-Weighted Prompt Budgeting
**Status:** Live (v2.88.0)  
**What it does:** Pre-processing step computes "surprise score" for every metric — deviation from personal rolling baseline. High-surprise metrics get expanded context in AI prompts; low-surprise ones compress to one line or are omitted. `_compute_surprise_scores(data, baselines)` returns metric → surprise_score (0-1). Information theory applied to prompt engineering.

### IC-24: Data Quality Scoring
**Status:** Live (v2.88.0)  
**What it does:** `_compute_data_quality(data)` runs before AI calls. Per-source confidence score based on completeness, recency, and consistency. Outputs compact quality block injected into prompts: "⚠️ Nutrition: 800 cal — likely incomplete (7d avg 1,750)". AI treats flagged sources with skepticism.

### IC-25: Diminishing Returns Detector
**Status:** Live (v2.88.0)  
**What it does:** Weekly computation of each pillar's score trajectory vs. effort (habit completion rate, active habit count). When high effort + flat trajectory detected, coaching redirects to highest-leverage pillar. "Sleep optimization is mature at 82 — your biggest lever is movement consistency at 45%."

---

## Prompt Architecture Standards


... [TRUNCATED — 235 lines omitted, 385 total]


---

## 9. TIER 8 HARDENING STATUS

[Tier 8 section not found in PROJECT_PLAN.md]


---

## 10. CDK / IaC STATE

### cdk/app.py
```python

#!/usr/bin/env python3
"""
Life Platform CDK App — PROD-1: Infrastructure as Code

Stack architecture:
  core        → DynamoDB, S3, SQS DLQ, SNS alerts (imported existing resources)
  ingestion   → 13 ingestion Lambdas + EventBridge rules + IAM roles
  compute     → 5 compute Lambdas + EventBridge rules
  email       → 8 email/digest Lambdas + EventBridge rules
  operational → Operational Lambdas (anomaly, freshness, canary, dlq-consumer, etc.)
  mcp         → MCP Lambda + Function URLs (local + remote)
  web         → CloudFront (3 distributions) + ACM certificates
  monitoring  → CloudWatch alarms + ops dashboard + SLO alarms

Deployment:
  cdk bootstrap aws://205930651321/us-west-2
  cdk deploy LifePlatformCore
  cdk deploy LifePlatformIngestion
  cdk deploy LifePlatformCompute
  cdk deploy LifePlatformEmail
  cdk deploy LifePlatformOperational
  cdk deploy LifePlatformMcp
  cdk deploy LifePlatformWeb         # requires us-east-1 cert ARNs
  cdk deploy LifePlatformMonitoring

To import existing resources (first time only):
  cdk import LifePlatformCore
"""

import aws_cdk as cdk

from stacks.core_stack import CoreStack
from stacks.ingestion_stack import IngestionStack
from stacks.compute_stack import ComputeStack
from stacks.email_stack import EmailStack
from stacks.operational_stack import OperationalStack
from stacks.mcp_stack import McpStack
from stacks.web_stack import WebStack
from stacks.monitoring_stack import MonitoringStack

app = cdk.App()

# Read context values
account = app.node.try_get_context("account") or "205930651321"
region = app.node.try_get_context("region") or "us-west-2"

env = cdk.Environment(account=account, region=region)

# ── Core infrastructure (DynamoDB, S3, SQS, SNS) ──
core = CoreStack(app, "LifePlatformCore", env=env)

# ── All 8 stacks wired ──
# Each stack receives core.table, core.bucket, core.dlq, core.alerts_topic
# as cross-stack references.
#
ingestion = IngestionStack(app, "LifePlatformIngestion", env=env,
    table=core.table, bucket=core.bucket, dlq=core.dlq,
    alerts_topic=core.alerts_topic)
# ingestion stack wired ✅
#
compute = ComputeStack(app, "LifePlatformCompute", env=env,
    table=core.table, bucket=core.bucket, dlq=core.dlq,
    alerts_topic=core.alerts_topic)
# compute stack wired ✅
#
email = EmailStack(app, "LifePlatformEmail", env=env,
    table=core.table, bucket=core.bucket, dlq=core.dlq,
    alerts_topic=core.alerts_topic)
# email stack wired ✅
#
operational = OperationalStack(app, "LifePlatformOperational", env=env,
    table=core.table, bucket=core.bucket, dlq=core.dlq,
    alerts_topic=core.alerts_topic)
# operational stack wired ✅
#
mcp = McpStack(app, "LifePlatformMcp", env=env,
    table=core.table, bucket=core.bucket)
# mcp stack wired ✅
#
web = WebStack(app, "LifePlatformWeb",
    env=cdk.Environment(account=account, region="us-east-1"))  # CloudFront requires us-east-1
# web stack wired ✅
#
monitoring = MonitoringStack(app, "LifePlatformMonitoring", env=env,
    alerts_topic=core.alerts_topic)
# monitoring stack wired ✅

app.synth()

```


### cdk/stacks/lambda_helpers.py (first 80 lines)
```python

"""
lambda_helpers.py — Shared Lambda construction patterns for CDK stacks.

Provides a helper function that creates a Lambda function with all the
standard Life Platform conventions:
  - Per-function IAM role with explicit least-privilege policies
  - DLQ configured
  - Environment variables (TABLE_NAME, S3_BUCKET, USER_ID)
  - CloudWatch error alarm
  - Handler auto-detection from source file
  - Shared Layer attachment (optional)

v2.0 (v3.4.0): Added custom_policies parameter to replace existing_role_arn.
  CDK now OWNS all IAM roles — no more from_role_arn references.
  Migration: existing_role_arn is DEPRECATED and will be removed in a future version.

Usage in a stack:
    from stacks.lambda_helpers import create_platform_lambda
    from stacks.role_policies import ingestion_policies

    fn = create_platform_lambda(
        self, "WhoopIngestion",
        function_name="whoop-data-ingestion",
        source_file="lambdas/whoop_lambda.py",
        handler="whoop_lambda.lambda_handler",
        table=core.table,
        bucket=core.bucket,
        dlq=core.dlq,
        custom_policies=ingestion_policies("whoop"),
        schedule="cron(0 14 * * ? *)",
        timeout_seconds=120,
    )
"""

from aws_cdk import (
    Duration,
    aws_lambda as _lambda,
    aws_iam as iam,
    aws_sqs as sqs,
    aws_events as events,
    aws_events_targets as targets,
    aws_cloudwatch as cloudwatch,
    aws_cloudwatch_actions as cw_actions,
    aws_sns as sns,
    aws_dynamodb as dynamodb,
    aws_s3 as s3,
)
from constructs import Construct


def create_platform_lambda(
    scope: Construct,
    id: str,
    function_name: str,
    source_file: str,
    handler: str,
    table: dynamodb.ITable,
    bucket: s3.IBucket,
    dlq: sqs.IQueue = None,
    alerts_topic: sns.ITopic = None,
    alarm_name: str = None,
    secrets: list[str] = None,
    schedule: str = None,
    timeout_seconds: int = 120,
    memory_mb: int = 256,
    environment: dict = None,
    shared_layer: _lambda.ILayerVersion = None,
    additional_layers: list = None,
    # ── Legacy parameter (DEPRECATED — use custom_policies instead) ──
    existing_role_arn: str = None,
    # ── Fine-grained IAM (v2.0) ──
    custom_policies: list[iam.PolicyStatement] = None,
    # ── Legacy broad-permission flags (used when neither existing_role_arn nor custom_policies) ──
    ddb_write: bool = True,
    s3_write: bool = True,
    needs_ses: bool = False,
    ses_domain: str = None,
    # ── Observability ──
    tracing: _lambda.Tracing = None,  # R13-XR: pass _lambda.Tracing.ACTIVE for X-Ray
) -> _lambda.Function:

... [TRUNCATED — 160 lines omitted, 240 total]

```


### cdk/stacks/role_policies.py (first 80 lines)
```python

"""
role_policies.py — Centralized IAM policy definitions for all Life Platform Lambdas.

Each function returns a list of iam.PolicyStatement objects that exactly
replicate the existing console-created per-function IAM roles from SEC-1.

Audit source: aws iam get-role-policy on all 37 lambda-* roles (2026-03-09).
Organized by CDK stack: ingestion, compute, email, operational, mcp.

Policy principle: least-privilege per Lambda. No shared roles.
"""

from aws_cdk import aws_iam as iam

# ── Constants ──────────────────────────────────────────────────────────────
ACCT = "205930651321"
REGION = "us-west-2"
TABLE_ARN = f"arn:aws:dynamodb:{REGION}:{ACCT}:table/life-platform"
BUCKET = "matthew-life-platform"
BUCKET_ARN = f"arn:aws:s3:::{BUCKET}"
DLQ_ARN = f"arn:aws:sqs:{REGION}:{ACCT}:life-platform-ingestion-dlq"
KMS_KEY_ARN = f"arn:aws:kms:{REGION}:{ACCT}:key/444438d1-a5e0-43b8-9391-3cd2d70dde4d"
SES_IDENTITY = f"arn:aws:ses:{REGION}:{ACCT}:identity/mattsusername.com"


def _secret_arn(name: str) -> str:
    """Secrets Manager ARN with wildcard suffix for version IDs."""
    return f"arn:aws:secretsmanager:{REGION}:{ACCT}:secret:{name}*"


def _s3(*prefixes: str) -> list[str]:
    """S3 object ARNs for the given key prefixes."""
    return [f"{BUCKET_ARN}/{p}" for p in prefixes]


# ═══════════════════════════════════════════════════════════════════════════
# INGESTION STACK — 15 Lambdas
# Pattern: DDB write, S3 raw/<source>/*, source-specific secret, DLQ
# ═══════════════════════════════════════════════════════════════════════════

def _ingestion_base(
    source: str,
    secret_name: str = None,
    s3_prefix: str = None,
    ddb_actions: list[str] = None,
    extra_secret_actions: list[str] = None,
    extra_s3_read: list[str] = None,
    extra_s3_write: list[str] = None,
    extra_statements: list[iam.PolicyStatement] = None,
    no_s3: bool = False,
    no_secret: bool = False,
) -> list[iam.PolicyStatement]:
    """Build standard ingestion role policies."""
    stmts = []

    # DynamoDB
    actions = ddb_actions or ["dynamodb:PutItem", "dynamodb:GetItem", "dynamodb:UpdateItem", "dynamodb:Query"]
    stmts.append(iam.PolicyStatement(
        sid="DynamoDB",
        actions=actions,
        resources=[TABLE_ARN],
    ))

    # KMS — required for all DDB operations (table is CMK-encrypted)
    stmts.append(iam.PolicyStatement(
        sid="KMS",
        actions=["kms:Decrypt", "kms:GenerateDataKey"],
        resources=[KMS_KEY_ARN],
    ))

    # S3 write (raw data)
    if not no_s3:
        prefix = s3_prefix or f"raw/matthew/{source}/*"
        write_resources = _s3(prefix) + (_s3(*extra_s3_write) if extra_s3_write else [])
        stmts.append(iam.PolicyStatement(
            sid="S3Write",
            actions=["s3:PutObject"],
            resources=write_resources,
        ))


... [TRUNCATED — 874 lines omitted, 954 total]

```


### .github/workflows/ci-cd.yml (FULL — proof of pipeline implementation)
```yaml

# Life Platform CI/CD Pipeline
# MAINT-4: Automated lint → deploy → smoke test on push to main
#
# Architecture:
#   1. Lint (flake8 + py_compile syntax check) — runs on every push, no AWS access needed
#   2. Plan — validates lambda_map.json, detects changed files, maps to Lambda functions
#   3. Deploy — requires manual approval (GitHub Environment: production)
#   4. Smoke test — invokes qa-smoke + canary, checks structured output
#   5. Auto-rollback — fires if smoke-test fails after a successful deploy (TB7-25)
#   6. Notify — posts to SNS on any failure
#
# AWS auth: OIDC federation (no long-lived keys)
# See deploy/setup_github_oidc.sh to create the IAM provider + role
#
# Changes from original (v3.5.8 → v3.6.0):
#   - Added py_compile syntax check step in Lint job
#   - Added lambda_map.json structural validation in Plan job
#   - Replaced sleep 10 with aws lambda wait function-updated (MCP + Lambda deploys)
#   - Added layer version verification after shared layer rebuild
#   - Fixed smoke test and canary to parse JSON output, not grep for "error"
#   - Added notify-failure job that posts to SNS life-platform-alerts on any failure
# Changes (v3.7.9):
#   - Added rollback-on-smoke-failure job (TB7-25): auto-rollback when smoke test fails
#     after a successful deploy. Calls deploy/rollback_lambda.sh for each deployed function.
#     Requires deploy_lambda.sh to have stored artifacts to s3://matthew-life-platform/deploys/

name: CI/CD

on:
  push:
    branches: [main]
    paths:
      - 'lambdas/**'
      - 'mcp/**'
      - 'mcp_server.py'
  workflow_dispatch:
    inputs:
      deploy_all:
        description: 'Deploy ALL Lambdas (skip change detection)'
        required: false
        type: boolean
        default: false

env:
  AWS_REGION: us-west-2
  LAMBDA_MAP: ci/lambda_map.json
  SNS_TOPIC_ARN: arn:aws:sns:us-west-2:205930651321:life-platform-alerts

permissions:
  id-token: write   # OIDC token for AWS
  contents: read    # Checkout code

jobs:
  # ════════════════════════════════════════════════════════════════
  # Job 1: Lint + Syntax Check
  # ════════════════════════════════════════════════════════════════
  lint:
    name: Lint + Syntax Check
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'

      - name: Install flake8
        run: pip install flake8

      - name: Run flake8
        run: |
          echo "::group::Linting lambdas/"
          flake8 lambdas/ --count --show-source --statistics || true
          echo "::endgroup::"

          echo "::group::Linting mcp/"
          flake8 mcp/ --count --show-source --statistics || true
          echo "::endgroup::"

          # Fail on syntax errors and undefined names; pass on style warnings
          flake8 lambdas/ mcp/ --count --select=E9,F63,F7,F82 --show-source --statistics

      - name: Syntax check (py_compile)
        # Catches broken syntax that flake8 misses (e.g. invalid f-strings, truncated files)
        run: |
          echo "::group::Syntax checking lambdas/ and mcp/"
          FAILED=0
          while IFS= read -r -d '' f; do
            if python3 -m py_compile "$f" 2>&1; then
              echo "  ✅ $f"
            else
              echo "  ❌ SYNTAX ERROR: $f"
              FAILED=$((FAILED + 1))
            fi
          done < <(find lambdas/ mcp/ -name '*.py' -print0)
          echo "::endgroup::"
          if [ "$FAILED" -gt 0 ]; then
            echo "::error::$FAILED file(s) failed syntax check"
            exit 1
          fi
          echo "✅ All files pass syntax check"

  # ════════════════════════════════════════════════════════════════
  # Job 2: Unit Tests — run pytest on tests/test_shared_modules.py
  # ════════════════════════════════════════════════════════════════
  test:
    name: Unit Tests
    runs-on: ubuntu-latest
    needs: lint
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'

      - name: Install test dependencies
        run: pip install pytest

      - name: Run unit tests
        run: |
          echo "::group::Running tests/test_shared_modules.py"
          python3 -m pytest tests/test_shared_modules.py -v --tb=short
          echo "::endgroup::"

      - name: IAM policy linter (test_role_policies.py)
        run: |
          echo "::group::IAM policy linter"
          python3 -m pytest tests/test_role_policies.py -v --tb=short
          echo "::endgroup::"

      - name: CDK handler consistency linter (test_cdk_handler_consistency.py)
        run: |
          echo "::group::CDK handler consistency linter"
          python3 -m pytest tests/test_cdk_handler_consistency.py -v --tb=short
          echo "::endgroup::"

      - name: CDK S3 path linter (test_cdk_s3_paths.py)
        run: |
          echo "::group::CDK S3 path linter"
          python3 -m pytest tests/test_cdk_s3_paths.py -v --tb=short
          echo "::endgroup::"

      - name: Safety module wiring linter (test_wiring_coverage.py)
        run: |
          echo "::group::Wiring coverage linter"
          python3 -m pytest tests/test_wiring_coverage.py -v --tb=short
          echo "::endgroup::"

      - name: DynamoDB pattern linter (test_ddb_patterns.py)
        run: |
          echo "::group::DynamoDB pattern linter"
          python3 -m pytest tests/test_ddb_patterns.py -v --tb=short
          echo "::endgroup::"

      - name: MCP registry integrity linter (test_mcp_registry.py)
        run: |
          echo "::group::MCP registry integrity linter"
          python3 -m pytest tests/test_mcp_registry.py -v --tb=short
          echo "::endgroup::"

      - name: Lambda handler integration linter (test_lambda_handlers.py)
        # TB7-24: I1-I6 — file existence, syntax, handler signature, try/except, orphans, MCP entry point
        run: |
          echo "::group::Lambda handler integration linter"
          python3 -m pytest tests/test_lambda_handlers.py -v --tb=short
          echo "::endgroup::"

      - name: Deprecated secrets scan
        run: |
          echo "::group::Deprecated secrets scan"
          FAILED=0

          while IFS= read -r line; do
            secret=$(echo "$line" | sed 's/#.*//' | xargs)
            [ -z "$secret" ] && continue

            echo "Scanning for deprecated secret: $secret"
            MATCHES=$(grep -rn --include='*.py' --include='*.json' --include='*.yml' --include='*.yaml' --include='*.sh' "$secret" \
              lambdas/ mcp/ cdk/ .github/ ci/ \
              --exclude-dir='.venv' --exclude-dir='cdk.out' \
              2>/dev/null | grep -v 'deprecated_secrets.txt' | grep -v '^Binary')

            if [ -n "$MATCHES" ]; then
              echo "::error::Deprecated secret '$secret' still referenced:"
              echo "$MATCHES" | head -20
              FAILED=$((FAILED + 1))
            else
              echo "  ✅ No references to '$secret'"
            fi
          done < ci/deprecated_secrets.txt

          echo "::endgroup::"
          if [ "$FAILED" -gt 0 ]; then
            echo "::error::$FAILED deprecated secret(s) still referenced. Update to current secret names before merging."
            exit 1
          fi
          echo "✅ Deprecated secrets scan passed"

      - name: IAM/secrets consistency linter (test_iam_secrets_consistency.py)
        # R8-8: Cross-refs IAM secret ARN patterns against known-secrets list
        run: |
          echo "::group::IAM/secrets consistency linter"
          python3 -m pytest tests/test_iam_secrets_consistency.py -v --tb=short
          echo "::endgroup::"

      - name: Secret references linter (test_secret_references.py)
        # R13-F04: Validates Lambda source secret name literals against known-secrets list.
        # Prevents Todoist-style 2-day outage caused by wrong SECRET_NAME default value.
        run: |
          echo "::group::Secret references linter"
          python3 -m pytest tests/test_secret_references.py -v --tb=short
          echo "::endgroup::"

      - name: Layer version consistency linter (test_layer_version_consistency.py)
        # R13-F08: Offline check — verifies layer module files exist, no hardcoded ARNs,
        # and all consumers are wired in CDK. Complements the live AWS check in the Plan job.
        run: |
          echo "::group::Layer version consistency linter"
          python3 -m pytest tests/test_layer_version_consistency.py -v --tb=short
          echo "::endgroup::"

  # ════════════════════════════════════════════════════════════════
  # Job 3: Plan — validate map, detect changes, build deploy plan
  # ════════════════════════════════════════════════════════════════
  plan:
    name: Plan deployments
    runs-on: ubuntu-latest
    needs: [lint, test]
    outputs:
      deploy_matrix: ${{ steps.plan.outputs.matrix }}
      has_deploys: ${{ steps.plan.outputs.has_deploys }}
      layer_changed: ${{ steps.plan.outputs.layer_changed }}
      mcp_changed: ${{ steps.plan.outputs.mcp_changed }}
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 2  # Need HEAD~1 for diff

      - name: Validate lambda_map.json
        run: |
          echo "Validating ci/lambda_map.json..."
          MISSING=0

          echo "Checking Lambda source files..."
          while IFS= read -r src; do
            if [ ! -f "$src" ]; then
              echo "  ❌ MISSING source: $src (in .lambdas — file not found in repo)"
              MISSING=$((MISSING + 1))
            fi
          done < <(jq -r '.lambdas | keys[]' ci/lambda_map.json)

          echo "Checking shared layer modules..."
          while IFS= read -r mod; do
            if [ ! -f "$mod" ]; then
              echo "  ❌ MISSING layer module: $mod (in .shared_layer.modules — file not found)"
              MISSING=$((MISSING + 1))
            fi
          done < <(jq -r '.shared_layer.modules[]' ci/lambda_map.json)

          if [ "$MISSING" -gt 0 ]; then
            echo "::error::lambda_map.json references $MISSING missing file(s). Update ci/lambda_map.json to match current repo state."
            exit 1
          fi
          echo "✅ lambda_map.json valid — all source files present"

      - name: Configure AWS credentials (OIDC) — plan
        uses: aws-actions/configure-aws-credentials@v4
        with:
          role-to-assume: arn:aws:iam::205930651321:role/github-actions-deploy-role
          aws-region: ${{ env.AWS_REGION }}

      - name: CDK diff — detect IAM/infra drift
        run: |
          echo "::group::CDK diff"
          node --version
          npm install -g aws-cdk --quiet

          cd cdk
          python3 -m venv .venv --quiet
          source .venv/bin/activate
          pip install -r requirements.txt --quiet

          set +e
          npx cdk diff --all 2>&1 | tee /tmp/cdk_diff.txt
          CDK_EXIT=$?
          set -e

          echo "::endgroup::"

          if grep -q '\[-\]\|destroy\|Destroy' /tmp/cdk_diff.txt; then
            echo "::error::CDK diff detected resource DESTRUCTIONS — review before deploying:"
            grep '\[-\]\|destroy\|Destroy' /tmp/cdk_diff.txt | head -20
            exit 1
          fi

          if grep -qi 'iam\|policy\|role\|permission' /tmp/cdk_diff.txt; then
            echo "::error::CDK diff detected IAM/policy changes — R8-ST6 gate: review and approve manually before deploying."
            echo "Changes detected:"
            grep -i 'iam\|policy\|role\|permission' /tmp/cdk_diff.txt | head -20

... [TRUNCATED — 598 lines omitted, 898 total]

```


### Test suite — all test files with function names

**test_business_logic.py** (0 tests): 


**test_cdk_handler_consistency.py** (5 tests): test_h1_handler_and_source_always_paired, test_h2_all_source_files_exist, test_h3_handler_module_matches_source_file, test_h4_all_source_files_define_lambda_handler, test_h5_no_generic_lambda_function_handler


**test_cdk_s3_paths.py** (4 tests): test_s1_all_s3_prefixes_are_convention_or_documented, test_s2_exception_evidence_in_lambda_source, test_s3_exceptions_dont_use_convention_prefix, test_s4_no_hardcoded_matthew_in_iam_comments


**test_ddb_patterns.py** (4 tests): test_d1_pk_sk_format, test_d2_date_reserved_word_guarded, test_d3_schema_version_present, test_d4_put_item_guarded_by_validator


**test_dropbox.py** (0 tests): 


**test_dropbox2.py** (0 tests): 


**test_dropbox3.py** (0 tests): 


**test_dropbox_token.py** (0 tests): 


**test_habitify_api.py** (0 tests): 


**test_iam_secrets_consistency.py** (4 tests): test_s1_all_iam_secrets_are_known, test_s2_no_deleted_secrets_in_iam, test_s3_all_known_secrets_referenced, test_s4_known_secrets_count_matches_architecture


**test_integration_aws.py** (13 tests): test_i1_lambda_handlers_match_expected, test_i2_lambda_layer_version_current, test_i3_spot_check_lambda_invocability, test_i4_dynamodb_table_healthy, test_i5_required_secrets_exist, test_i6_eventbridge_rules_exist_and_enabled, test_i7_cloudwatch_alarms_exist, test_i8_s3_bucket_and_config_files, test_i9_dlq_empty, test_i10_mcp_lambda_responds, test_i11_data_reconciliation_running, test_i12_mcp_tool_call_response_shape, test_i13_freshness_checker_returns_valid_data


**test_lambda_handlers.py** (6 tests): test_i1_source_file_exists, test_i2_source_file_syntax_valid, test_i3_handler_signature, test_i4_handler_has_try_except, test_i5_no_orphaned_lambda_files, test_i6_mcp_server_handler


**test_layer_version_consistency.py** (5 tests): test_lv1_cdk_uses_layer_name_not_hardcoded_arn, test_lv2_all_consumers_referenced_in_cdk, test_lv3_all_layer_modules_exist_on_disk, test_lv5_layer_version_only_in_constants, test_lv4_consumer_count_sanity


**test_mcp_registry.py** (7 tests): test_r1_all_imports_resolve, test_r2_all_fn_references_exist, test_r3_schema_structure, test_r4_no_duplicate_tool_names, test_r5_tool_count_in_range, test_r6_registry_syntax_valid, test_r7_all_tool_modules_parseable


**test_role_policies.py** (7 tests): test_r1_ddb_read_requires_kms_decrypt, test_r2_ddb_write_requires_kms_generate, test_r3_kms_resource_is_scoped, test_r4_no_unexpected_wildcard_resources, test_r5_secrets_resources_are_scoped, test_r6_policy_is_non_empty, test_r7_no_duplicate_sids


**test_secret_references.py** (4 tests): test_sr1_all_secret_references_are_known, test_sr2_no_deleted_secret_references, test_sr3_secret_names_follow_convention, test_sr4_secret_references_found


**test_shared_modules.py** (66 tests): test_empty_blocked, test_none_blocked, test_too_short_blocked, test_truncated_blocked, test_good_text_passes, test_dangerous_training_red_recovery, test_aggressive_borderline_warns, test_low_cal_blocked, test_causation_warns, test_generic_phrases_warn, test_sanitized_text_fallback, test_sanitized_text_original, test_fallbacks_all_types, test_validate_json_none_blocked, test_validate_json_missing_key, test_validate_json_ok, test_get_logger_type, test_get_logger_singleton, test_set_date, test_set_correlation_id, test_info_json_output, test_positional_args, test_helpers_no_raise, test_check_sick_day_none, test_check_sick_day_found, test_check_sick_day_decimal, test_check_sick_day_ddb_error, test_get_sick_days_range_empty, test_get_sick_days_range_error, test_write_sick_day_fields, test_write_sick_day_no_reason, test_delete_sick_day, test_d2f_decimal, test_d2f_nested, test_avg_basic, test_avg_none_ignored, test_avg_empty, test_avg_all_none, test_fmt_value, test_fmt_none, test_fmt_with_unit, test_fmt_num, test_fmt_num_none, test_safe_float_present, test_safe_float_missing, test_safe_float_default, test_dedup_different_sports, test_dedup_removes_duplicate, test_dedup_empty, test_normalize_whoop_sleep, test_ex_whoop_from_list, test_ex_whoop_empty, test_ex_withings_latest, test_banister_zero_input, test_banister_with_training, test_validate_whoop_ok, test_validate_whoop_out_of_range, test_validate_empty_record, test_validation_result_structure, test_list_supported_sources, test_call_anthropic_has_output_type_param, test_ai_validator_importable, test_ai_output_type_importable, test_bod_caller_passes_output_type, test_journal_caller_passes_output_type, test_email_lambdas_dont_call_anthropic_directly


**test_wiring_coverage.py** (4 tests): test_w1_platform_logger_imported, test_w2_ingestion_validator_wired, test_w3_ai_output_validator_wired, test_w4_no_causal_language_in_prompts


### CDK stack files: compute_stack.py, constants.py, core_stack.py, email_stack.py, ingestion_stack.py, lambda_helpers.py, mcp_stack.py, monitoring_stack.py, operational_stack.py, role_policies.py, web_stack.py


---

## 11. SOURCE CODE INVENTORY

### lambdas/ (59 .py files, 0 other files)

**Python files:** adaptive_mode_lambda.py, ai_calls.py, ai_output_validator.py, anomaly_detector_lambda.py, apple_health_lambda.py, board_loader.py, brittany_email_lambda.py, canary_lambda.py, character_engine.py, character_sheet_lambda.py, daily_brief_lambda.py, daily_insight_compute_lambda.py, daily_metrics_compute_lambda.py, dashboard_refresh_lambda.py, data_export_lambda.py, data_reconciliation_lambda.py, digest_utils.py, dlq_consumer_lambda.py, dropbox_poll_lambda.py, eightsleep_lambda.py, enrichment_lambda.py, evening_nudge_lambda.py, failure_pattern_compute_lambda.py, freshness_checker_lambda.py, garmin_lambda.py, google_calendar_lambda.py, habitify_lambda.py, health_auto_export_lambda.py, html_builder.py, hypothesis_engine_lambda.py, ingestion_framework.py, ingestion_validator.py, insight_email_parser_lambda.py, insight_writer.py, item_size_guard.py, journal_enrichment_lambda.py, key_rotator_lambda.py, macrofactor_lambda.py, mcp_server.py, monday_compass_lambda.py, monthly_digest_lambda.py, notion_lambda.py, nutrition_review_lambda.py, output_writers.py, pip_audit_lambda.py, platform_logger.py, qa_smoke_lambda.py, retry_utils.py, scoring_engine.py, sick_day_checker.py, strava_lambda.py, todoist_lambda.py, weather_handler.py, wednesday_chronicle_lambda.py, weekly_correlation_compute_lambda.py, weekly_digest_lambda.py, weekly_plate_lambda.py, whoop_lambda.py, withings_lambda.py


**Subdirectories:** __pycache__, buddy, cf-auth, dashboard, requirements


### deploy/ (25 files)

**Files:** MANIFEST.md, README.md, SMOKE_TEST_TEMPLATE.sh, apply_s3_lifecycle.sh, archive_onetime_scripts.sh, build_layer.sh, build_mcp_stable_layer.sh, canary_policy.json, consolidate_secrets.sh, create_compute_staleness_alarm.sh, create_duration_alarms.sh, create_lambda_edge_alarm.sh, create_mcp_canary_15min.sh, create_operational_dashboard.sh, create_withings_oauth_alarm.sh, deploy_and_verify.sh, deploy_lambda.sh, generate_review_bundle.py, maintenance_mode.sh, pitr_restore_drill.sh, post_cdk_reconcile_smoke.sh, post_cdk_smoke.sh, rollback_lambda.sh, smoke_test_cloudfront.sh, sync_doc_metadata.py


### mcp/ (32 modules)

**Modules:** __init__.py, config.py, core.py, handler.py, helpers.py, labs_helpers.py, registry.py, strength_helpers.py, tools_adaptive.py, tools_board.py, tools_calendar.py, tools_cgm.py, tools_character.py, tools_correlation.py, tools_data.py, tools_decisions.py, tools_habits.py, tools_health.py, tools_hypotheses.py, tools_journal.py, tools_labs.py, tools_lifestyle.py, tools_memory.py, tools_nutrition.py, tools_sick_days.py, tools_sleep.py, tools_social.py, tools_strength.py, tools_todoist.py, tools_training.py, utils.py, warmer.py


---

## 12. KEY SOURCE CODE SAMPLES

### daily_brief_lambda.py — Daily Brief orchestrator — most complex Lambda
```python

"""
Daily Brief Lambda — v2.82.0 (Compute refactor: reads pre-computed metrics from daily-metrics-compute Lambda)
Fires at 10:00am PT daily (18:00 UTC via EventBridge).

v2.2 changes:
  - MacroFactor workouts integration (exercise-level detail in Training Report)
  - Smart Guidance: AI-generated from all signals (replaces static table)
  - TL;DR line: single sentence under day grade
  - Weight: weekly delta callout
  - Sleep architecture: deep % + REM % in scorecard
  - Eight Sleep field name fixes (sleep_efficiency_pct, sleep_duration_hours)
  - Nutrition Report: meal timing in AI prompt
  - 4 AI calls: BoD, Training+Nutrition, Journal Coach, TL;DR+Guidance combined

v2.77.0 extraction:
  - html_builder.py   — build_html, hrv_trend_str, _section_error_html (~1,000 lines)
  - ai_calls.py       — all 4 AI call functions + data summary builders (~380 lines)
  - output_writers.py — write_dashboard_json, write_clinical_json, write_buddy_json,
                        evaluate_rewards, get_protocol_recs, sanitize_for_demo (~700 lines)
  Lambda shrinks from 4,002 → ~1,366 lines of orchestration logic.

Sections (15):
  1.  Day Grade + TL;DR (AI one-liner)
  2.  Yesterday's Scorecard (sleep architecture detail)
  3.  Readiness Signal
  4.  Training Report (exercise-level detail from MacroFactor workouts)
  5.  Nutrition Report (meal timing in AI prompt)
  6.  Habits Deep-Dive
  7.  CGM Spotlight (UPDATED: fasting proxy, hypo flag, 7-day trend)
  8.  Gait & Mobility (NEW: walking speed, step length, asymmetry, double support)
  9.  Habit Streaks
  10. Weight Phase Tracker (weekly delta callout)
  11. Today's Guidance (AI-generated smart guidance)
  12. Journal Pulse
  13. Journal Coach
  14. Board of Directors Insight
  15. Anomaly Alert

Profile-driven: all targets read from DynamoDB PROFILE#v1. No hardcoded constants.
4 AI calls: Board of Directors, Training+Nutrition Coach, Journal Coach, TL;DR+Guidance.

v2.54.0: Board of Directors prompt dynamically built from s3://matthew-life-platform/config/board_of_directors.json
         Falls back to hardcoded _FALLBACK_BOD_PROMPT if S3 config unavailable.
"""

import json
import os
import math
import time
import boto3
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from decimal import Decimal

# -- Configuration from environment variables (with backwards-compatible defaults) --
_REGION    = os.environ.get("AWS_REGION", "us-west-2")
TABLE_NAME = os.environ.get("TABLE_NAME", "life-platform")
S3_BUCKET  = os.environ["S3_BUCKET"]
USER_ID    = os.environ["USER_ID"]
RECIPIENT  = os.environ["EMAIL_RECIPIENT"]
SENDER     = os.environ["EMAIL_SENDER"]
ANTHROPIC_SECRET = os.environ.get("ANTHROPIC_SECRET", "life-platform/ai-keys")

USER_PREFIX = f"USER#{USER_ID}#SOURCE#"
PROFILE_PK  = f"USER#{USER_ID}"

# -- AWS clients ---------------------------------------------------------------
dynamodb = boto3.resource("dynamodb", region_name=_REGION)
table    = dynamodb.Table(TABLE_NAME)
ses      = boto3.client("sesv2", region_name=_REGION)
s3       = boto3.client("s3", region_name=_REGION)
secrets  = boto3.client("secretsmanager", region_name=_REGION)

# Board of Directors config loader
try:
    import board_loader
    _HAS_BOARD_LOADER = True
except ImportError:
    _HAS_BOARD_LOADER = False

... [TRUNCATED — 1505 lines omitted, 1585 total]

```


### sick_day_checker.py — Sick day cross-cutting utility
```python

"""
Sick Day Checker — shared Lambda Layer utility.

Provides a lightweight DDB check so all Lambdas can test whether a given
date has been flagged as a sick/rest day without duplicating query logic.

DDB schema:
  pk  = USER#<user_id>#SOURCE#sick_days
  sk  = DATE#YYYY-MM-DD
  fields: date, reason (optional), logged_at, schema_version

Used by:
  character_sheet_lambda      — freeze EMA on sick days
  daily_metrics_compute_lambda — store grade="sick", preserve streaks
  anomaly_detector_lambda      — suppress alert emails
  freshness_checker_lambda     — suppress stale-source alerts
  daily_brief_lambda           — show recovery banner, skip coaching

v1.0.0 — 2026-03-09
"""

from datetime import datetime, timezone
from decimal import Decimal

SICK_DAYS_SOURCE = "sick_days"


def _d2f(obj):
    """Convert Decimal → float recursively."""
    if isinstance(obj, list):    return [_d2f(i) for i in obj]
    if isinstance(obj, dict):    return {k: _d2f(v) for k, v in obj.items()}
    if isinstance(obj, Decimal): return float(obj)
    return obj


def check_sick_day(table, user_id, date_str):
    """Return sick day record dict for *date_str*, or None if not flagged.

    Safe to call from any Lambda — returns None on any error rather than raising.
    """
    pk = f"USER#{user_id}#SOURCE#{SICK_DAYS_SOURCE}"
    sk = f"DATE#{date_str}"
    try:
        resp = table.get_item(Key={"pk": pk, "sk": sk})
        item = resp.get("Item")
        return _d2f(item) if item else None
    except Exception as e:
        print(f"[WARN] sick_day_checker.check_sick_day({date_str}): {e}")
        return None


def get_sick_days_range(table, user_id, start_date, end_date):
    """Return list of sick day record dicts within a date range (inclusive).

    Returns empty list on any error.
    """
    pk = f"USER#{user_id}#SOURCE#{SICK_DAYS_SOURCE}"
    try:
        resp = table.query(
            KeyConditionExpression="pk = :pk AND sk BETWEEN :s AND :e",
            ExpressionAttributeValues={
                ":pk": pk,
                ":s":  f"DATE#{start_date}",
                ":e":  f"DATE#{end_date}",
            },
        )
        return [_d2f(i) for i in resp.get("Items", [])]
    except Exception as e:
        print(f"[WARN] sick_day_checker.get_sick_days_range({start_date}→{end_date}): {e}")
        return []


def write_sick_day(table, user_id, date_str, reason=None):
    """Write a sick day record. Idempotent — safe to call multiple times for the same date."""
    pk = f"USER#{user_id}#SOURCE#{SICK_DAYS_SOURCE}"
    sk = f"DATE#{date_str}"
    item = {
        "pk":             pk,
        "sk":             sk,
        "date":           date_str,

... [TRUNCATED — 14 lines omitted, 94 total]

```


### platform_logger.py — Structured logging module
```python

"""
platform_logger.py — OBS-1: Structured JSON logging for all Life Platform Lambdas.

Shared module. Drop-in replacement for the stdlib `logging` pattern used across
all 37 Lambdas. Every log line becomes a structured JSON object that CloudWatch
Logs Insights can query, filter, and alarm on.

USAGE (replaces `logger = logging.getLogger(); logger.setLevel(logging.INFO)`):

    from platform_logger import get_logger
    logger = get_logger("daily-brief")           # source name = lambda function name
    logger.info("Sending email", subject=subject, grade=grade)
    logger.warning("Stale data", source="whoop", age_hours=4.2)
    logger.error("AI call failed", attempt=3, error=str(e))

    # Structured log emitted to CloudWatch:
    {
      "timestamp": "2026-03-08T18:00:01.234Z",
      "level": "INFO",
      "source": "daily-brief",
      "correlation_id": "daily-brief#2026-03-08",
      "lambda": "daily-brief",
      "message": "Sending email",
      "subject": "Morning Brief | Sun Mar 8 ...",
      "grade": "B+"
    }

CORRELATION ID:
  Set once per Lambda execution via logger.set_date(date_str).
  Pattern: "{source}#{date}" — enables cross-Lambda log grouping in CWL Insights.
  Example query: `filter correlation_id like "2026-03-08"` shows ALL Lambda executions
  for that date.

MIGRATION PATTERN (for Lambdas not yet migrated):
  Old: `logger.info("Sending email: " + subject)`
  New: `logger.info("Sending email", subject=subject)`
  — keyword args become top-level JSON fields (searchable in CWL Insights)

BACKWARD COMPATIBILITY:
  PlatformLogger inherits logging.Logger so existing `logger.info(msg)` calls
  (positional only) continue to work unchanged. Migration can be incremental.

v1.0.0 — 2026-03-08 (OBS-1)
v1.0.1 — 2026-03-10 — *args %s compat for all log methods (Bug B fix)
"""

import json
import logging
import os
import sys
import time
from datetime import datetime, timezone

# ── Constants ──────────────────────────────────────────────────────────────────
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()
_LAMBDA_NAME = os.environ.get("AWS_LAMBDA_FUNCTION_NAME", "unknown")
_LAMBDA_VERSION = os.environ.get("AWS_LAMBDA_FUNCTION_VERSION", "$LATEST")

# Map stdlib level names → integers (for external callers that pass strings)
_LEVEL_MAP = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "WARN": logging.WARNING,
    "ERROR": logging.ERROR,
    "CRITICAL": logging.CRITICAL,
}


class StructuredFormatter(logging.Formatter):
    """Emit each log record as a single-line JSON object.

    Standard fields always present:
      timestamp, level, source, lambda, correlation_id, message

    Additional fields: any keyword arguments passed to the log call
    (stored in `record.extra_fields` by PlatformLogger).
    """

    def format(self, record: logging.LogRecord) -> str:

... [TRUNCATED — 308 lines omitted, 388 total]

```


### ingestion_validator.py — Ingestion validation layer
```python

"""
ingestion_validator.py — DATA-2: Shared ingestion validation layer.

Validates incoming data items BEFORE writing to DynamoDB.
Invalid records are logged and written to S3 `validation-errors/` prefix
for audit. Critical validation failures skip DDB write entirely.

USAGE:

    from ingestion_validator import validate_item, validate_and_write

    result = validate_item("whoop", item, date_str="2026-03-08")
    if result.should_skip_ddb:
        logger.error("Skipping DDB write", errors=result.errors)
        result.archive_to_s3(s3_client, bucket)
        return
    if result.warnings:
        logger.warning("Validation warnings", warnings=result.warnings)

    table.put_item(Item=item)  # or safe_put_item()

VALIDATION RULES:

    Each source has:
      - required_fields: list of fields that MUST be present (critical if missing)
      - typed_fields: {field: type} — warns if value fails type check
      - range_checks: {field: (min, max)} — warns if value out of expected range
      - critical_range_checks: {field: (min, max)} — SKIPS write if out of range
      - at_least_one_of: list of fields — warns if ALL are absent

    Severity levels:
      CRITICAL — skip DDB write, archive to S3, log error
      WARNING  — write proceeds, issue logged and archived

SOURCES COVERED (20):
  whoop, garmin, apple_health, macrofactor, macrofactor_workouts, strava,
  eightsleep, withings, habitify, notion, todoist, weather, supplements,
  computed_metrics, character_sheet, day_grade, habit_scores,
  computed_insights, google_calendar, adaptive_mode
  (20 total: 13 ingestion + 6 compute + 1 calendar)

v1.0.0 — 2026-03-08 (DATA-2)
"""

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal as _Decimal
from typing import Any

logger = logging.getLogger(__name__)
REGION = os.environ.get("AWS_REGION", "us-west-2")

# ── Validation result ──────────────────────────────────────────────────────────

@dataclass
class ValidationResult:
    source: str
    date_str: str
    errors: list[str] = field(default_factory=list)     # CRITICAL — skip write
    warnings: list[str] = field(default_factory=list)   # non-blocking

    @property
    def is_valid(self) -> bool:
        return len(self.errors) == 0

    @property
    def should_skip_ddb(self) -> bool:
        return len(self.errors) > 0

    def archive_to_s3(self, s3_client, bucket: str, item: dict):
        """Write the rejected item to S3 validation-errors/ prefix for audit."""
        try:
            ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
            key = f"validation-errors/{self.source}/{self.date_str}/{ts}.json"
            payload = {
                "source": self.source,
                "date": self.date_str,

... [TRUNCATED — 483 lines omitted, 563 total]

```


### ai_output_validator.py — AI output safety layer
```python

"""
ai_output_validator.py — AI-3: Post-processing validation for AI coaching output.

Validates AI-generated coaching text AFTER generation, BEFORE delivery.
Catches dangerous recommendations, empty/truncated output, and advice that
conflicts with the user's known health context.

USAGE (in ai_calls.py or any Lambda after receiving AI output):

    from ai_output_validator import validate_ai_output, AIOutputType

    result = validate_ai_output(
        text=bod_insight,
        output_type=AIOutputType.BOD_COACHING,
        health_context={"recovery_score": 18, "tsb": -22},
    )

    if result.blocked:
        logger.error("AI output blocked", reason=result.block_reason)
        return result.safe_fallback   # use fallback text instead

    if result.warnings:
        logger.warning("AI output warnings", warnings=result.warnings)

    final_text = result.sanitized_text   # safe to use

VALIDATION TIERS:

    BLOCK  — output is replaced with safe_fallback. Used for:
             - Empty/None output (Lambda crash protection)
             - Dangerous exercise recs with red recovery (injury risk)
             - Severely dangerous caloric guidance (< 800 kcal)
             - Output clearly truncated mid-sentence

    WARN   — output used as-is, warning logged. Used for:
             - Aggressive training language with borderline recovery
             - High-calorie surplus recommendation (unusual for this user)
             - Generic phrases that suggest context was ignored
             - Correlation presented as causation with low-confidence signal

    PASS   — no issues detected

DISCLAIMER:
    All AI output validated by this module should still include the footer:
    "AI-generated analysis, not medical advice." (AI-1 requirement)
    This module validates logical safety, not medical accuracy.

v1.1.0 — 2026-03-13 (TB7-19: hallucinated data reference detection)
  - _METRIC_PATTERNS: 7 metric patterns (recovery, HRV, resting HR, sleep score, weight, TSB)
  - _check_hallucinated_metrics(): cross-refs text numbers against health_context ±25%
  - Check 12 in validate_ai_output(): WARN when claimed metrics deviate >25% from actual
v1.0.0 — 2026-03-08 (AI-3)
"""

import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

logger = logging.getLogger(__name__)


# ── Output types ───────────────────────────────────────────────────────────────

class AIOutputType(str, Enum):
    BOD_COACHING   = "bod_coaching"      # Board of Directors 2-3 sentence coaching
    TLDR           = "tldr"              # TL;DR one-liner
    GUIDANCE       = "guidance"          # Smart guidance bullet item
    TRAINING_COACH = "training_coach"    # Training coach section
    NUTRITION_COACH = "nutrition_coach"  # Nutrition coach section
    JOURNAL_COACH  = "journal_coach"     # Journal reflection + tactical
    CHRONICLE      = "chronicle"         # Weekly chronicle narrative
    WEEKLY_DIGEST  = "weekly_digest"     # Weekly digest coaching
    MONTHLY_DIGEST = "monthly_digest"    # Monthly digest coaching
    GENERIC        = "generic"           # Unknown — minimal checks only


# ── Validation result ──────────────────────────────────────────────────────────


... [TRUNCATED — 513 lines omitted, 593 total]

```


### digest_utils.py — Shared digest utilities
```python

"""
digest_utils.py — Shared utilities for digest Lambdas (v1.0.0)

Extracted from weekly_digest_lambda.py and monthly_digest_lambda.py to eliminate
duplication, fix bugs, and ensure consistent behaviour across all digest cadences.

Consumers:
  - weekly_digest_lambda.py
  - monthly_digest_lambda.py

Contents:
  - Pure scalar helpers: d2f, avg, fmt, fmt_num, safe_float
  - dedup_activities
  - _normalize_whoop_sleep
  - List-based extractors: ex_whoop_from_list, ex_whoop_sleep_from_list, ex_withings_from_list
  - Banister: compute_banister_from_list, compute_banister_from_dict
"""

import math
from datetime import datetime, timedelta, timezone
from decimal import Decimal


# ══════════════════════════════════════════════════════════════════════════════
# PURE SCALAR HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def d2f(obj):
    """Recursively convert DynamoDB Decimal values to float."""
    if isinstance(obj, list):    return [d2f(i) for i in obj]
    if isinstance(obj, dict):    return {k: d2f(v) for k, v in obj.items()}
    if isinstance(obj, Decimal): return float(obj)
    return obj


def avg(vals):
    """Mean of a list, ignoring None values. Returns None for empty input."""
    v = [x for x in vals if x is not None]
    return round(sum(v) / len(v), 1) if v else None


def fmt(val, unit="", dec=1):
    """Format a number with optional unit; returns em-dash for None."""
    return "\u2014" if val is None else f"{round(val, dec)}{unit}"


def fmt_num(val):
    """Format a number with thousands separator; returns em-dash for None."""
    if val is None:
        return "\u2014"
    return "{:,}".format(round(val))


def safe_float(rec, field, default=None):
    """Safely extract a float from a dict record."""
    if rec and field in rec:
        try:
            return float(rec[field])
        except Exception:
            return default
    return default


# ══════════════════════════════════════════════════════════════════════════════
# ACTIVITY DEDUP  (Strava/Garmin duplicate removal)
# ══════════════════════════════════════════════════════════════════════════════

def dedup_activities(activities):
    """Remove duplicate activities within a 15-minute window.

    Keeps the richer record (higher richness score). Records without a parseable
    start_date_local are kept unconditionally. Handles Garmin->Strava auto-sync
    duplicates where the same session appears twice with different metadata.
    """
    if not activities or len(activities) <= 1:
        return activities

    def parse_start(a):
        s = a.get("start_date_local") or a.get("start_date") or ""
        try:

... [TRUNCATED — 195 lines omitted, 275 total]

```


### mcp/handler.py (first 60 lines)
```python

"""
Lambda handler and MCP protocol implementation.

Supports two transport modes:
1. Remote MCP (Streamable HTTP via Function URL) — for claude.ai, mobile, desktop
2. Local bridge (direct Lambda invoke via boto3) — legacy Claude Desktop bridge

The remote transport implements MCP Streamable HTTP (spec 2025-06-18):
- POST / — JSON-RPC request/response
- HEAD / — Protocol version discovery
- GET /  — 405 (no SSE support in Lambda)

OAuth: Minimal auto-approve flow to satisfy Claude's connector requirement.
Security is provided by the unguessable 40-char Lambda Function URL, not OAuth.
"""
import json
import logging
import base64
import uuid
import hmac
import hashlib
import time
import concurrent.futures
import urllib.parse

from mcp.config import logger, __version__
from mcp.core import get_api_key, decimal_to_float
from mcp.registry import TOOLS
from mcp.utils import validate_date_range, validate_single_date, mcp_error
from mcp.warmer import nightly_cache_warmer

# ── MCP protocol constants ────────────────────────────────────────────────────
MCP_PROTOCOL_VERSION = "2025-06-18"
MCP_PROTOCOL_VERSION_LEGACY = "2024-11-05"

# Headers included in all remote MCP responses
_MCP_HEADERS = {
    "Content-Type": "application/json",
    "MCP-Protocol-Version": MCP_PROTOCOL_VERSION,
    "Cache-Control": "no-cache",
}


# ── MCP protocol handlers ─────────────────────────────────────────────────────
def handle_initialize(params):
    # Negotiate protocol version — support both current and legacy
    client_version = params.get("protocolVersion", MCP_PROTOCOL_VERSION_LEGACY)
    server_version = (MCP_PROTOCOL_VERSION
                      if client_version >= "2025"
                      else MCP_PROTOCOL_VERSION_LEGACY)

    return {
        "protocolVersion": server_version,
        "capabilities":    {"tools": {}},
        "serverInfo":      {"name": "life-platform", "version": __version__},
    }


def handle_tools_list(_params):
    return {"tools": [t["schema"] for t in TOOLS.values()]}

... [TRUNCATED — 543 lines omitted, 603 total]

```


---

## 13. PREVIOUS REVIEW GRADES


| Dimension | #1 (v2.91) | #2 (v3.1.3) | #3 (v3.3.10) | #4 (v3.4.1) | #13 (v3.7.29) |
|-----------|-----------|-----------|-------------|-------------|---------------|
| Architecture | B+ | B+ | A- | A | A |
| Security | C+ | B+ | B+ | A- | A- |
| Reliability | B- | B+ | B+ | B+ | A- |
| Operability | C+ | B- | B+ | B+ | B+ |
| Cost | A | A | A | A | A+ |
| Data Quality | B | B+ | B+ | A- | A |
| AI/Analytics | C+ | B- | B | B | B+ |
| Maintainability | C | B- | B | B+ | B+ |
| Production Readiness | D+ | C | B- | B | B+ |


**Last review source file: `REVIEW_2026-03-14_v13.md`**


### Last Review Findings (read this before flagging ANY new finding)

# Life Platform — Architecture Review #13
**Date:** 2026-03-14 | **Version:** v3.7.29 | **Reviewer:** Technical Board of Directors (full panel)
**Prior grade baseline:** Review #4 (v3.4.1) — last comprehensive external review

---

## Executive Summary

The Life Platform is a genuinely impressive solo-developer personal health intelligence system that has matured significantly since Review #4. The platform ingests data from 20 sources, processes it through 42+ Lambdas across 8 CDK stacks, and serves 88 MCP tools to Claude for interactive querying. An intelligence compounding layer (IC features) adds persistent memory, hypothesis generation, and progressive coaching context.

**Overall assessment: B+ to A- (strong for personal production, with specific gaps to close for productization)**

The system's strengths are real: clean single-table DynamoDB design, well-decomposed CDK stacks with per-Lambda least-privilege IAM, thoughtful cost management ($10/mo), genuine intelligence layer innovation, and an unusually disciplined ADR/documentation practice. The SIMP-1 tool consolidation (116→88 tools) and pre-computation pipeline are mature architectural moves.

The weaknesses are concentrated in three areas: (1) deployment fragility — the incident log tells a story of CDK reconciliation regressions and handler mismatches that keep recurring despite mitigations, (2) test coverage that validates wiring but not business logic end-to-end, and (3) the inherent single-operator brittleness of a system with 42 Lambdas, 11 secrets, and 49 alarms all maintained by one person with no automated CI/CD pipeline.

**Grade progression:**

| Dimension | #4 (v3.4.1) | #13 (v3.7.29) | Delta |
|-----------|-------------|---------------|-------|
| Architecture | A | A | = |
| Security | A- | A- | = |
| Reliability | B+ | A- | ↑ |
| Operability | B+ | B+ | = |
| Cost | A | A+ | ↑ |
| Data Quality | A- | A | ↑ |
| AI/Analytics | B | B+ | ↑ |
| Maintainability | B+ | B+ | = |
| Production Readiness | B | B+ | ↑ |

---

## What the System Does Well

### 1. Architecture Clarity (A)
The three-layer architecture (Ingest → Store → Serve) with a clearly separated Compute layer is clean and well-documented. The 8 CDK stacks map logically to functional boundaries. Cross-stack references flow through CoreStack outputs (table, bucket, DLQ, SNS topic). The separation of MCP serving from compute/email is sound.

### 2. IAM Discipline (A-)
Per-Lambda IAM roles with function-specific policies in `role_policies.py` is genuinely rare even in enterprise settings. The `_ingestion_base()` pattern that generates scoped DynamoDB + KMS + S3 + Secrets + DLQ policies per source is elegant. No shared roles. No wildcards on DynamoDB actions. KMS key properly scoped.

### 3. Cost Engineering (A+)
$10/month for a 42-Lambda, 20-source, 88-tool platform with AI calls is exceptional. The COST-A alarm consolidation (87→42 alarms, saving $4.60/mo), on-demand DynamoDB, Lambda Function URLs over API Gateway, and deliberate rejection of WAF/provisioned concurrency all show cost-conscious engineering. The $20 budget with graduated alerts is a real guardrail.

### 4. Intelligence Layer Design (B+)
The compute→store→read pattern (ADR-015) is the right architecture for avoiding redundant AI calls and enabling progressive context. The IC features — platform_memory, insight ledger, hypothesis engine, decision journal — create a genuine compounding intelligence substrate without the complexity of vector stores or fine-tuning (ADR-016, ADR-017). The chain-of-thought two-pass coaching (IC-3) and red team pass (IC-17) show real LLM system design sophistication.

### 5. Data Model Coherence (A-)
Single-table DynamoDB with `USER#matthew#SOURCE#<source> | DATE#YYYY-MM-DD` is the right choice. No GSI needed (ADR-005). Source-of-truth ownership model in config.py prevents conflicting data. Gap-aware backfill on ingestion Lambdas is a self-healing pattern. The ingestion validator with critical/warning severity tiers catches bad data before it enters DDB.

### 6. Documentation Practice (A)
28 ADRs, incident log with TTD/TTR, SLO definitions with error budgets, review methodology doc, handover protocol, and a review bundle generator — this is more rigorous than most enterprise teams. The doc update trigger matrix in the session workflow is a quality signal.

### 7. SIMP-1 Tool Consolidation
The dispatcher pattern (116→88 tools) with `view=` parameter routing is the right simplification. The EMF metrics (COST-2) for per-tool usage tracking will enable data-driven tool rationalization in Phase 2.

---

## Key Architectural Concerns

### FINDING-01: Deployment Pipeline Is the #1 Operational Risk
**Severity:** High | **Category:** CI/CD, Reliability | **Confidence:** High | **Evidence:** Direct (incident log)

**What I observed:** The incident log shows 8 deployment-related incidents including 3 P1/P2 events caused by CDK packaging, handler mismatches, and stale env vars. The deployment workflow is: Matthew runs `deploy/deploy_lambda.sh` or `npx cdk deploy` manually from his terminal, then runs `post_cdk_reconcile_smoke.sh`. There is no CI/CD pipeline, no automated test gate before deploy, no canary deployment, and no automated rollback.

**Why it matters:** Every deploy is a manual, error-prone ceremony. The CDK drift pattern (policies correct in code but not applied to AWS) has caused 3 incidents. The handler mismatch pattern has caused 2 P1s. These are exactly the failure modes that automated pipelines prevent.

**Impact if ignored:** Will continue to produce 1-2 deployment incidents per month. As the platform grows, the blast radius of a bad deploy increases. The `post_cdk_reconcile_smoke.sh` is a band-aid — it catches failures after they happen rather than preventing them.

**Recommended change:** Implement a minimal GitHub Actions pipeline: `pytest` → `cdk synth` (validates templates) → `cdk diff` (shows what will change) → manual approval → `cdk deploy` → smoke test. This does not need to be complex — even a single workflow file that runs tests and synth on every push to main would catch 80% of deployment bugs.

**Effort:** M (2-4 hours for basic pipeline) | **Context:** Acceptable for personal project. Needs improvement for serious production.

---

### FINDING-02: No Integration Test Coverage for the Critical Path
**Severity:** High | **Category:** Testing, Reliability | **Confidence:** High | **Evidence:** Direct

**What I observed:** 83 unit tests covering business logic, 7 registry integrity tests, and CDK handler/S3 path consistency tests. However, there is no integration test that exercises the actual critical path: EventBridge → Lambda → DynamoDB write → MCP query → response. The QA smoke Lambda tests basic liveness but not data correctness.

**Why it matters:** The unit tests validate scoring algorithms and dispatcher routing, but cannot catch: DynamoDB schema mismatches, IAM permission gaps, missing environment variables, Lambda cold start failures, or stale module copies. These are exactly the failure modes seen in the incident log.

**Recommended change:** Add 3-5 integration tests that run against live AWS: (1) invoke one ingestion Lambda with test data, verify DDB write, (2) invoke MCP server with a representative tool call, verify response shape, (3) verify freshness checker against known-good data. Run post-deploy.

**Effort:** M (3-5 hours) | **Context:** ADR-028 documents this intent — execution is the gap.

---

### FINDING-03: MCP Server Is a Single Monolith Under Scaling Pressure
**Severity:** Medium | **Category:** Architecture | **Confidence:** Medium | **Evidence:** Direct + Inferred

**What I observed:** The MCP server is a single Lambda with 31 modules, 88 tools, 1024 MB memory, and a 300s timeout. All tool calls — from simple `get_sources` (a few ms) to `get_longitudinal_summary` over years of data (potentially 20+ seconds) — share the same Lambda, concurrency pool, and memory allocation.

**Why it matters:** At current usage (single user, ~20-50 MCP calls/day), this is fine. But the 30s soft timeout per tool (R6) and reserved concurrency of 10 mean that a burst of heavy queries could exhaust concurrency while lightweight queries wait. The cache warmer holds a Lambda instance for ~90s daily, further reducing available concurrency.

**Impact if ignored:** Unlikely to be a problem at current scale. Becomes an issue if MCP usage increases 5-10x (e.g., agentic workflows, or productization).

**Recommended change:** No action needed now. The dedicated warmer Lambda (v3.7.22) was the right first step. If scaling pressure appears, split into read-light (cached tools, metadata) and read-heavy (correlation, longitudinal, search) Lambda functions.

**Effort:** L (if/when needed) | **Context:** Acceptable for personal project. Revisit at productization.

---

### FINDING-04: Secret Management Has Residual Complexity
**Severity:** Medium | **Category:** Security | **Confidence:** High | **Evidence:** Direct

**What I observed:** 11 active secrets with a complex consolidation history. The `api-keys` secret was deleted 2026-03-14, `webhook-key` is scheduled for deletion 2026-03-22, and TB7-4 (grep sweep to confirm no code reads deleted secrets) has a hard deadline of 2026-03-17. The incident at 2026-03-08 where Todoist failed for 2 days because an env var pointed to the deleted `api-keys` secret demonstrates the risk.

**Why it matters:** Secret consolidation is a correctness minefield. The env var override pattern (Lambda env vars taking precedence over code defaults) means that secrets can be "deleted" at the Secrets Manager level while still being referenced by running Lambdas. The 2-day Todoist outage is direct evidence.

**Recommended change:** After TB7-4 completes, add a CI test that greps all Lambda source files for every known secret name and validates that referenced secrets exist. This is a one-time addition that prevents the class of bug permanently.

**Effort:** S (1 hour) | **Context:** Needs improvement for any production system.

---

### FINDING-05: OAuth Auto-Approve Pattern Creates a False Security Boundary
**Severity:** Medium | **Category:** Security | **Confidence:** High | **Evidence:** Direct (handler.py)

**What I observed:** The remote MCP endpoint implements OAuth 2.1 with auto-approve: `_handle_authorize` immediately redirects with an auth code, `_handle_token` returns a deterministic HMAC-derived Bearer token. ADR-026 documents this as an accepted design where security relies on the "unguessable 40-char Lambda Function URL."

**Why it matters:** The Lambda Function URL is the de facto security boundary, not OAuth. This is fine — but it creates a false sense of layered security. If the Function URL is exposed (accidentally logged, shared, or extracted from claude.ai's MCP connector config), the OAuth layer provides zero additional protection because it auto-approves everything.

**Specific concern:** `_get_bearer_token()` falls back to accepting any token if no API key is configured (`if expected is None: return True`). This is a fail-open default.

**Recommended change:** (1) Remove the fail-open fallback — if no API key exists, reject all requests. (2) Add the Function URL to a `.gitignore`-equivalent so it's never committed. (3) Consider adding IP allowlisting via Lambda Function URL configuration if your Claude connections come from predictable IPs.

**Effort:** S (30 min) | **Context:** Acceptable for personal project with awareness. Must change before productization.

---

### FINDING-06: Correlation Analysis Needs Stronger Statistical Guardrails
**Severity:** Medium | **Category:** AI/Statistics | **Confidence:** High | **Evidence:** Direct (registry.py, weekly_correlation_compute)

**What I observed:** The `get_cross_source_correlation` tool computes Pearson correlation between arbitrary metrics. The tool description says "r > 0.4 is practically meaningful." The weekly correlation compute (R8-LT9) now has n-gating (moderate requires n≥30, strong requires n≥50). However, the on-demand MCP tool `get_cross_source_correlation` does not appear to have the same n-gating — it's available for any date range including very short ones.

**Why it matters:** A Pearson r of 0.7 on 10 data points is statistically meaningless but will be presented to Claude (and through Claude to Matthew) as a "strong correlation." With 20 sources and dozens of fields, the probability of finding spurious correlations by chance is extremely high. This is the multiple comparisons problem.

**Recommended change:** (1) Add n-gating to the on-demand correlation tool (minimum n=14, warn at n<30). (2) Report confidence intervals or p-values alongside r. (3) Add a disclaimer to the tool response when n < 30. (4) Consider Bonferroni or FDR correction when the weekly compute runs 20 pairs simultaneously.

**Effort:** S-M (2-3 hours) | **Context:** Needs improvement for any system making health recommendations.

---

### FINDING-07: No Automated Backup Verification
**Severity:** Medium | **Category:** Reliability | **Confidence:** High | **Evidence:** Direct

**What I observed:** PITR (35-day rolling backup) is enabled on DynamoDB, and S3 has raw data archives. However, there is no evidence of backup restore testing — no restore drills, no automated verification that PITR works, no tested restore procedure in the runbook.

**Why it matters:** PITR is configured but untested. DynamoDB PITR restores to a new table, which means every Lambda's TABLE_NAME env var would need updating. Without a tested procedure, recovery time after data loss could be hours to days.

**Recommended change:** (1) Add a quarterly restore drill to the review cadence. (2) Document the PITR restore procedure in the runbook (restore to new table → verify → swap TABLE_NAME env vars → repoint Lambdas). (3) Consider adding a daily DynamoDB export to S3 as a secondary backup.

**Effort:** S (2 hours for documentation, 1 hour per quarterly drill) | **Context:** Acceptable for personal project. Needs improvement for serious production.

---

### FINDING-08: Lambda Layer Version Management Is Manual and Fragile
**Severity:** Medium | **Category:** Maintainability | **Confidence:** High | **Evidence:** Direct (incident log entries for stale layer versions)

**What I observed:** The shared-utils layer (currently v4+) is built manually via `deploy/build_layer.sh` and attached to Lambdas via CDK. The P2 incident where all 8 email Lambdas ran on stale layer v2 (missing `set_date`) demonstrates the risk. ADR-027 plans a two-tier structure (stable core → Layer, volatile tools → Lambda zip) but execution is deferred to April 13.

**Why it matters:** Layer version mismatches are a silent failure mode — Lambdas continue to run with stale code, and errors only surface when a method added in the new layer is called. The incident log shows this has happened at least twice.

**Recommended change:** Add a CI test that verifies the shared layer version referenced in CDK matches the latest published layer version. This catches the "forgot to rebuild layer" class of bug.

**Effort:** S (1 hour) | **Context:** Needs improvement for any multi-Lambda system.

---

### FINDING-09: Health Data Coaching Without Medical Disclaimers in MCP Tool Responses
**Severity:** Medium | **Category:** Compliance, AI Safety | **Confidence:** High | **Evidence:** Direct

**What I observed:** The AI output validator (AI-3) blocks dangerous exercise recommendations and adds "AI-generated analysis, not medical advice" to email outputs. However, MCP tool responses (e.g., `get_health(view=risk_profile)`, `get_cgm(view=dashboard)`, `get_blood_pressure_dashboard`) return structured data with clinical classifications ("stage 2 hypertension", "pre-diabetic", "abnormal HR recovery") without embedded disclaimers.

**Why it matters:** When Claude surfaces these through conversation, the medical disclaimer depends on Claude's system prompt and general behavior, not on the tool response itself. If the MCP server is ever used by a different consumer, or if the tool responses are displayed directly (e.g., in a dashboard), clinical classifications without disclaimers create liability risk.

**Recommended change:** Add a `_disclaimer` field to all health-assessment tool responses: "Health data analysis for personal tracking only. Not medical advice. Consult a healthcare provider for clinical decisions."

**Effort:** S (1 hour — add to response wrapper) | **Context:** Acceptable for personal project. Must change before any sharing or productization.

---

### FINDING-10: `d2f()` Decimal Conversion Duplicated Across 4+ Files
**Severity:** Low | **Category:** Maintainability | **Confidence:** High | **Evidence:** Direct

**What I observed:** The `d2f()` / `_d2f()` / `decimal_to_float()` function (recursively converts DynamoDB Decimal to float) is independently implemented in: `digest_utils.py`, `sick_day_checker.py`, `mcp/core.py`, and likely several ingestion Lambdas. Each implementation is slightly different in naming and error handling.

**Why it matters:** Code duplication that's harmless until one copy diverges (e.g., one handles `set` types and another doesn't). The shared layer is the right home for this.

**Recommended change:** Consolidate into the shared utils layer as `decimal_utils.d2f()`. This is a natural candidate for the ADR-027 stable layer tier.

**Effort:** S (30 min) | **Context:** Low priority but clean hygiene.

---

## Detailed Findings Table

| # | Title | Severity | Category | Effort | Confidence |
|---|-------|----------|----------|--------|------------|
| F01 | No CI/CD pipeline — manual deploys are primary risk | High | CI/CD | M | High |
| F02 | No integration tests for critical path | High | Testing | M | High |
| F03 | MCP monolith under potential scaling pressure | Medium | Architecture | L | Medium |
| F04 | Secret management residual complexity | Medium | Security | S | High |
| F05 | OAuth auto-approve fail-open default | Medium | Security | S | High |
| F06 | Correlation tool missing n-gating | Medium | Statistics | S-M | High |
| F07 | No backup restore verification | Medium | Reliability | S | High |
| F08 | Layer version management is manual | Medium | Maintainability | S | High |
| F09 | No medical disclaimers in MCP tool responses | Medium | Compliance | S | High |
| F10 | d2f() duplicated across 4+ files | Low | Maintainability | S | High |
| F11 | DST shift on all EventBridge crons (documented but unmitigated) | Low | Reliability | S | High |
| F12 | No rate limiting on MCP write tools (Todoist, supplements, etc.) | Medium | Security | S | Medium |
| F13 | CloudWatch log retention at 30 days may lose incident context | Low | Operations | S | Medium |
| F14 | No canary for remote MCP endpoint availability | Medium | Reliability | S | High |
| F15 | Hypothesis engine runs 20 pairs without multiple comparison correction | Medium | Statistics | S | High |

---

## Security Review

**Overall: A-** (strong for personal project, specific gaps for productization)

**Strengths:**
- Per-Lambda IAM roles with least-privilege policies
- KMS CMK encryption on DynamoDB with annual rotation
- CloudTrail audit logging enabled
- Secrets Manager with dedicated per-service secrets
- HMAC-derived Bearer tokens for remote MCP
- Input validation (SEC-3) with date range caps and type checking
- Auth failure EMF metrics for credential probing detection
- Reserved concurrency (10) on MCP Lambda as anti-abuse measure
- No VPC needed (ADR-008) — correct for this architecture

**Gaps:**
- **F05:** OAuth fail-open default if API key missing
- **F12:** MCP write tools (create_todoist_task, log_supplement, write_platform_memory, delete_platform_memory, delete_todoist_task) have no rate limiting beyond the Lambda's reserved concurrency. A compromised MCP session could write unlimited records.
- **Inferred:** The `webhook-key` secret (scheduled deletion 2026-03-22) needs the same env-var audit that TB7-4 does for `api-keys`.
- **Observation:** The Lambda Function URL `https://c5hljblvma4u2xd6wf6oe4clk40unthu.lambda-url.us-west-2.on.aws` appears in the review bundle, ARCHITECTURE.md, and INFRASTRUCTURE.md. If any of these docs are shared or committed to a public repo, the URL is exposed — and since it's the primary security boundary (per ADR-026), this is material.

---

## IAM Review

**Overall: A-**

**Strengths:**
- `role_policies.py` is a single source of truth for all IAM policies
- `_ingestion_base()` pattern enforces consistent structure
- DynamoDB actions are scoped (PutItem/GetItem/Query — no Scan)
- S3 writes scoped to `raw/<source>/*` per Lambda
- KMS decrypt+generate permissions correctly scoped to the platform CMK

... [TRUNCATED — 243 lines omitted, 493 total]


---

## 13b. RESOLVED FINDINGS INVENTORY


> **REVIEWER INSTRUCTION:** Before issuing ANY finding in this review, check this table.
> If the finding appears here as RESOLVED, do NOT re-issue it. Instead, verify the
> resolution is adequate and note it as confirmed-resolved in your output.
> Re-issuing resolved findings wastes review budget and creates noise.

### R13 Findings — All Resolved (as of 2026-03-15, v3.7.40)

| ID | Finding | Status | Version | Proof |
|----|---------|--------|---------|-------|
| R13-F01 | No CI/CD pipeline | ✅ RESOLVED | Already existed | `.github/workflows/ci-cd.yml` — 7 jobs: lint, test (9 linters), plan (cdk synth+diff), manual approval gate, deploy, smoke test, auto-rollback. OIDC auth. |
| R13-F02 | No integration tests for critical path | ✅ RESOLVED | v3.7.38 | `tests/test_integration_aws.py` I1–I13: Lambda handlers, layer versions, DDB health, secrets, EventBridge, S3, DLQ, alarms, MCP invocability, data-reconciliation, MCP tool response shape, freshness data. |
| R13-F03 | MCP monolith split assessment | N/A | — | Deferred: <100 calls/day. |
| R13-F04 | CI secret reference linter | ✅ RESOLVED | v3.7.35 | `tests/test_secret_references.py` SR1–SR4. Wired into `ci-cd.yml` test job. |
| R13-F05 | OAuth fail-open default | ✅ RESOLVED | v3.7.35 | `mcp/handler.py` `_get_bearer_token()` returns sentinel `"__NO_KEY_CONFIGURED__"`, `_validate_bearer()` fail-closed. |
| R13-F06 | Correlation n-gating missing | ✅ RESOLVED | v3.7.36 | `mcp/tools_training.py` `tool_get_cross_source_correlation`: n≥14 hard min, label downgrade, p-value, 95% CI via Fisher z. |
| R13-F07 | No PITR restore drill | ⏳ PENDING | — | First drill scheduled ~Apr 2026. Runbook written at v3.7.17. |
| R13-F08 | Layer version CI test | ✅ RESOLVED | v3.7.38 | `tests/test_layer_version_consistency.py` LV1–LV5. `cdk/stacks/constants.py` is single source of truth for layer version (LV1 caught real duplication bug). |
| R13-F08-dur | No duration alarms | ✅ RESOLVED | v3.7.36 | `deploy/create_duration_alarms.sh`: `life-platform-daily-brief-duration-p95` (>240s) + `life-platform-mcp-duration-p95` (>25s). |
| R13-F09 | No medical disclaimers in MCP health tools | ✅ RESOLVED | v3.7.35–36 | `_disclaimer` field in `tool_get_health()`, `tool_get_cgm()`, `tool_get_readiness_score()`, `tool_get_blood_pressure_dashboard()`, `tool_get_blood_pressure_correlation()`, `tool_get_hr_recovery_trend()`. |
| R13-F10 | `d2f()` duplicated across Lambdas | ✅ RESOLVED (annotated) | v3.7.37 | `weekly_correlation_compute_lambda.py` annotated; canonical copy in `digest_utils.py` (shared layer). Full dedup deferred to layer v12. |
| R13-F11 | DST timing in EventBridge | Documented, not mitigated | — | Low-impact; documented in ARCHITECTURE.md. |
| R13-F12 | No rate limiting on MCP write tools | ✅ RESOLVED | v3.7.35 | `mcp/handler.py` `_check_write_rate_limit()`: 10 calls/invocation on `create_todoist_task`, `delete_todoist_task`, `log_supplement`, `write_platform_memory`, `delete_platform_memory`. |
| R13-F14 | No MCP endpoint canary | ✅ RESOLVED | v3.7.40 | EventBridge rule `rate(15 minutes)` → canary. Alarms: `life-platform-mcp-canary-failure-15min`, `life-platform-mcp-canary-latency-15min`. |
| R13-F15 | Weekly correlation lacks FDR correction | ✅ RESOLVED | v3.7.37 | `weekly_correlation_compute_lambda.py` Benjamini-Hochberg FDR correction, `pearson_p_value()`, per-pair `p_value`/`p_value_fdr`/`fdr_significant`. |
| R13-XR | No X-Ray tracing on MCP | ✅ RESOLVED | v3.7.40 | `cdk/stacks/mcp_stack.py` `tracing=_lambda.Tracing.ACTIVE`. IAM: `xray:PutTraceSegments` etc. in `mcp_server()` policy. |


---

## 14. SCHEMA SUMMARY

## Key Structure

| Attribute | Description |
|-----------|-------------|
| `pk` | Partition key — identifies the entity type and owner |
| `sk` | Sort key — enables range queries and versioning |



## Sources

Valid source identifiers: `whoop`, `withings`, `strava`, `todoist`, `apple_health`, `hevy`, `eightsleep`, `chronicling`, `macrofactor`, `macrofactor_workouts`, `garmin`, `habitify`, `notion`, `labs`, `dexa`, `genome`, `supplements`, `weather`, `travel`, `state_of_mind`, `habit_scores`, `character_sheet`, `computed_metrics`, `platform_memory`, `insights`, `decisions`, `hypotheses`, `chronicle`

Note: `hevy` and `chronicling` are historical/archived sources — not actively ingesting. `habit_scores`, `character_sheet`, `computed_metrics`, `platform_memory`, `insights`, `decisions`, and `hypotheses` are derived/computed partitions, not raw ingested data.

Ingestion methods: API polling (scheduled Lambda), S3 file triggers (manual export), **webhook** (Health Auto Export push — also handles BP and State of Mind), **MCP tool write** (supplements), **on-demand fetch + scheduled Lambda** (weather)

---


---

## 15. DOCUMENTATION INVENTORY

**Root docs (23 files):** ARCHITECTURE.md, CHANGELOG.md, CHANGELOG_ARCHIVE.md, COST_TRACKER.md, DATA_FLOW_DIAGRAM.md, DECISIONS.md, HANDOVER_LATEST.md, INCIDENT_LOG.md, INFRASTRUCTURE.md, INTELLIGENCE_LAYER.md, MCP_TOOL_CATALOG.md, MCP_TOOL_TIERING_DESIGN.md, ONBOARDING.md, PLATFORM_GUIDE.md, PROJECT_PLAN.md, PROJECT_PLAN_ARCHIVE.md, REVIEW_METHODOLOGY.md, REVIEW_RUNBOOK.md, RUNBOOK.md, SCHEMA.md, SIMP1_PLAN.md, SLOs.md, sec3_input_validation_assessment.md


**docs/archive/ (18 files):** AUDIT_PROD2_MULTI_USER.md, AVATAR_DESIGN_STRATEGY.md, BOARD_DERIVED_METRICS_PLAN.md, CHANGELOG_v341.md, DATA_DICTIONARY_archived_v3.7.32.md, DERIVED_METRICS_PLAN.md, DESIGN_PROD1_CDK.md, DESIGN_SIMP2_INGESTION.md, FEATURES_archived_v3.7.32.md, NOTION_ENRICHMENT_SPEC.md, NOTION_JOURNAL_SPEC.md, SCHEMA_LABS_ADDITION.md, SCOPING_LARGE_OPUS.md, SPEC_CHARACTER_SHEET.md, USER_GUIDE_archived_v3.7.32.md, avatar-design-strategy.md, data-source-audit-2026-02-24.md, wednesday-chronicle-design.md


**docs/audits/ (1 files):** IAM_AUDIT_2026-03-08.md


**docs/design/ (0 files):** 


**docs/rca/ (2 files):** PIR-2026-02-28-ingestion-outage.md, RCA_2026-02-24_apple_health_pipeline.md


**docs/reviews/ (14 files):** REVIEW_2026-03-08.md, REVIEW_2026-03-08_v2.md, REVIEW_2026-03-09.md, REVIEW_2026-03-09_full.md, REVIEW_2026-03-10.md, REVIEW_2026-03-10_full.md, REVIEW_2026-03-10_v6.md, REVIEW_2026-03-11_v7.md, REVIEW_2026-03-14_v13.md, REVIEW_BUNDLE_2026-03-10.md, REVIEW_BUNDLE_2026-03-14.md, REVIEW_BUNDLE_2026-03-15.md, mcp_architecture_review_2026-03-11.md, platform-review-2026-03-05.md



---


*Bundle generated 2026-03-15 by deploy/generate_review_bundle.py*
