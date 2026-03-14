# Life Platform — Changelog

## v3.7.14 — 2026-03-14: doc sync automation

### Summary
Added `deploy/sync_doc_metadata.py` — single source of truth for all platform counters (tool count, Lambda count, secrets, alarms, version, date). Replaces manual hunt-and-update across 6+ docs. Also rewrote the RUNBOOK session close checklist with a proper trigger matrix.

### Changes
- **deploy/sync_doc_metadata.py** (new): owns PLATFORM_FACTS dict, applies regex replacements across all docs. Dry-run by default, `--apply` to write.
- **docs/RUNBOOK.md**: session close checklist rewritten — 2-command process (`sync_doc_metadata.py` + git), plus explicit trigger matrix for structural changes.

### Files Changed
- `deploy/sync_doc_metadata.py` (new)
- `docs/RUNBOOK.md`
- `docs/CHANGELOG.md`

---

## v3.7.13 — 2026-03-14: R8-6/7/8 housekeeping

### Summary
Post-Review #8 housekeeping. Updated archive_onetime_scripts.sh with Batch 2 (12 new one-time scripts since v3.6.0). Reconciled MCP tool count to 116 across all docs (was 144/150/116 across three files). Updated ARCHITECTURE.md to v3.7.12 + fixed stale auth secret reference.

### Changes
- **deploy/archive_onetime_scripts.sh**: added Batch 2 (12 scripts from TB7 + P0 sessions)
- **docs/ARCHITECTURE.md**: header updated to v3.7.12/2026-03-14, tool count 116, modules 31, secrets 9, alarms 47; serve layer section updated (144→116, 30→31 modules); fixed stale `life-platform/api-keys` auth reference
- **docs/INFRASTRUCTURE.md**: tool count 150→116
- **docs/MCP_TOOL_CATALOG.md**: version v2.91.0→v3.7.12, date updated, total 144→116
- **docs/CHANGELOG.md**: this entry

### Files Changed
- `deploy/archive_onetime_scripts.sh`
- `docs/ARCHITECTURE.md`
- `docs/INFRASTRUCTURE.md`
- `docs/MCP_TOOL_CATALOG.md`

---

## v3.7.12 — 2026-03-14: Architecture Review #8 + R8 housekeeping

### Summary
Architecture Review #8 (v3.7.11 baseline). Platform grades to A- overall for the first time. Five R8 items resolved in-session: SNS confirmed active, weather_lambda.py orphan deleted, bundle generator handover path fixed, test_lambda_handlers.py + test_mcp_registry.py wired into CI/CD Job 2.

