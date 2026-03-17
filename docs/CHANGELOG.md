## v3.7.66 — 2026-03-17: MCP Key bug fix + BS-T2-5 complete

### Summary
Two fixes shipped. MCP `Key` NameError resolved (missing boto3.dynamodb.conditions import in `tools_lifestyle.py` — was breaking `list_experiments`, `create_experiment`, `end_experiment`, and any other experiments function using `Key()` expressions). BS-T2-5 Chronicle Newsletter Full Delivery completed: rate bump to SES production limits + token-based unsubscribe replacing raw-email URL exposure.

### MCP `Key` NameError Fix
- `mcp/tools_lifestyle.py`: Added `from boto3.dynamodb.conditions import Key` import (line 10). Was present in usage at lines 285 and 2455 but never imported. Affected `list_experiments`, `create_experiment`, `end_experiment`, `get_experiment_results`, `log_insight`, and related functions. **MCP DEPLOYED ✅**

### BS-T2-5: Chronicle Newsletter Full Delivery — COMPLETE ✅
- `cdk/stacks/email_stack.py`: `SEND_RATE_PER_SEC` bumped `"1.0"` → `"14.0"`. At 14/sec, ~300 subscribers deliver in ~22s. **CDK LifePlatformEmail DEPLOYED ✅**
- `lambdas/chronicle_email_sender_lambda.py`: Unsubscribe URL changed from `?email=<raw>` to `?h=<email_hash>` — raw email never exposed in URL params. Function signature updated to accept full subscriber dict. **DEPLOYED ✅**
- `lambdas/email_subscriber_lambda.py`: `handle_unsubscribe_by_hash()` added. Router prefers `?h=` param (backward-compatible). Welcome email unsub link updated to hash-based. **DEPLOYED ✅**

### Sprint 3 Status
- BS-T2-5: ✅ COMPLETE (was ⚠️ 90%)
- Sprint 3 now 5/9 complete

---
# Life Platform — Changelog

## v3.7.65 — 2026-03-17: Sprint 3 partial — IC-28, WEB-WCT, BS-13 deployed

### Summary
First Sprint 3 session. 3 of 9 Sprint 3 features shipped. IC-28 wires ACWR training load into Daily Brief context. WEB-WCT adds a persistent weekly challenge ticker to all 5 site pages. BS-13 launches the `/experiments` public archive page. BS-T2-5 assessed: 90% complete (pipeline already works, rate bump + token-based unsubscribe remain). MCP `Key` import error flagged for cleanup.

### IC-28: Training Load Intelligence (IC feature)
- `lambdas/daily_insight_compute_lambda.py`: `_build_acwr_signal()` added. Reads ACWR fields (`acwr`, `acwr_zone`, `acwr_alert`, `acwr_alert_reason`, `acute_load_7d`, `chronic_load_28d`) from `computed_7d` records. Injects as priority-4 signal (danger/caution/detraining) or priority-8 (safe) into `ai_context_block`. Wired in `lambda_handler` step 5h (non-fatal). **DEPLOYED ✅**
- `lambdas/ai_calls.py`: `_build_acwr_coaching_context()` added. Reads ACWR from `data["computed_metrics"]`. Zone-specific coaching rules injected into `call_training_nutrition_coach` prompt — DANGER zone is a hard instruction. **DEPLOYED ✅** (via daily-brief multi-file deploy)
- Timing confirmed correct: ACWR runs 9:55 AM PT (16:55 UTC), insight-compute runs 10:45 AM PT (17:45 UTC). No CDK change needed.

### WEB-WCT: Weekly Challenge Ticker
- `site/assets/css/base.css`: `.challenge-bar` component added — fixed bottom bar, 36px height, amber pip + label + text + progress. `body { padding-bottom: 36px }` added. Mobile: text hidden, label only.
- `site/config/current_challenge.json`: Seeded to S3 (`site/config/current_challenge.json`). Week 4 challenge: "4+ protein feedings of 30g+ daily".
- `lambdas/site_api_lambda.py`: `/api/current_challenge` route added. Reads from S3 `site/config/current_challenge.json` via boto3 (not public URL). Route registered in ROUTES dict. IAM `S3SiteConfigRead` policy added inline and to `role_policies.py`. **DEPLOYED ✅** (us-east-1 direct zip deploy)
- `site/index.html`, `site/journal/index.html`, `site/character/index.html`, `site/platform/index.html`: Challenge bar HTML + fetch script added before `</body>`. **S3 SYNCED ✅**
- `cdk/stacks/role_policies.py`: `site_api()` updated with `S3SiteConfigRead` statement (`s3:GetObject` on `site/config/*`). IAM inline policy applied live via `aws iam put-role-policy`.
- Smoke test: `curl https://averagejoematt.com/api/current_challenge` returns full challenge JSON. ✅

