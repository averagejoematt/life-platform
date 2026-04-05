# Handover — v5.1.1: Bug Bash + Documentation Overhaul + Pipeline Fixes

**Date:** 2026-04-05
**Scope:** Full-stack bug bash (32 fixes across 4 domains), ADR-046 CDK deploy, documentation audit + archive, 48 completed specs archived. Then: /api/labs IAM fix, Garmin layer + OAuth resilience, stale backlog cleanup.

## What Changed

### ADR-046: CDK Deploy (CloudFormation Sync)
- S3GeneratedOrigin + 6 cache behaviors now owned by CloudFormation (was manual CLI)
- Future `cdk deploy` cannot accidentally revert the generated/ prefix routing
- All 8 CDK stacks deployed successfully

### Bug Bash Round 1 (10 fixes, deployed)
**Critical — data safety:**
- Journal post HTML moved from `site/journal/` to `generated/journal/` (was being deleted by sync)
- Findings S3 write moved from `site/findings/` to `generated/findings/`
- Error responses now include `Cache-Control: no-cache, no-store` (503s were cached 5 min)

**High:**
- Subscriber onboarding fixed: reads `generated/journal/posts.json` (was `site/chronicle/posts.json`)
- Accountability page: replaced hardcoded Lambda Function URL with `/api/subscribe` (was bypassing CloudFront WAF)
- Lift glyph: only counts strength activities (WeightTraining, Crossfit, HIIT, Yoga) — was showing green for walks
- Site-api docstring + CLAUDE.md updated to reflect actual write capabilities

**Medium:**
- Platform counts in daily-brief: 95→121 MCP, 19→26 sources, 50→62 Lambdas
- Challenge dynamic status stored by both full ID and stripped catalog ID
- 10 missing weight milestone badge SVGs created (lost_10 through lost_100, sub_250)

### Bug Bash Round 2 (22 files, deployed)
**Infrastructure cleanup:**
- Removed Phase 1 site-api Lambda + duplicate alarms from web_stack (131 lines)
- Updated 3 IAM policies for `generated/` prefix (og-image, chronicle-approve, stats-refresh)
- Staggered 3 concurrent cron schedules: daily-brief 17:00, subscriber-onboarding 17:05, mcp-warmer 17:10
- Added `buddy/*` and `blog/*` to bucket policy deletion protection
- Scoped SES permissions from wildcard to domain identity (subscriber-onboarding, canary)
- Fixed CI smoke test Lambda name: `qa-smoke` → `life-platform-qa-smoke`

**Frontend safety:**
- Added `r.ok` checks to ~20 fetch calls across 14 pages + 2 shared JS files
- Removed duplicate `startWeight=307` on homepage (uses dynamic value)
- Removed duplicate `.reading-path-v2` CSS definition
- Removed dead `reading_paths` object from site_constants.js

### Documentation Overhaul
**Staleness fixes (11 files):**
- MCP tools: 121 → 115 across 8 docs (CLAUDE.md, ARCHITECTURE, SCHEMA, RUNBOOK, ONBOARDING, INFRASTRUCTURE, OPERATOR_GUIDE, MCP_TOOL_CATALOG)
- Lambda layer: v22/v25 → v26 (CLAUDE.md, constants.py, ARCHITECTURE, RUNBOOK)
- Cron schedules corrected: daily-brief 18:00→17:00 UTC, anomaly 16:05→15:05 UTC
- Site-api "read-only" → "primarily read-only" with limited writes noted
- ADR-046 added to DECISIONS.md index table
- Data sources 19 → 26 in ONBOARDING.md
- Google Calendar removed from ONBOARDING (retired ADR-030)
- `generated/` prefix added to INFRASTRUCTURE.md S3 section
- deploy/MANIFEST.md marked as deprecated

**Archived (48 files → docs/archive/):**
- Completed implementation specs, session briefs, one-time prompts, offsite build plans, usability studies, visual briefs
- Git history preserved via `git mv`

### v5.1.1 Fixes (same day, deployed)

**`/api/labs` 503 — FIXED:**
- Root cause: site-api IAM role lacked S3 `dashboard/*` read. `clinical.json` existed with 74 biomarkers but Lambda couldn't read it (AccessDenied → 503).
- Fix: Added `dashboard/*` and `generated/*` S3 read + `generated/findings/*` write to `role_policies.py:site_api()`. Deployed via `LifePlatformOperational` stack.

