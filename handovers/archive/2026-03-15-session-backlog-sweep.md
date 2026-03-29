# Session Handover — 2026-03-15 — Backlog Sweep + Power Tuning + Doc Consolidation (v3.7.34)

**Platform version:** v3.7.34
**Session type:** Large multi-part session — backlog sprint + R5 power tuning + R48 doc consolidation + inbox hygiene

---

## What Was Done

### Risk-7 — Compute staleness alarm
- `bash deploy/create_compute_staleness_alarm.sh` ✅
- Alarm `life-platform-compute-pipeline-stale` is live in CloudWatch.

### ADR-027 — Stable MCP Layer v10
- `bash deploy/build_mcp_stable_layer.sh` ✅
- Published `life-platform-shared-utils:10` — adds `mcp/` core modules (config, core, helpers, labs_helpers, strength_helpers, utils) to the Layer.
- Updated `cdk/stacks/email_stack.py` and `cdk/stacks/ingestion_stack.py` to reference `:10`.
- `npx cdk deploy LifePlatformIngestion LifePlatformEmail` ✅ — both stacks updated to Layer v10.

### R57 — Attia centenarian benchmarks MCP tool
- `mcp/strength_helpers.py`: added `_ATTIA_TARGETS`, `_ATTIA_STATUS_TIERS`, `attia_benchmark_status()`.
- `mcp/tools_strength.py`: added `tool_get_centenarian_benchmarks()`.
- `mcp/registry.py`: switched `from tools_strength import *` to explicit imports; added `get_centenarian_benchmarks` tool.
- Tool targets: deadlift 2.0×BW, squat 1.75×, bench 1.5×, OHP 1.0×. Returns status tier, % of target, lbs to close gap, overall readiness, priority lift.
- MCP Lambda deployed ✅ 2026-03-15T05:56:01Z.

### R6 — Per-tool 30s soft timeout
- `mcp/handler.py`: added `import concurrent.futures`; wrapped tool call in `ThreadPoolExecutor(max_workers=1)` with 30s timeout. On `TimeoutError` returns `mcp_error(QUERY_TOO_BROAD)` instead of burning to the 300s Lambda hard limit.
- MCP Lambda deployed in same deploy as R57 ✅.

### R54 — Evening nudge Lambda
- `lambdas/evening_nudge_lambda.py` (new): checks supplements, journal (Notion), How We Feel at 8 PM PT. Only sends email if ≥1 source missing. Amber HTML email design.
- `cdk/stacks/email_stack.py`: `EveningNudge` Lambda added, schedule `cron(0 3 * * ? *)`.
- `cdk/stacks/role_policies.py`: `email_evening_nudge()` added — DDB GetItem+Query, KMS, SES, DLQ (no ai-keys).
- `npx cdk deploy LifePlatformEmail` ✅ — Lambda created, IAM approved, deployed in 129s.

### R20 — Secrets consolidation audit
- `bash deploy/consolidate_secrets.sh` ✅ (read-only audit)
- **Finding:** `life-platform/habitify` IS actively read by `habitify-data-ingestion` via `HABITIFY_SECRET_NAME` env var — **cannot delete**.
- **Finding:** `life-platform/webhook-key` has `LastAccessed: None` and zero Lambda references — **safe to delete**.
- Tracker updated: scope reduced to just webhook-key deletion (5 min, $0.40/mo saving).

### R1 confirmed already done
- `daily_brief_lambda.py` v2.82.0 reads from `computed_metrics` partition. Inline compute is fallback-only. R1 is complete.

### Sync + commit
- `python3 deploy/sync_doc_metadata.py --apply` ✅ — auto-updated tool count 88→89, lambda count 45→43.
- `git commit + push` ✅ — edaac50

### R5 — Lambda Power Tuning
- Deployed AWS Lambda Power Tuning SAR (serverlessrepo-lambda-power-tuning)
- Ran against `life-platform-mcp` at 512/768/1024/1536 MB, 10 invocations each
- **Result: 768 MB is cost-optimal** — $0.00000029/invocation, 21.8ms avg
- CDK had drift (512 MB in code, 1024 MB live) — both fixed to 768 MB
- MCP server + warmer both updated in `cdk/stacks/mcp_stack.py`
- `npx cdk deploy LifePlatformMcp` ✅

### R48 — Doc consolidation
- `DATA_DICTIONARY.md` merged into `SCHEMA.md` (SOT domains, overlap map, data gaps as header sections)
- `FEATURES.md` + `USER_GUIDE.md` (both at stale v2.91.0) replaced with fresh `PLATFORM_GUIDE.md`
- 3 docs archived, 1 new doc, net 25→22 active docs
- `docs/ARCHITECTURE.md` doc index updated

### Inbox hygiene (bonus)
- Removed `add_ok_action` from `cdk/stacks/lambda_helpers.py` — all CDK Lambda alarms now ALARM-only
- `deploy/create_withings_oauth_alarm.sh` — removed `--ok-actions` flag
- Live Withings alarm updated directly in AWS
- Rule: email in inbox = something broken, action required

### sync_doc_metadata.py fixes
- `secret_count` 11→10, cost note updated
- `DATA_DICTIONARY.md` rule removed (file archived)
- `secrets_cost` recompute formula updated

### Deploys
- `npx cdk deploy LifePlatformMcp` ✅ (768MB memory + OK action removal)
- `npx cdk deploy LifePlatformEmail` ✅ (evening nudge + Layer v10)
- `npx cdk deploy LifePlatformIngestion` ✅ (Layer v10)

---

## Current State

**Platform:** v3.7.34 | **MCP tools:** 89 | **Lambdas:** 43 | **Secrets:** 10 | **Layer:** v10 | **MCP memory:** 768 MB

---

## Pending / Next Steps

1. **CLEANUP-3: Google Calendar OAuth** — `python3 setup/setup_google_calendar_auth.py` (20 min, non-engineering)

2. **Architecture Review #13** — `python3 deploy/generate_review_bundle.py` first. Targeting Apr 13.

3. **SIMP-1 Phase 2** — ≤80 tools, gated on 30 days EMF data (~Apr 13).

4. **MacroFactor CSV import** — top blocked item. All nutrition tools on mock data.

5. **IC-4/IC-5** — failure patterns + momentum. Data gate ~May 2026.

6. **webhook-key permanent deletion** — auto-deletes 2026-03-22 (already scheduled, no action needed).

---

## Files Created/Modified

| File | Action |
|------|--------|
| `mcp/strength_helpers.py` | Modified — Attia benchmark data + `attia_benchmark_status()` |
| `mcp/tools_strength.py` | Modified — `tool_get_centenarian_benchmarks()` |
| `mcp/registry.py` | Modified — explicit imports + `get_centenarian_benchmarks` entry |
| `mcp/handler.py` | Modified — `concurrent.futures` + 30s tool timeout |
| `lambdas/evening_nudge_lambda.py` | Created — R54 evening nudge |
| `cdk/stacks/email_stack.py` | Modified — EveningNudge Lambda + Layer v10 ARN |
| `cdk/stacks/ingestion_stack.py` | Modified — Layer v10 ARN |
| `cdk/stacks/role_policies.py` | Modified — `email_evening_nudge()` policy |
| `deploy/consolidate_secrets.sh` | Created — R20 audit script |
| `docs/reviews/.../09-recommendation-tracker.md` | Updated — R20 scope clarified |
| `docs/CHANGELOG.md` | Updated — v3.7.31 entry |
