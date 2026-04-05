# Handover — v5.0.0: Design & Product Review + Architecture A-

**Date:** 2026-04-04
**Scope:** DPR-1 (56 items across 2 phases), R20 architecture review (A- grade), ADR-046 S3 prefix separation, 27 production bug fixes, CI/CD improvements.

## What Changed

### Architecture Review #20 (A- grade, findings F01-F05 resolved)
- MCP tools count synced 115 to 121 (6 new tools added and registered)
- Architecture docs updated to match live system state
- `generate_review_bundle.py` Section 13b updated with R20 findings table
- INFRASTRUCTURE.md, ARCHITECTURE.md, RUNBOOK.md all reconciled

### DPR-1: Design & Product Review
**Phase 1** (43 items, 13 pages):
- Full visual + functional audit across 13 site pages
- Engagement pulse history feed (`engagement.js`) with daily log from April 1
- Field notes token display fix
- Character event log detail enrichment
- Habitify vice streak timing bug resolved

**Phase 2** (13 items across Practice + Platform + Chronicle + Utility):
- Practice, Platform, Chronicle, Utility page improvements
- Mobile home page: gauge overflow fix, hamburger menu scroll lock
- Achievements: 14 weight milestone badges (10 loss every 10 lbs + 4 target sub-280/250/220/200)
- Achievements: Arena to Challenge badge rename
- Active challenge status matching fix

### ADR-046: S3 Prefix Separation
- `site/` for static assets, `generated/` for Lambda-written files
- `safe_sync.sh` updated with complete exclude list for all Lambda-generated files
- Bucket policy protects `config/*` and `data/*` directories from sync --delete
- Prevents deploy-time deletion of Lambda-generated content

### New Endpoints & Features
- `/api/pulse_history` endpoint — daily log feed from April 1
- Sleep observatory: `best_efficiency` field added
- Glucose observatory: source fixed `dexcom` to `apple_health`, field names corrected
- Glucose added to allowed AI analysis expert keys
- Observatory week + weight_progress: experiment date clamping to EXPERIMENT_START

### Production Bug Fixes (27 issues, 3 sweeps)
- `safe_sync.sh`: Lambda-generated file exclusions (character_stats.json, etc.)
- Config and data directory protection from S3 sync --delete
- 8 user-reported issues (commit bad4a80)
- 9 user-reported issues (commit 4980e23)
- Achievements 10lb badge threshold
- Challenges active status matching

### Light Mode Compatibility
- AI expert cards moved outside try/catch blocks
- Light mode CSS variables added for AI expert card theming

### Infrastructure & CI/CD
- Shared Lambda layer: v22 to v25
- Full pytest suite wired into CI/CD pipeline
- Claude Code config: `/deploy` command, `/qa` command, `.mcp.json`
- `google_calendar_lambda.py` deleted (ADR-030)
- Product review prompt PR-1 added

### Documentation
- DPR-1 review documents (Phase 1 + Phase 2), implementation brief, execution prompt
- CLAUDE.md updated for v5.0.0
- DECISIONS.md updated with ADR-046
- INTELLIGENCE_LAYER.md updated for v4.8.0 AI overhaul

## What to Verify

### Smoke Tests
- [ ] `bash deploy/deploy_and_verify.sh site-api` — full site API smoke
- [ ] Visit averagejoematt.com and spot-check: pulse history feed, achievements page (weight badges), glucose observatory
- [ ] Mobile viewport: home page gauges should not overflow, hamburger menu should lock scroll
- [ ] Light mode toggle: AI expert cards should render with correct colors
- [ ] `/api/pulse_history` returns entries from April 1 onward
- [ ] Sleep observatory response includes `best_efficiency` field
- [ ] Run `python3 -m pytest tests/ -v` — expect 1075+ tests passing

### Deploy Safety
- [ ] `bash deploy/lib/safe_sync.sh` — confirm Lambda-generated files are excluded from --delete
- [ ] S3 `config/*` and `data/*` prefixes are not deleted during deploy
- [ ] Shared layer is at v25 — run `aws lambda get-layer-version --layer-name life-platform-shared --version-number 25`

## Known Issues / Carry Forward

- **sync_doc_metadata.py** — archived to `deploy/archive/onetime/`. Session close checklist in RUNBOOK still references it. May need cleanup.
- **Protocol adherence on sleep page** — needs design decision
- **TDEE tracking** — MacroFactor doesn't export TDEE; no current workaround
- **Glucose intraday curve** — needs raw 5-min CGM readings (not available from Apple Health bridge)
- **IC-4/IC-5** (failure pattern + momentum warning) — data gate ~May 1
- **SIMP-1 Phase 2** — accepted via ADR-045 (118 to 115, not pursuing <=80 tools)
- **DPR-1 Phase 3** — not yet scoped; Phase 1+2 covered 56 of estimated total items

## Current System State

| Metric | Value |
|--------|-------|
| MCP Tools | 121 |
| Lambdas | 62 |
| Site Pages | 72 |
| Lambda Layer | v25 |
| Architecture Grade | A- (R20) |
| Pytest Tests | 1075+ |
| CDK Stacks | 8 |
| DynamoDB Table | life-platform (single-table, no GSIs) |
| Version | v5.0.0 |

## Key Files Modified (18 commits)

**Lambda / Backend:**
- `deploy/lib/safe_sync.sh` — Lambda-generated file exclusions
- `lambdas/site_api_lambda.py` — pulse_history, achievements, glucose, sleep observatory
- `lambdas/google_calendar_lambda.py` — deleted (ADR-030)

**Frontend:**
- `site/engagement.js` — pulse history feed
- `site/` — mobile fixes, light mode CSS, achievement badges

**Infrastructure:**
- `cdk/stacks/` — ADR-046 S3 prefix separation, IAM updates
- `.mcp.json` — Claude Code MCP config

**Documentation:**
- `docs/CHANGELOG.md` — v5.0.0 entry
- `docs/CLAUDE.md` — v5.0.0 conventions
- `docs/DECISIONS.md` — ADR-046
- `docs/INTELLIGENCE_LAYER.md` — v4.8.0 AI overhaul
- `reviews/DPR-1*.md` — design & product review documents
