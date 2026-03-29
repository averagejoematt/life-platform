# Life Platform Handover — v3.7.16
**Date:** 2026-03-14
**Session type:** R8-QS4 confirmation + R8-QS2 integration test + CDK bug fixes

---

## What Was Done

### R8-QS4: Archive Deploy Scripts
Ran `bash deploy/archive_onetime_scripts.sh` — all 25 scripts were already archived
from previous sessions. Active `deploy/` is clean at 13 files. ✅ No action needed.

### R8-QS2: MCP Integration Test Added to qa-smoke
Added `check_mcp_tool_calls()` to `lambdas/qa_smoke_lambda.py` with 3 sub-checks:
- **a) `get_sources`** → ≥10 sources returned (validates auth + DDB read path end-to-end)
- **b) `get_task_load_summary`** → `active` and `overdue` keys present (validates compute path)
- **c) DDB cache warm** → direct DDB query on `CACHE#matthew / TOOL#*` ≥10 entries (validates nightly warmer ran)

Also fixed the **pre-existing IAM bug**: `check_lambda_secrets()` has always called
`secretsmanager:ListSecrets` + `lambda:ListFunctions`, but the qa-smoke IAM role had
zero Secrets Manager or Lambda permissions. This caused silent AccessDenied failures on
every QA run. Fixed in `role_policies.py` with 4 new statements.

**CDK changes:**
- `operational_stack.py`: Added `MCP_FUNCTION_URL` + `MCP_SECRET_NAME` env vars to QaSmoke
- `role_policies.py`: `operational_qa_smoke()` expanded 4 → 8 statements

### Bonus: 2 Pre-existing CDK Bugs Caught by CI
The H3/H5 linters caught real bugs that had been lurking:

1. **`email_stack.py` weekly-digest wrong handler**: `digest_handler.lambda_handler`
   (no such module exists). CDK would have overwritten the live handler to a broken value
   on the next `cdk deploy LifePlatformEmail`. Fixed → `weekly_digest_lambda.lambda_handler`.

2. **`lambda_helpers.py` docstring placeholder**: Used `lambda_function.lambda_handler`
   in the usage example — exactly the P0 bug pattern H5 catches. Fixed → `whoop_lambda.lambda_handler`.

### Deploys
- `life-platform-qa-smoke` Lambda code deployed ✅
- `LifePlatformOperational` CDK stack deployed ✅ (IAM + env vars)
- `LifePlatformEmail` CDK stack deployed ✅ (weekly-digest handler fix)
- Post-reconcile smoke: 10/10 ✅
- CI: 20/20 tests passing ✅

---

## Platform Status
- Version: v3.7.16
- All alarms: OK
- All CI: 20/20 (H1–H5, S1–S4 ×2, R1–R7)
- DLQ: 0
- SIMP-1 EMF data window: accumulating (started 2026-03-13, ready ~2026-04-13)

---

## Completed This Session
- ✅ R8-QS4: Deploy script archive (confirmed complete)
- ✅ R8-QS2: qa-smoke integration test (MCP tool calls + cache warm)
- ✅ Bonus: weekly-digest handler CDK bug fixed
- ✅ Bonus: lambda_helpers docstring placeholder fixed

## Open Tier 1 Items (from PROJECT_PLAN.md)
- R8-QS3: Update COST_TRACKER model routing entry (10 min, documentation hygiene)
- TB7-1: GitHub `production` Environment gate (5 min)
- TB7-2: Update `BRITTANY_EMAIL` env var to real address (5 min)

---

## Next Session — Recommended Order
1. **SIMP-1 Phase 1a: Habits cluster** — merge `get_habit_dashboard`, `get_habit_adherence`,
   `get_habit_streaks`, `get_habit_tier_report`, `get_habit_stacks`, `get_keystone_habits`
   into `get_habits(view=...)`. Files: `mcp/tools_habits.py`, `mcp/registry.py`.
   Reduction: 116 → ~111 tools (−5 net after new consolidated tool added).
2. **SIMP-1 Phase 1b** (same session if time): Health + Nutrition clusters.
3. **R8-ST1: Google Calendar integration** (~6-8h, highest-priority unbuilt feature).

---

## Files Changed This Session
- `lambdas/qa_smoke_lambda.py` — check_mcp_tool_calls() added, IAM-compatible imports
- `cdk/stacks/role_policies.py` — operational_qa_smoke() expanded (4→8 statements)
- `cdk/stacks/operational_stack.py` — QaSmoke env vars added
- `cdk/stacks/email_stack.py` — weekly-digest handler fixed, stale comment removed
- `cdk/stacks/lambda_helpers.py` — docstring placeholder fixed
- `docs/CHANGELOG.md` — v3.7.16 entry
- `handovers/HANDOVER_v3.7.16.md` — this file