**Garmin ingestion broken — FIXED:**
- Root cause 1: `garth-layer` (v2) not attached to Lambda. CDK redeploy on 2026-04-05 04:39 UTC dropped it. Fix: Added `GARTH_LAYER_ARN` to `constants.py`, wired `additional_layers=[garth_layer]` in `ingestion_stack.py`. Deployed via `LifePlatformIngestion` stack.
- Root cause 2: Garmin OAuth 429 rate limit cascade. When OAuth2 token expired, garth tried to refresh on every API call (14 calls/day × 5 gap days = 70+ exchange endpoint hits). Fix: proactive single refresh attempt in `get_garmin_client()` with early bail on 429, circuit breaker (2 consecutive failures → abort gap-fill), eager token save to Secrets Manager. Deployed via `deploy_lambda.sh`.
- Re-authed via `setup_garmin_browser_auth.py`. Backfilled 4 missing days (Mar 30, Apr 2-4). All Garmin data current.

**Stale documentation — FIXED:**
- `docs/BACKLOG_HANDOFF_CLAUDE_CODE.md`: Marked HP-13 (share cards), BL-01 (builders page), BL-02 (labs page) as ✅ DONE with implementation details. These were completed in prior sessions but backlog still listed them as greenfield.
- `docs/INCIDENT_LOG.md`: Resolved open Garmin P3 incident (2026-03-19).
- `docs/HANDOVER_LATEST.md` pointer updated from v4.7.0 to v5.1.1.

## What to Verify

### Smoke Tests
- [ ] `curl https://averagejoematt.com/public_stats.json` — returns data (generated/ origin)
- [ ] `curl https://averagejoematt.com/api/pulse` — lift glyph gray on non-strength days
- [ ] `/api/challenges` — active challenge appears with correct status
- [ ] Achievements page — all 14 weight milestone badges render with icons
- [ ] Accountability subscribe form — uses `/api/subscribe` (not raw Lambda URL)
- [ ] `curl -sI https://averagejoematt.com/api/nonexistent` — has `Cache-Control: no-cache`

### CDK
- [ ] `cdk diff --all` shows no changes (all 8 stacks deployed)
- [ ] Layer version 26 in use: `aws lambda get-layer-version --layer-name life-platform-shared-utils --version-number 26`

### Documentation
- [ ] `docs/` directory — only active reference docs, operational docs, and future specs remain
- [ ] `docs/archive/` — 48+ completed specs archived with git history

## Known Issues / Carry Forward

- **~~Garmin not syncing~~** — FIXED and DEPLOYED. Layer attached, OAuth resilience added, re-authed, 4 days backfilled. All data current.
- **~~`/api/labs` returns 503~~** — FIXED and DEPLOYED. IAM policy updated, endpoint returning 200.
- **Protocol adherence on sleep page** — needs design decision
- **TDEE tracking** — blocked (MacroFactor doesn't export)
- **Glucose intraday curve** — blocked (no raw 5-min CGM readings from Apple Health)
- **IC-4/IC-5** (failure pattern + momentum warning) — data gate ~May 1
- **DPR-1 Phase 3** — not yet scoped
- **PRE-13 Data Publication Review** — genome/lab/supplement granularity deferred
- **Strava walk steps** — movement glyph doesn't estimate steps from Strava walk distance (enhancement, not bug)

## Current System State

| Metric | Value |
|--------|-------|
| MCP Tools | 115 |
| Lambdas | 62 |
| Site Pages | 72 |
| Lambda Layer | v26 |
| Architecture Grade | A- (R20) |
| CDK Stacks | 8 |
| DynamoDB Table | life-platform (single-table, no GSIs) |
| Version | v5.1.1 |

## Key Commits

| Hash | Description |
|------|-------------|
| `78e56cb` | fix: bug bash — 10 fixes across data safety, API, and frontend |
| `8f5de93` | fix: bug bash round 2 — infra cleanup, frontend safety, IAM hardening |
| `e933949` | docs: fix staleness across 11 docs + archive 48 completed specs |