### BS-13: N=1 Experiment Archive (Website)
- `site/experiments/index.html`: New page. Reads from `/api/experiments`. Filter buttons (All / Active / Completed / Abandoned). Experiment cards with status badge, hypothesis, day counter, 4-field data grid, outcome row. Active experiments show amber top-border accent. Empty state with graceful message. N=1 methodology explainer strip (H/P/D). Full Signal aesthetic. **DEPLOYED ✅** (`/experiments/` live)
- `/api/experiments` endpoint: already live from BS-07 — no changes needed.
- Challenge ticker included on `/experiments/` page.

### BS-T2-5: Chronicle Newsletter Full Delivery (Assessment)
- `wednesday_chronicle_lambda.py` already includes `publish_to_journal()` — writes `site/journal/posts/week-{nn}/index.html` + `site/journal/posts.json` manifest. ✅
- `chronicle_email_sender_lambda.py` (BS-03) already delivers to confirmed subscribers. ✅
- **Remaining gaps (not blocking):** SEND_RATE_PER_SEC still at 1.0 (needs bump to 14.0 now SES production confirmed); unsubscribe link uses raw email instead of token. Flagged for next session.

### Bug flagged
- MCP `list_experiments` (and others): `NameError: name 'Key' is not defined`. Transient or import-level bug in MCP Lambda. Source not yet identified. Needs CloudWatch log investigation next session.

### Infrastructure
- `life-platform-site-api` (us-east-1): deployed 3x this session (path fix, code fix, final). Live with `/api/current_challenge` route.
- CloudFront invalidations: `/assets/css/base.css`, `/`, `/journal/`, `/character/`, `/platform/`, `/experiments/`.
- S3 synced: `site/` (all pages + CSS), `site/experiments/index.html`, `site/config/current_challenge.json`.

---

## v3.7.64 — 2026-03-17: Sprint 2 complete — BS-MP3, BS-TR1, BS-TR2, BS-BH1, BS-07, BS-08, BS-SL2

### Summary
Full Sprint 2 implemented and deployed in one session. 6 of 7 planned features shipped (BS-NU1 shelved per plan). Two new compute Lambdas added to CDK, MCP deployed with new `get_vice_streaks` tool, site-api Lambda created via LifePlatformWeb CDK deploy, SES confirmed out of sandbox.

### New Lambda Files
- `lambdas/sleep_reconciler_lambda.py`: BS-08 Unified Sleep Record — merges Whoop/Eight Sleep/Apple Health per conflict resolution rules. Runs 7:00 AM PT daily. Writes to `SOURCE#sleep_unified`.
- `lambdas/circadian_compliance_lambda.py`: BS-SL2 Circadian Compliance Score — 4-component pre-sleep behavioral score (0-100). Runs 7:00 PM PT daily. Writes to `SOURCE#circadian`.

### Modified Files
- `lambdas/daily_insight_compute_lambda.py`: BS-MP3 — `_compute_decision_fatigue_alert()` added. Fires when active+overdue Todoist tasks >15 AND T0 habit completion <60% this week. Priority 3 signal in AI context block. **DEPLOYED ✅**
- `lambdas/weekly_correlation_compute_lambda.py`: BS-TR1 + BS-TR2 — `_compute_centenarian_progress()` and `_compute_zone2_efficiency()` added. Both run Sunday after correlations. Write to `SOURCE#centenarian_progress` and `SOURCE#zone2_efficiency`. **DEPLOYED ✅**
- `lambdas/site_api_lambda.py`: BS-07 — 4 new routes: `/api/weight_progress`, `/api/character_stats`, `/api/habit_streaks`, `/api/experiments`. All 1h cache TTL.
- `mcp/tools_habits.py`: BS-BH1 — `tool_get_vice_streaks()` added. Compounding value formula (streak^1.5/10), streak risk rating, milestone coaching, portfolio total.
- `mcp/registry.py`: BS-BH1 — `get_vice_streaks` tool registered. Import updated to explicit names. **MCP DEPLOYED ✅**
- `ci/lambda_map.json`: BS-08 and BS-SL2 registered as `sleep_reconciler` and `circadian_compliance` sections.
- `cdk/stacks/compute_stack.py`: BS-08 + BS-SL2 Lambdas added (SleepReconciler + CircadianCompliance). **CDK DEPLOYED ✅** (LifePlatformCompute)
- `cdk/stacks/role_policies.py`: `compute_sleep_reconciler()` and `compute_circadian_compliance()` policies added.

