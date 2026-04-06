# Handover — v5.4.0: Product Board Sprint + V3/V3.1 Observatory Redesign

**Date:** 2026-04-05
**Scope:** Product Board sprint (PB-01–07), V3 Observatory redesign (PB-09), V3.1 Observatory polish (PB-09.1). Verification sweep, Weekly Signal email, protocol adherence, coach-led dashboard restructure across 8 pages, then polish pass (deltas, subtitles, deep collapse, Elena/journaling fix). Also: MCP Lambda 502 fix, AI expert analyzer V3 upgrade, disposable email blocklist, CI fix.

## What Changed

### Pre-Sprint Fix: MCP Lambda 502 (Canary Spam)

- **Root cause:** CDK redeploy at 04:39 UTC packaged MCP Lambda from `lambdas/` directory instead of repo root (`mcp_server.py` + `mcp/` package). Caused `ModuleNotFoundError: No module named 'mcp_server'` on every invocation.
- **Fix:** Redeployed MCP Lambda + warmer with correct code. Fixed CDK `mcp_stack.py` to stage `mcp_server.py` + `mcp/` into a clean temp directory (`_mcp_staging/`) instead of using the generic `../lambdas` code asset. Added `code` parameter override to `create_platform_lambda` helper.
- **Canary:** All 3 checks pass (DDB, S3, MCP with 115 tools). MCP alarm cleared.

### PB-01: Discoveries Verification ✅
- `/api/journey_timeline` returns 7+ events (4 Day 1 seeds + level_ups + experiments)
- MCP registry tests pass (7/7) — annotation tools registered
- DISC-7 marked ✅ DONE in `BACKLOG_HANDOFF_CLAUDE_CODE.md`

### PB-02: get_nutrition Bug Closure ✅
- All 8 tests pass in `test_get_nutrition_args.py`
- Marked ✅ DONE in backlog

### PB-03: OG Share Cards ✅
- All 7 OG images return 200 (home, sleep, glucose, training, character, nutrition, mind)
- Homepage meta tags correct: `og:image`, `og:image:width` (1200), `og:image:height` (630), `twitter:card` (summary_large_image)
- Share button present with Web Share API + clipboard fallback

### PB-04: Sleep Observatory V2 ✅
- **Audit result:** Page was already ~85% aligned with editorial pattern (hero, gauges, pull-quotes, section headers, freshness, reading path nav all present)
- **Gap closed:** Added AI expert analysis card (`renderAIAnalysisCard` with `sleep` expert key)
- Added `sleep` to site-api AI analysis whitelist
- Added `sleep` + `glucose` to `components.js` EXPERTS config (Dr. Park's Sleep Analysis, Dr. Patrick's Metabolic Assessment)
- Deployed: sleep page to S3, components.js to S3, site-api Lambda