### Changes
- **docs/reviews/REVIEW_BUNDLE_2026-03-14.md** (new): pre-compiled review bundle
- **lambdas/weather_lambda.py** deleted (orphan — Review #4 debt, fails I5)
- **deploy/generate_review_bundle.py**: fix handover path (`handovers/HANDOVER_LATEST.md` not `docs/`)
- **.github/workflows/ci-cd.yml**: added `test_mcp_registry.py` + `test_lambda_handlers.py` to Job 2 (R8-5)
- **docs/CHANGELOG.md**: this entry

### Review #8 Grades
| Dimension | #7 | **#8** | Δ |
|-----------|-----|--------|---|
| Architecture | A | **A** | → |
| Security | A- | **A-** | → |
| Reliability | B+ | **A-** | ↑ |
| Operability | B+ | **A-** | ↑ |
| Cost | A | **A** | → |
| Data Quality | A- | **A-** | → |
| AI/Analytics | B | **B+** | ↑ |
| Maintainability | B+ | **A-** | ↑ |
| Production Readiness | B | **B** | → |

### Outstanding R8 items
- R8-1 ✅ TB7-4: `life-platform/api-keys` permanently deleted 2026-03-14
- R8-6 🟡 Run `bash deploy/archive_onetime_scripts.sh`
- R8-7 🟡 Reconcile MCP tool count across ARCHITECTURE.md / INFRASTRUCTURE.md / MCP_TOOL_CATALOG.md
- R8-8 🟢 Update ARCHITECTURE.md header

### Files Changed
- `docs/reviews/REVIEW_BUNDLE_2026-03-14.md` (new)
- `deploy/generate_review_bundle.py` (handover path fix)
- `.github/workflows/ci-cd.yml` (R8-5: 2 new CI test steps)
- `lambdas/weather_lambda.py` (deleted → deploy/archive/)
- `docs/CHANGELOG.md`

---

## v3.7.11 — 2026-03-13: TB7-24 Lambda handler integration linter

### Summary
Added `tests/test_lambda_handlers.py` — static Lambda handler integration linter using `ci/lambda_map.json` as authoritative registry. Six rules (I1–I6) covering file existence, syntax validity, handler signature, error resilience, orphan detection, and MCP server entry point. Complements the existing CDK handler consistency linter (H1–H5).

### Changes
- **tests/test_lambda_handlers.py** (new): TB7-24. I1 all registered sources exist; I2 syntax valid; I3 `lambda_handler(event, context)` arity; I4 top-level try/except present; I5 no orphaned Lambda files; I6 MCP server entry point valid.

### Files Changed
- `tests/test_lambda_handlers.py` (new)
- `docs/CHANGELOG.md`

---

## v3.7.10 — 2026-03-13: Housekeeping + Incident RCA (Todoist IAM drift)

### Summary
Housekeeping sprint: confirmed SIMP-1 EMF instrumentation already live, added
S3 lifecycle script for deploy artifacts, confirmed Brittany email address already
correct (SES sandbox verification pending). Investigated Mar 12 alarm storm —
root cause was CDK drift on TodoistIngestionRole missing `s3:PutObject`. Fixed
via `cdk deploy LifePlatformIngestion`. Also fixed duplicate sick-day suppression
block in freshness_checker_lambda.py (silent bug).

### Changes
- **deploy/apply_s3_lifecycle.sh** (new): expires `deploys/*` S3 objects after 30 days. Pending run.
- **lambdas/freshness_checker_lambda.py**: removed duplicate sick-day suppression block — second block silently reset `_sick_suppress = False`. Needs deploy.
- **LifePlatformIngestion CDK deploy**: synced TodoistIngestionRole — added missing `s3:PutObject` on `raw/todoist/*`. Resolved Mar 12 alarm storm.

### Incident: Mar 12 Alarm Storm (P3)
- **Root cause:** CDK drift — TodoistIngestionRole missing `s3:PutObject`
- **Cascade:** Todoist failure → freshness checker → slo-source-freshness → daily-insight-compute, failure-pattern-compute, monday-compass, DLQ depth
- **Fix:** `cdk deploy LifePlatformIngestion` (54s). Smoke verified clean.
- **Full RCA:** docs/INCIDENT_LOG.md

### Pending deploy actions
- `bash deploy/apply_s3_lifecycle.sh`
- `bash deploy/deploy_lambda.sh freshness-checker lambdas/freshness_checker_lambda.py`
- `aws sesv2 create-email-identity --email-identity brittany@mattsusername.com --region us-west-2`
- SNS subscription confirmation in `awsdev@mattsusername.com`


## v3.7.9 — 2026-03-13: TB7-25/26/27 — Rollback + WAF (N/A) + tool tiering design

### Summary
TB7-25: S3 artifact rollback strategy. `deploy_lambda.sh` maintains
`latest.zip`/`previous.zip` per function. New `rollback_lambda.sh` one-command
rollback. CI/CD `rollback-on-smoke-failure` job auto-fires when smoke fails after
a successful deploy. TB7-26: N/A — AWS WAFv2 `associate-web-acl` does not support
Lambda Function URLs as a resource type (supported: ALB, API GW, AppSync, Cognito,
App Runner, Verified Access). Attempted CfnWebACLAssociation and CLI association
both returned InvalidRequest. WebACL created and rolled back cleanly. MCP endpoint
is adequately protected by HMAC Bearer auth + existing slo-mcp-availability alarm.
TB7-27: MCP tool tiering design doc — 4-tier taxonomy, criteria, preliminary
assignments for all 144 tools, SIMP-1 instrumentation plan.

### Changes
- **TB7-25** — `deploy/deploy_lambda.sh`: S3 artifact management — shifts
  `deploys/{func}/latest.zip` → `previous.zip` before each deploy, uploads new
  zip as `latest.zip`.
- **TB7-25** — `deploy/rollback_lambda.sh` (new): downloads `previous.zip` from
  S3, redeploys, waits for active. Accepts multiple function names.
- **TB7-25** — `.github/workflows/ci-cd.yml`: `rollback-on-smoke-failure` job
  (Job 6). Fires when smoke-test fails AND deploy succeeded. Rolls back all
  deployed Lambdas + MCP. Layer rollback noted as manual.
- **TB7-25** — `ci-cd.yml` MCP deploy step: now maintains S3 rollback artifacts
  for `life-platform-mcp`.
- **TB7-26 N/A** — `cdk/stacks/mcp_stack.py`: WAF attempt reverted. Stack
  returned to v2.0 baseline with documented rationale in module docstring.
  `deploy/attach_mcp_waf.sh` created (documents the failed approach) then
  superseded. No net change to stack from v3.7.8.
- **TB7-27** — `docs/MCP_TOOL_TIERING_DESIGN.md` (new): 4-tier taxonomy,
  tiering criteria, preliminary assignments for all 144 tools, Option A
  implementation (tier field in TOOLS dict), 6-week SIMP-1 instrumentation
  requirements, decision rules, session plan.

### Files Changed
- `deploy/deploy_lambda.sh` (S3 artifact management)
- `deploy/rollback_lambda.sh` (new)
- `.github/workflows/ci-cd.yml` (rollback job + MCP S3 artifact)
- `cdk/stacks/mcp_stack.py` (WAF reverted; docstring updated with N/A rationale)
- `docs/MCP_TOOL_TIERING_DESIGN.md` (new)
- `docs/CHANGELOG.md` (this file)
- `handovers/HANDOVER_v3.7.9.md` (new)

### Deploy status
- LifePlatformMcp: ✅ deployed + smoke 10/10
- TB7-26 WAF: N/A — not supported for Lambda Function URLs

### AWS cost delta
- S3 rollback artifacts: ~$0 (small zips; add lifecycle rule to expire after 30d)
- WAF: $0 (not deployed)

---

## v3.7.8 — 2026-03-13: TB7 fully closed + DLQ cleared + smoke test fix

### Summary
TB7-11/12/13 confirmed already done. TB7-14 and TB7-16 completed (SCHEMA TTL
documentation + fingerprint comment). DLQ investigated and cleared (5 stale
Habitify retry messages from pre-layer-v9 deploy). Smoke test fixed
(--cli-binary-format regression + handler regressions for key-rotator and
insight-email-parser). All TB7 items now closed.

### Changes
- **TB7-14 CLOSED** — `SCHEMA.md` TTL section replaced with full per-partition
  table: DDB TTL vs app-level expiry vs indefinite, with rationale for each.
  Documents hypotheses (30d app-level), platform_memory (~90d policy),
  insights (~180d policy), decisions/anomalies/ingestion (indefinite).
- **TB7-16 CLOSED** — Comment added to `get_source_fingerprints()` in
  `daily_metrics_compute_lambda.py` warning that new data sources must be
  added to the fingerprint list to trigger recomputes.
- **TB7-11/12/13 CLOSED** — Confirmed already implemented: layer version
  consistency CI check, stateful resource assertions, and digest_utils.py in
  shared_layer.modules all present in existing `ci-cd.yml` and `lambda_map.json`.
- **DLQ CLEARED** — 5 stale Habitify retry messages from 2026-03-13 14:15 UTC
  (pre-layer-v9 deploy). All identical EventBridge events. Purged + alarm reset
  to OK. Habitify confirmed healthy.
- **SMOKE TEST FIXED** — Removed `--cli-binary-format raw-in-base64-out` from
  `post_cdk_reconcile_smoke.sh` (AWS CLI v2 regression). Fixed dry_run payload
  for todoist invocation check.
- **HANDLER FIXES** — `life-platform-key-rotator` and `insight-email-parser`
  restored to correct handlers (CDK reconcile regression).

### Files Changed
- `lambdas/daily_metrics_compute_lambda.py` (TB7-16 fingerprint comment)
- `docs/SCHEMA.md` (TB7-14 TTL per-partition table)
- `docs/PROJECT_PLAN.md` (TB7-11–17 all marked complete)
- `deploy/post_cdk_reconcile_smoke.sh` (CLI flag fix + dry_run fix)

---

## v3.7.7 — 2026-03-13: TB7-19/20/21/22/23 — AI validator + anomaly + drift hardening