### Infrastructure
- `LifePlatformCompute` deployed: sleep-reconciler + circadian-compliance Lambdas created with EventBridge schedules.
- `LifePlatformWeb` deployed: life-platform-site-api Lambda created (us-east-1). Function URL: `https://lxhjl2qvq2ystwp47464uhs2ti0hpdcq.lambda-url.us-east-1.on.aws/`
- SES: `ProductionAccessEnabled: true` confirmed.
- MCP tool count: 89 → 90 (`get_vice_streaks` added).
- CDK Lambda count: 46 → 48 (sleep-reconciler + circadian-compliance).

### Post-deploy fixes
- **site-api cross-region bug**: Lambda runs in us-east-1, DDB in us-west-2. Fixed by injecting `DYNAMODB_REGION=us-west-2` env var in CDK web_stack.py and reading `DDB_REGION` in Lambda instead of `AWS_REGION`. Committed separately.
- BS-08 backfill: 43/44 nights stored (2026-02-01 to 2026-03-16)
- BS-SL2 first run: 38/100 (poor) confirmed working
- `/api/status` + `/api/weight_progress` smoke tested OK

### Pending (next session)
- `HERO_WHY_PARAGRAPH` in `site_writer.py` (deferred from Sprint 1)
- TB7-25: CI/CD rollback scope verification
- TB7-27: MCP tool tiering design doc (pre-SIMP-1 Phase 2)

---

## v3.7.63 — 2026-03-17: BS-02 hero live, journal Signal alignment, SES sandbox exit

### Summary
Post-Sprint-1 cleanup session. BS-02 hero drop-in applied to `index.html` and deployed live. Journal page brought into Signal design system parity (ticker, live data, nav/CSS path fixes, animate-in). SES production access request submitted. `ci/lambda_map.json` confirmed already had `chronicle_email_sender` — no action needed.

### Modified Files
- `site/index.html`: BS-02 hero drop-in applied (transformation story format: 302→current→185 counter, progress bar, stat chips, Chronicle teaser). JS unified to single fetch `/site/public_stats.json`. OG description updated to 89 tools. **DEPLOYED ✅** (S3 + CloudFront invalidation E3S424OXQZ8NBE)
- `site/journal/index.html`: Full Signal design system alignment — serif fonts (Lora) removed entirely, replaced with Bebas Neue + Space Mono throughout. Ticker added with live data. CSS border overrides removed (was bleeding amber tint into all surfaces). Nav links fixed to absolute paths. `animate-in` classes added. Live data JS added.
- `lambdas/daily_brief_lambda.py` (via `site_writer.py`): Redeployed to pick up hero changes. **DEPLOYED ✅**

### Infrastructure
- SES production access request submitted via `aws sesv2 put-account-details`. Pending AWS review (~24h).
- CloudFront invalidation ICSV1P164RAIOE8A6WR5RNEBI in progress for `E3S424OXQZ8NBE` (averagejoematt.com).

### Pending (next session)
- BS-02 paragraph: write 50-word `HERO_WHY_PARAGRAPH` in `site_writer.py`, set `paragraph_is_placeholder: False`, redeploy daily-brief
- Verify SES production access granted: `aws sesv2 get-account`
- Deploy journal page to S3
- Sprint 2 prereqs: BS-08 sleep conflict rules doc, BS-05 confidence spec per-insight-type

---

## v3.7.62 — 2026-03-17: Sprint 1 complete — BS-01, BS-02, BS-03, BS-05, BS-09

### Summary
All 5 Sprint 1 features implemented and deployed. Board architecture decision (4-0): separate `chronicle-email-sender` Lambda over inline call. BS-01 and BS-09 were already code-complete from prior sessions; MCP registry entries confirmed present. BS-03 (new Lambda + CDK + IAM), BS-05 (confidence wiring into Chronicle), and BS-02 (hero section in `public_stats.json` + homepage HTML snippet) built and deployed this session.

