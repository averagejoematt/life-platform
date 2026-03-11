# Life Platform — Handover v3.6.0
**Date:** 2026-03-10  
**Version:** v3.6.0  
**Session:** Board Sprint — all 4 voted items shipped with modified scope

---

## What Was Done This Session

All 4 Tech Board items built and verified (66/66 tests passing):

### Item 4 — AI-3 Middleware in `call_anthropic()` ✅
**Files changed:** `lambdas/ai_calls.py`, `lambdas/ai_output_validator.py`, `lambdas/weekly_plate_lambda.py`, `lambdas/monday_compass_lambda.py`, `tests/test_shared_modules.py`

- `call_anthropic()` now accepts `output_type=None, health_context=None` — validation activates automatically when `output_type` is passed
- Transparent fail-safe: ImportError → logs warning, returns raw output (no crash)
- `call_board_of_directors` wired with `AIOutputType.BOD_COACHING` + `health_context` dict
- `call_journal_coach` wired with `AIOutputType.JOURNAL_COACH`
- `_CORRELATION_AS_CAUSATION` patterns expanded 4→12 (direct causal assertions, certainty language, responsibility framing)
- `weekly_plate_lambda`: `GENERIC` → `NUTRITION_COACH` (calorie blocking now active)
- `monday_compass_lambda`: `GENERIC` → `WEEKLY_DIGEST` (correct type for planning digest)
- 6 new tests; bypass detector correctly allows `_HAS_AI_VALIDATOR` standalone pattern
- **Layer must be rebuilt + redeployed** (`bash deploy/build_layer.sh`) before AI-3 is live in Lambda

### Item 1 — Post-CDK Smoke Test ✅
**File:** `deploy/post_cdk_smoke.sh`

3-section deploy gate: CloudFront HTTPS → Lambda active+error-state → MCP warm ping.  
Usage: `bash deploy/post_cdk_smoke.sh` (add `--skip-mcp` if no API key in env)

### Item 2 — Pre-CDK Env Var Diff Check ✅
**File:** `deploy/cdk_env_diff.sh`

Two-direction diff: additions (low risk) + deletions (high risk, red). Requires `cdk.out/` for CDK-side comparison — run `cdk synth` first.  
Usage: `bash deploy/cdk_env_diff.sh LifePlatformEmail`  
CI mode: `bash deploy/cdk_env_diff.sh LifePlatformEmail --ci` (fails on deletions without prompt)

### Item 3 — ARCHITECTURE.md Header Auto-Update ✅
**Files:** `scripts/update_architecture_header.sh`, `scripts/install_hooks.sh`

Pre-commit hook installed. Runs automatically on every commit, stages the updated header.  
Detected: 42 Lambdas, 150 MCP tools (header now current).

---

## ⚠️ IMMEDIATE PENDING ACTIONS

| Priority | Item |
|----------|------|
| 🔴 ASAP | Confirm Brittany's real email → update `_brittany_env["BRITTANY_EMAIL"]` in `cdk/stacks/email_stack.py` |
| 🔴 ASAP | `bash deploy/build_layer.sh` → redeploy Layer + Lambdas (AI-3 middleware not live until this runs) |
| 🔴 ASAP | `npx cdk deploy LifePlatformEmail LifePlatformCompute` — pushes api-keys env var fixes + Brittany Lambda |
| 🔴 ASAP | `bash deploy/post_cdk_smoke.sh` — run after CDK deploy |
| ~Apr 7 | `life-platform/api-keys` secret permanent deletion |
| ~Apr 8 | SIMP-1 MCP tool audit + Architecture Review #7 |

---

## Platform State

| Dimension | Grade | Notes |
|-----------|-------|-------|
| Architecture | A | 42 Lambdas, CDK-owned, 8 stacks |
| Security | A | 13 dedicated IAM roles, secrets scoped |
| Reliability | A- | DLQ, canary, item size guard |
| Observability | A- | OBS-1 partial — email Lambdas only |
| Cost | A | ~$10/mo |
| Data Quality | A | DATA-2 wired, ingestion_validator on all 13 |
| AI/Analytics | **B→A path** | ai_output_validator wired in all email Lambdas; `call_anthropic()` middleware live after Layer redeploy |
| Maintainability | A- | Layer v4, 66 unit tests, pre-commit hook |
| Productization | B+ | PROD-2 complete |

---

## Open Items

| Status | Item |
|--------|------|
| 🔴 Blocked on deploy | Layer rebuild + CDK deploy (AI-3 middleware not live yet) |
| 🔴 Blocked on Brittany email | `brittany-weekly-email` Lambda deployed but BRITTANY_EMAIL is placeholder |
| ⚠️ Partial | OBS-1: `platform_logger` wired in email Lambdas only — ingestion rollout pending |
| 🔴 Open | SIMP-1: MCP tool rationalization (~Apr 8, after 30 days EMF data) |
| 🔴 Open | SEC-4: WAF rate limiting |
| 🔴 Open | MAINT-3: `.zip` cleanup |

---

## Key File Paths

- `lambdas/ai_calls.py` — `call_anthropic()` now accepts `output_type`, `health_context`
- `lambdas/ai_output_validator.py` — 12 causal language patterns
- `deploy/post_cdk_smoke.sh` — run after every CDK deploy
- `deploy/cdk_env_diff.sh` — run before every CDK deploy
- `scripts/update_architecture_header.sh` — auto-run by pre-commit hook
- `scripts/install_hooks.sh` — run once per clone to install hook
- `tests/test_shared_modules.py` — 66 tests, all passing
- `docs/CHANGELOG.md` — v3.6.0 entry written
- `cdk/stacks/email_stack.py` — Brittany email placeholder ⚠️

---

## Session Close Checklist

- [x] CHANGELOG.md updated (v3.6.0)
- [x] Handover written
- [ ] `git add -A && git commit -m "v3.6.0: Board sprint — AI-3 middleware, post-CDK smoke, env diff, architecture auto-update" && git push`
