# Session Handover — 2026-03-15 — Backlog Sweep (v3.7.31)

**Platform version:** v3.7.31
**Session type:** Large backlog sprint — 9 items from buildable list

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

---

## Current State

**Platform:** v3.7.31 | **MCP tools:** 89 | **Lambdas:** 43 | **Layer:** v10

---

## Pending / Next Steps

1. **R20: Delete `webhook-key`** — run:
   ```bash
   aws secretsmanager delete-secret \
     --secret-id life-platform/webhook-key \
     --recovery-window-in-days 7 \
     --region us-west-2
   ```
   Then update `docs/ARCHITECTURE.md` and `docs/INFRASTRUCTURE.md` secrets count 11→10.

2. **CLEANUP-3: Google Calendar OAuth** — `python3 setup/setup_google_calendar_auth.py` (20 min, not engineering)

3. **Architecture Review #13** — `python3 deploy/generate_review_bundle.py` first. Targeting Apr 13.

4. **SIMP-1 Phase 2** — ≤80 tools, gated on 30 days EMF data (~Apr 13).

5. **IC-4/IC-5** — failure patterns + momentum. Data gate ~May 2026.

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