### New Files
- `lambdas/chronicle_email_sender_lambda.py`: **NEW** — BS-03. Delivers Chronicle installment to confirmed email subscribers. Viktor guard: clean no-op if no installment found this week. Rate-limited (1/sec, bumped after SES production access). Personalized unsubscribe link per subscriber (CAN-SPAM). Signal-branded HTML email. `_confidence_badge_html` field read from DDB installment record (BS-05 integration).
- `deploy/hero_snippet_bs02.html`: **NEW** — BS-02 homepage hero drop-in. Reads from `public_stats.json` via fetch. Live weight counter (302 → current → 185), progress bar, days on journey, streak chip, Chronicle teaser. Skeleton loading state. Placeholder paragraph flag (`paragraph_is_placeholder: true`) until Matthew writes his 50-word paragraph.
- `deploy/patch_chronicle_bs05.py`: Patches wednesday_chronicle_lambda.py BS-05 (duplicate confidence block insertion — superseded by fix_chronicle_bs05.py).
- `deploy/fix_chronicle_bs05.py`: Cleaned up duplicate confidence block, updated store_installment kwargs call.
- `deploy/fix_store_installment_sig.py`: Updated `store_installment()` signature at line 1497 to accept `confidence_level` and `confidence_badge_html` kwargs.
- `deploy/patch_role_policies_bs03.py`: Inserted `email_chronicle_sender()` IAM policy function into role_policies.py.

### Modified Files
- `cdk/stacks/email_stack.py`: Added `ChronicleEmailSender` Lambda entry. `cron(10 15 ? * WED *)` — 8:10 AM PT Wednesday. `timeout=300s`, `SEND_RATE_PER_SEC=1.0`, `SITE_URL` env vars. **DEPLOYED ✅**
- `cdk/stacks/role_policies.py`: Added `email_chronicle_sender()` function (DDB GetItem/Query, KMS Decrypt, SES send, DLQ — no ai-keys, no S3 read). **DEPLOYED ✅**
- `lambdas/site_writer.py`: v1.1.0. Added `hero` section to `public_stats.json` (BS-02): narrative paragraph, live weight, progress pct, days on journey. Added `chronicle_latest` section (latest Chronicle headline for below-fold). Updated `write_public_stats()` signature with `table_client` and `user_id` params. **DEPLOYED ✅** (via daily-brief)
- `lambdas/wednesday_chronicle_lambda.py`: BS-05 confidence block in lambda_handler, `build_email_html()` injects confidence badge, `store_installment()` signature updated with confidence kwargs, `_confidence_level` + `_confidence_badge_html` fields written to DDB item. **DEPLOYED ✅**

### Architecture Decision
**BS-03 routing — Board vote 4-0 (Marcus/Jin/Elena/Priya):** Separate Lambda over inline call. Clean separation of concerns, independent DLQ/alarm/retry. Viktor guard: no-op if no Chronicle installment found this week — makes the 10-min EventBridge timing gap irrelevant to correctness.

### Deployments (all ✅)
- `LifePlatformEmail` CDK deploy: `chronicle-email-sender` Lambda created. IAM role: DynamoDB GetItem/Query, KMS Decrypt, SES send, DLQ. EventBridge `cron(10 15 ? * WED *)`.
- Post-CDK smoke: 10/10 passed.
- `wednesday-chronicle` Lambda (BS-05): confidence block wired.
- `daily-brief` Lambda (BS-02): site_writer hero section.
- `life-platform-mcp`: BS-01 `get_essential_seven` + BS-09 `get_acwr_status` both confirmed in registry.

### Remaining Manual Steps
- `ci/lambda_map.json`: Add `chronicle_email_sender` entry
- Homepage hero: drop `deploy/hero_snippet_bs02.html` into `index.html`
- BS-02 paragraph: edit `HERO_WHY_PARAGRAPH` in `site_writer.py` + set `paragraph_is_placeholder: False`
- SES sandbox exit: request production SES access (blocks real subscriber delivery)

### Sprint 1 Status: COMPLETE ✅
| ID | Feature | Status |
|----|---------|--------|
| BS-01 | Essential Seven Protocol | ✅ Deployed (was already code-complete) |
| BS-02 | Website Hero Redesign | ✅ site_writer updated; hero_snippet ready to drop in |
| BS-03 | Chronicle → Email Pipeline | ✅ chronicle-email-sender deployed |
| BS-05 | AI Confidence Scoring | ✅ wired into Chronicle (DDB + email) |
| BS-09 | ACWR Training Load Model | ✅ Deployed (was already code-complete) |

---

## v3.7.61 — 2026-03-16: Board Summit gap-fill + full sprint plan