### PB-05: Glucose Observatory V2 ✅
- **Audit result:** Page was already ~90% aligned — all editorial elements present including AI card
- **Gap closed:** Added `glucose` to `components.js` EXPERTS config (was calling `renderAIAnalysisCard` but key wasn't registered). AI card now renders with existing analysis data.

### PB-06: Weekly Signal Subscriber Email ✅ — NEW LAMBDA
- **Lambda:** `weekly-signal` (`lambdas/weekly_signal_lambda.py`)
- **Schedule:** `cron(30 16 ? * SUN *)` — Sunday 9:30 AM PT (30 min after Matthew's private digest)
- **5-section email:** The Numbers, Chronicle Preview, What Worked, The Board Says, Observatory Spotlight
- **Data sources:** `generated/public_stats.json` (S3), `generated/journal/posts.json` (S3), DynamoDB computed_insights
- **Pattern:** Modeled exactly on `chronicle_email_sender_lambda.py` — same subscriber query, SES rate limiting, per-subscriber error handling, unsubscribe links
- **Deployed** via `LifePlatformEmail` CDK stack. Test invocation: sent to 1 subscriber successfully.
- **IAM:** `email_weekly_signal()` in `role_policies.py` — DDB read, S3 read (generated/*), KMS, SES, DLQ

### PB-07: Protocol Adherence Card ✅
- Made the sleep onset card data-driven (was static "70%")
- Added `sleep_start` to `/api/sleep_detail` trend response (from Whoop DynamoDB records)
- JavaScript calculates from last 30 days of `sleep_start` data:
  - Converts UTC → PT, counts days with onset < 11:00 PM
  - Calculates average recovery on adherent vs non-adherent days
  - Shows delta with Henning Brandt confidence label when N<30
- Falls back gracefully with insufficient data messages

### Sleep AI Expert Analyzer — FIXED POST-SPRINT
- `sleep` expert was missing from `ai_expert_analyzer_lambda.py` EXPERTS list
- Added `gather_data_for_expert("sleep")` branch (reads Whoop + Eight Sleep data)
- Added Dr. Lisa Park persona (sleep & circadian specialist)
- Generated initial analysis (1503 chars). Dr. Park's card on sleep page now renders content.

### V3 Observatory Redesign (PB-09) ✅
- **Phase 1 (Foundation):** Created `observatory-v3.css` + `observatory-v3.js` shared module (6 named function exports). Upgraded `ai_expert_analyzer_lambda.py` to V3: rotating analytical lens, enhanced data gathering (sleep onset/temp/REM, training recovery/modality, nutrition fiber), labs context override, max_tokens 1200, week_number + prior_recommendation anti-repetition. Generated V3 analyses for all 8 experts (1700-2400 chars).
- **Phase 2 (Observatory Pages):** Restructured Sleep, Physical, Training, Nutrition, Glucose (Approach B — status bar → coach → trends → detail → cross-domain → depth) and Mind (Approach C — Conti Amendment, hero stays visible).
- **Phase 3 (Habits + Labs):** Habits V3-lite (editorial collapsed, T1/T2 collapsed). Labs: Dr. Okafor promoted to position 2.

### V3.1 Observatory Polish (PB-09.1) ✅
- **Item 1 (P0):** Week-over-week deltas — `computeDelta()` + `_renderDelta()` in shared JS with polarity-aware color coding
- **Item 2 (P0):** Complete depth-section collapse on Nutrition (7 sections) + Training (11 sections) — editorial, hypotheses, protocols, empty placeholders all in `<details>`
- **Item 3 (P1):** One-line page subtitles on all 6 observatory pages for first-time visitor context
- **Item 4 (P1):** Specific depth section labels with teasers replacing generic "Deep Dive"
- **Item 5 (P2):** Section divider CSS (`obs-section-divider`)
- **Item 6 (P2):** Depth section teaser support in `renderDepth()`
- **Item 7 (P1):** Mind page Elena quote / journaling prompt separation — fixed `rsplit` parsing order in Lambda, journaling prompt renders in own purple-bordered block
- **Coach timestamp:** Added "Saturday, April 5, 2026 · 7:00 AM PT · Day 5 Observations" prefix to all coach cards

### Other Fixes
- **CI/CD fix:** Removed retired `google_calendar` from `lambda_s3_paths.json` — was failing `test_s2` on every push
- **Disposable email blocklist:** Added domain blocklist to `email_subscriber_lambda.py` — prevents SES bounces from fake signups (example.com, mailinator.com, etc.)
- **Test subscriber cleanup:** Deleted 9 test/junk DynamoDB subscriber records

### PB-08: Intelligence Page Rebuild — NOT STARTED (per plan)
- Gated on SIMP-1 Phase 2 (~April 13)

## Files Changed

| File | Change |
|------|--------|
| `cdk/stacks/mcp_stack.py` | MCP code asset now uses staging directory |
| `cdk/stacks/lambda_helpers.py` | Added `code` parameter override |
| `cdk/stacks/email_stack.py` | Added weekly-signal Lambda (PB-06) |
| `cdk/stacks/role_policies.py` | Added `email_weekly_signal()` IAM policy |
| `lambdas/weekly_signal_lambda.py` | NEW — Weekly Signal subscriber email |
| `lambdas/ai_expert_analyzer_lambda.py` | V3 prompts, sleep expert, V3.1 rsplit parsing fix for Elena/journaling |
| `lambdas/site_api_lambda.py` | `sleep` AI key, `sleep_start` in trend, `week_number` in response |
| `lambdas/email_subscriber_lambda.py` | Disposable domain blocklist |
| `site/assets/css/observatory-v3.css` | NEW — V3 + V3.1 styles (deltas, subtitles, teasers, journaling prompt) |
| `site/assets/js/observatory-v3.js` | NEW — V3 + V3.1 module (deltas, teasers, journaling, coach timestamp) |
| `site/sleep/index.html` | V3 + subtitle + protocol adherence |
| `site/physical/index.html` | V3 + subtitle |
| `site/training/index.html` | V3 + V3.1 deep collapse + subtitle |
| `site/nutrition/index.html` | V3 + V3.1 deep collapse (7 sections) + subtitle |
| `site/glucose/index.html` | V3 + subtitle |
| `site/mind/index.html` | V3 Approach C + subtitle + journaling prompt block |
| `site/habits/index.html` | V3-lite (editorial + T1/T2 collapsed) |
| `site/labs/index.html` | V3 coach promotion (Dr. Okafor at position 2) |
| `ci/lambda_s3_paths.json` | Removed retired google_calendar reference |
| `site/assets/js/components.js` | Added `sleep` + `glucose` to EXPERTS config |
| `docs/BACKLOG_HANDOFF_CLAUDE_CODE.md` | DISC-7 + get_nutrition marked ✅ DONE |
| `docs/ARCHITECTURE.md` | Lambda count 62→63, added weekly-signal |
| `CLAUDE.md` | Lambda count 62→63 |
| `.gitignore` | Added `cdk/_mcp_staging/` |

## What to Verify

### Smoke Tests
- [ ] `curl https://averagejoematt.com/api/sleep_detail` — trend items include `sleep_start`
- [ ] `curl https://averagejoematt.com/api/ai_analysis?expert=sleep` — returns 200 (analysis may be null)
- [ ] `curl https://averagejoematt.com/api/ai_analysis?expert=glucose` — returns analysis text
- [ ] Sleep page — protocol adherence card shows data-driven percentages
- [ ] Sleep page — AI expert analysis section present
- [ ] Weekly Signal — test invocation sends to subscribers

### CDK
- [ ] `cdk diff --all` shows no changes (Email + MCP stacks deployed)

## Known Issues / Carry Forward

- **Protocol adherence on sleep page** — onset < 11pm card is data-driven; other 3 cards (screen-off, temp, alcohol) remain static placeholders. Making them data-driven requires tracking data not yet in the API.
- **TDEE tracking** — blocked (MacroFactor doesn't export)
- **Glucose intraday curve** — blocked (no raw 5-min CGM readings)
- **IC-4/IC-5** (failure pattern + momentum warning) — data gate ~May 1
- **DPR-1 Phase 3** — not yet scoped
- **PRE-13 Data Publication Review** — deferred
- **PB-08 Intelligence Page Rebuild** — gated on SIMP-1 Phase 2 (~April 13)
- **~~Sleep AI analysis~~** — FIXED. Added sleep expert to ai_expert_analyzer_lambda.py, generated initial content.

## Current System State

| Metric | Value |
|--------|-------|
| MCP Tools | 115 |
| Lambdas | 63 |
| Site Pages | 72 |
| Lambda Layer | v26 |
| Architecture Grade | A- (R20) |
| CDK Stacks | 8 |
| Version | v5.4.0 |
