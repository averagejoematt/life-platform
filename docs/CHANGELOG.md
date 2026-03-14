# Life Platform — Changelog

## v3.7.21 — 2026-03-14: Google Calendar integration (R8-ST1)

### Summary
Google Calendar is now a live data source. 2 new MCP tools (`get_calendar_events`, `get_schedule_load`). Daily ingestion Lambda runs at 6:30 AM PT. OAuth2 with token refresh stored in Secrets Manager `life-platform/google-calendar`. Requires one-time auth setup via `setup/setup_google_calendar_auth.py`.

### Components
- **`lambdas/google_calendar_lambda.py`** — daily ingestion Lambda. OAuth2 refresh_token pattern (same as Strava/Whoop). Fetches 7-day lookback (gap fill) + 14-day lookahead. Stores per-day records + `DATE#lookahead` summary.
- **`mcp/tools_calendar.py`** — `tool_get_calendar_events` (view: day/range/lookahead) + `tool_get_schedule_load` (meeting load analysis, DOW patterns, week assessment)
- **`mcp/registry.py`** — 2 new tools registered (88 total)
- **`cdk/stacks/role_policies.py`** — `ingestion_google_calendar()` IAM (DDB, S3, secret read/write, DLQ)
- **`cdk/stacks/ingestion_stack.py`** — Lambda #16 wired, schedule `cron(30 13 * * ? *)` (6:30 AM PT)
- **`setup/setup_google_calendar_auth.py`** — one-time OAuth setup script

### Data model
- `SOURCE#google_calendar | DATE#<date>` — per-day: event list, event_count, meeting_minutes, focus_block_count, earliest/latest event
- `SOURCE#google_calendar | DATE#lookahead` — 14-day forward summary, updated daily

### Activation required
Google Calendar data will NOT flow until OAuth is authorized:
```bash
pip install google-auth-oauthlib google-api-python-client
python3 setup/setup_google_calendar_auth.py
```
Requires: Google Cloud project, Calendar API enabled, OAuth 2.0 Desktop credentials.

### Deployed
- CDK: `LifePlatformIngestion` (google-calendar-ingestion Lambda + IAM)
- `google-calendar-ingestion` Lambda code deployed
- `life-platform-mcp` Lambda (88 tools)
- Post-reconcile smoke: 10/10 ✅, CI: 7/7 ✅

---

## v3.7.20 — 2026-03-14: R8-ST5 + R8-LT3 + R8-LT9

### Summary
Three R8 findings closed: composite scores pre-compute (R8-ST5), unit test suite (R8-LT3, 74/74), and weekly correlation compute Lambda (R8-LT9). All remaining actionable R8 findings are now resolved. Only gated items remain (SIMP-1 Phase 2 ~Apr 13, R9 review, Google Calendar).

### R8-ST5 — Composite Scores Pre-compute
- Added `write_composite_scores()` to `daily_metrics_compute_lambda.py` — called at end of every daily compute run
- Writes `SOURCE#composite_scores | DATE#<date>` with: day_grade_score, day_grade_letter, readiness_score, readiness_colour, tier0_streak, tier01_streak, tsb, hrv_7d, hrv_30d, latest_weight, component_scores, computed_at, algo_version
- Non-fatal: write failures logged but don’t block Daily Brief
- Schema documented in `docs/SCHEMA.md`

### R8-LT3 — Unit Tests for Business Logic
- Created `tests/test_business_logic.py` — 74 tests, all passing (0.17s)
- Covers: `scoring_engine` (helpers, letter_grade, score_sleep, score_recovery, score_nutrition, compute_day_grade), `character_engine` (helpers, _clamp, _pct_of_target, _deviation_score, _in_range_score, _trend_score, get_tier), `daily_metrics_compute_lambda` (compute_tsb, compute_readiness)
- Fully offline — no AWS credentials needed

### R8-LT9 — Weekly Correlation Compute
- New Lambda `lambdas/weekly_correlation_compute_lambda.py`
- Runs Sunday 11:30 AM PT (`cron(30 18 ? * SUN *)`) — 30 min before hypothesis engine
- Computes 20 Pearson correlation pairs over 90-day rolling window
- Writes to `SOURCE#weekly_correlations | WEEK#<iso_week>`
- Idempotent: skips if already computed (pass `force=true` to override)
- CDK wired: `LifePlatformCompute` stack, `compute_weekly_correlations()` IAM policy
- Schema documented in `docs/SCHEMA.md`

### Deployed
- CDK: `LifePlatformCompute` (new weekly-correlation-compute Lambda + IAM)
- `daily-metrics-compute` Lambda (composite scores writer)
- `weekly-correlation-compute` Lambda (new)
- Post-reconcile smoke: 10/10 ✅
- CI: 7/7 ✅, business logic: 74/74 ✅

---

## v3.7.19 — 2026-03-14: SIMP-1 Phase 1c+1d — Labs/Training/Strength/Character/CGM/Mood/Metrics/Todoist/SickDays

### Summary
SIMP-1 Phase 1c+1d consolidated 24 tools into 9 dispatchers. Tool count 101 → 86 (−15 net: 24 removed, 9 added). Warmer extended with 5 new warm steps (training_load fix + periodization + recommendation + character_sheet + cgm_dashboard). Board vote 11-0 applied: all expensive on-demand tools in Phase 1c clusters (training, cgm) now warmed nightly. Registry R5 test range updated to 75-105.

### Changes
- **mcp/tools_labs.py**: Added `tool_get_labs(view: results|trends|out_of_range)`
- **mcp/tools_training.py**: Added `tool_get_training(view: load|periodization|recommendation)`
- **mcp/tools_strength.py**: Added `tool_get_strength(view: progress|prs|standards)`
- **mcp/tools_character.py**: Added `tool_get_character(view: sheet|pillar|history)`
- **mcp/tools_cgm.py**: Added `tool_get_cgm(view: dashboard|fasting)`
- **mcp/tools_journal.py**: Added `tool_get_mood(view: trend|state_of_mind)` with lazy import of tool_get_state_of_mind_trend from tools_lifestyle
- **mcp/tools_health.py**: Added `tool_get_daily_metrics(view: movement|energy|hydration)` with lazy import of tool_get_movement_score from tools_lifestyle
- **mcp/tools_todoist.py**: Added `tool_get_todoist_snapshot(view: load|today)` with args-dict adapter for positional-arg underlying functions
- **mcp/tools_sick_days.py**: Added `tool_manage_sick_days(action: list|log|clear)`
- **mcp/warmer.py**: Added steps 9-13 — training_load (fix: imported but never cached), training_periodization, training_recommendation, character_sheet, cgm_dashboard
- **mcp/registry.py**: Removed 24 tools, added 9 dispatchers, net 101→86
- **tests/test_mcp_registry.py**: Updated R5 range 100-130 → 75-105

### Tool count history
| Version | Tools | Delta | Phase |
|---------|-------|-------|-------|
| v3.7.14 | 116 | baseline | pre-SIMP-1 |
| v3.7.17 | 109 | −7 | Phase 1a: Habits |
| v3.7.18 | 101 | −8 | Phase 1b: Data/Health/Nutrition |
| v3.7.19 | 86 | −15 | Phase 1c+1d: Labs/Training/Strength/Character/CGM/Mood/Metrics/Todoist/SickDays |
| Target | ≤80 | −6 more | Phase 2: EMF-driven (~2026-04-13) |

### Deployed
- `life-platform-mcp` Lambda
- Post-reconcile smoke: 10/10 ✅
- CI: 7/7 ✅

---

## v3.7.18 — 2026-03-14: SIMP-1 Phase 1b — Data, Health, Nutrition clusters

### Summary
SIMP-1 Phase 1b consolidated 11 tools into 4 dispatchers: `get_daily_snapshot`, `get_longitudinal_summary`, `get_health`, `get_nutrition`. Tool count 109 → 101 (−8 net: 11 removed, 4 added). Board vote 11-0: also added `get_health_risk_profile` and `get_health_trajectory` to nightly warmer in the same commit — these were the only two expensive on-demand tools not previously cached; now warm nightly alongside health_dashboard.

### Changes
- **mcp/tools_data.py**: Added `tool_get_daily_snapshot` (view: summary|latest) and `tool_get_longitudinal_summary` (view: aggregate|seasonal|records) dispatchers at end of file.
- **mcp/tools_health.py**: Added `tool_get_health` (view: dashboard|risk_profile|trajectory) dispatcher at end of file.
- **mcp/tools_nutrition.py**: Added `tool_get_nutrition` (view: summary|macros|meal_timing|micronutrients) dispatcher at end of file.
- **mcp/warmer.py**: Added steps 7 + 8 — nightly warm of `health_risk_profile` and `health_trajectory`. Import line updated. These were previously compute-on-demand only.
- **mcp/registry.py**: Removed 11 tools: get_latest, get_daily_summary, get_aggregated_summary, get_personal_records, get_seasonal_patterns, get_health_dashboard, get_health_risk_profile, get_health_trajectory, get_micronutrient_report, get_meal_timing, get_nutrition_summary, get_macro_targets. Added 4 dispatchers: get_daily_snapshot, get_longitudinal_summary, get_health, get_nutrition. Net: 109 → 101.

### Tool count history
| Version | Tools | Delta | Phase |
|---------|-------|-------|-------|
| v3.7.14 | 116 | baseline | pre-SIMP-1 |
| v3.7.17 | 109 | −7 | Phase 1a: Habits |
| v3.7.18 | 101 | −8 | Phase 1b: Data/Health/Nutrition |
| Target | ≤80 | −21 more | Phases 1c-2 |

### Deployed
- `life-platform-mcp` Lambda (registry + dispatcher functions + warmer)
- Post-reconcile smoke: 10/10 ✅
- CI: 7/7 (registry test) ✅

### Files Changed
- `mcp/tools_data.py`
- `mcp/tools_health.py`
- `mcp/tools_nutrition.py`
- `mcp/warmer.py`
- `mcp/registry.py`
- `docs/CHANGELOG.md`

---

## v3.7.17 — 2026-03-14: R8 gap closure sprint — 8 findings resolved

### Summary
Closed all remaining actionable R8 findings from the Architecture Review #8 PDF. SIMP-1 Phase 1a (habits cluster) reduced MCP tools 116→109. Resolved 8 open items: compute pipeline staleness observability (Risk-7), HAE S3 scope tightening (R8-ST7), CDK IAM blocking gate (R8-ST6), maintenance mode script (R8-ST3), OAuth token health monitoring (R8-ST4), DynamoDB PITR restore runbook (R8-ST2), hypothesis disclaimer (R8-LT7), and COST_TRACKER model routing entry (R8-QS3). PROJECT_PLAN TB7-1 and TB7-2 statuses corrected to Done (were previously completed but not marked).

### Changes
- **mcp/tools_habits.py**: Added `tool_get_habits(view=...)` dispatcher — routes to dashboard/adherence/streaks/tiers/stacks/keystones.
- **mcp/registry.py**: Removed 7 habit tools (get_habit_adherence, get_habit_streaks, get_keystone_habits, get_group_trends, get_habit_stacks, get_habit_dashboard, get_habit_tier_report). Added `get_habits`. Retained `compare_habit_periods` standalone. Net: 116→109 tools. Added unconfirmed-hypothesis disclaimer to `get_hypotheses` description.
- **lambdas/daily_brief_lambda.py**: Risk-7 — emits `LifePlatform/ComputePipelineStaleness` CloudWatch metric when computed_metrics is missing or >4h stale.
- **lambdas/freshness_checker_lambda.py**: R8-ST4 — OAuth token health check on all 4 OAuth secrets via DescribeSecret. Alerts via SNS if any token not updated >60 days. Emits `OAuthTokenStaleCount` metric.
- **cdk/stacks/role_policies.py**: `email_daily_brief()` — added CloudWatchMetrics statement (PutMetricData). `operational_freshness_checker()` — added OAuthSecretDescribe statement for 4 OAuth secrets. `ingestion_hae()` — S3Write tightened from `raw/matthew/*` to 5 explicit paths.
- **.github/workflows/ci-cd.yml**: R8-ST6 — CDK diff IAM detection upgraded from `::warning` to `::error` + `exit 1` (blocking gate).
- **deploy/maintenance_mode.sh** (new): R8-ST3 — enable/disable/status for 7 non-essential EventBridge rules. Core ingestion + compute always kept running.
- **deploy/create_compute_staleness_alarm.sh** (new): Risk-7 — creates `life-platform-compute-pipeline-stale` CloudWatch alarm.
- **docs/RUNBOOK.md**: R8-ST2 — added DynamoDB PITR Restore section with drill procedure, integrity checks, and emergency restore steps.
- **docs/COST_TRACKER.md**: R8-QS3 — marked Haiku model routing entry as stale (actual: Sonnet).
- **docs/PROJECT_PLAN.md**: Marked R8-QS2/QS3/QS4, TB7-1/TB7-2, R8-ST2/ST3/ST4/ST6/ST7, R8-LT7 as Done. Added Risk-7 as tracked item.

### Deployed
- `daily-brief` Lambda (compute staleness metric)
- `life-platform-mcp` Lambda (registry: 116→109 tools, hypothesis disclaimer)
- `life-platform-freshness-checker` Lambda (OAuth token health check)
- `LifePlatformIngestion` CDK (HAE S3 scope tightened)
- `LifePlatformEmail` CDK (daily_brief CloudWatch IAM)
- `LifePlatformOperational` CDK (freshness_checker OAuthSecretDescribe IAM)
- CloudWatch alarm: `life-platform-compute-pipeline-stale` ✅
- Post-reconcile smoke: 10/10 ✅
- CI: 20/20 ✅

### Files Changed
- `mcp/tools_habits.py`
- `mcp/registry.py`
- `lambdas/daily_brief_lambda.py`
- `lambdas/freshness_checker_lambda.py`
- `cdk/stacks/role_policies.py`
- `.github/workflows/ci-cd.yml`
- `deploy/maintenance_mode.sh` (new)
- `deploy/create_compute_staleness_alarm.sh` (new)
- `docs/RUNBOOK.md`
- `docs/COST_TRACKER.md`
- `docs/PROJECT_PLAN.md`
- `docs/CHANGELOG.md`

---

## v3.7.16 — 2026-03-14: R8-QS2 integration test + CDK handler bug fixes

### Summary
Added MCP integration test to qa-smoke Lambda (R8-QS2). Fixed pre-existing IAM bug where qa-smoke had zero Secrets Manager/Lambda permissions, silently breaking `check_lambda_secrets()` on every run. Caught and fixed 2 additional pre-existing CDK bugs: `weekly-digest` had wrong handler (`digest_handler` instead of `weekly_digest_lambda`), and `lambda_helpers.py` docstring contained the `lambda_function.lambda_handler` placeholder that H5 linter now catches. Deployed LifePlatformOperational + LifePlatformEmail. R8-QS4 (archive scripts) confirmed already done.

### Changes
- **lambdas/qa_smoke_lambda.py**: Added `check_mcp_tool_calls()` — 3 sub-checks: (a) `get_sources` ≥10 sources, (b) `get_task_load_summary` shape validation, (c) DDB cache warm ≥10 `TOOL#` entries. Wired into handler. Added `urllib.request`, `Key` imports. Added `MCP_FUNCTION_URL` / `MCP_SECRET_NAME` env var config.
- **cdk/stacks/role_policies.py**: `operational_qa_smoke()` expanded from 4 → 8 policy statements. Added: `S3ListBlog` (blog/* list), `SecretsGetMCP` (mcp-api-key GetSecretValue), `SecretsInventory` (ListSecrets *), `LambdaList` (ListFunctions *). Fixed `S3Read` to include `blog/*`.
- **cdk/stacks/operational_stack.py**: Added `MCP_FUNCTION_URL` and `MCP_SECRET_NAME` env vars to QaSmoke Lambda.
- **cdk/stacks/email_stack.py**: Fixed `weekly-digest` handler `digest_handler.lambda_handler` → `weekly_digest_lambda.lambda_handler`. Removed stale "Special handler" comment.
- **cdk/stacks/lambda_helpers.py**: Fixed docstring example using `lambda_function.lambda_handler` placeholder → `whoop_lambda.lambda_handler`.

### Bugs Found and Fixed
- **qa-smoke IAM gap** (silent pre-existing): `check_lambda_secrets()` called `secretsmanager:ListSecrets` + `lambda:ListFunctions` but role had neither permission → AccessDenied on every run, silently reported as a failure in QA email.
- **weekly-digest wrong handler** (latent CDK bug): Handler was `digest_handler.lambda_handler` — no such module exists. CDK deploy would overwrite live handler to a broken value on next reconcile. Fixed to `weekly_digest_lambda.lambda_handler`.
- **lambda_helpers docstring** (linter false-positive risk): Docstring example used `lambda_function.lambda_handler` which H5 linter correctly flags as the P0 bug pattern.

### CI Results
- 20/20 tests passing (test_cdk_handler_consistency H1–H5, test_cdk_s3_paths S1–S4, test_iam_secrets_consistency S1–S4, test_mcp_registry R1–R7)

### Deployed
- `life-platform-qa-smoke` Lambda (code)
- `LifePlatformOperational` CDK stack (IAM + env vars)
- `LifePlatformEmail` CDK stack (weekly-digest handler fix)
- Post-reconcile smoke: 10/10 ✅

### Files Changed
- `lambdas/qa_smoke_lambda.py`
- `cdk/stacks/role_policies.py`
- `cdk/stacks/operational_stack.py`
- `cdk/stacks/email_stack.py`
- `cdk/stacks/lambda_helpers.py`
- `docs/CHANGELOG.md`
- `handovers/HANDOVER_v3.7.16.md` (new)

### Next Steps
1. SIMP-1 Phase 1a: Habits cluster merge (6 tools → 1, −5 net)
2. Google Calendar integration (~6-8h)
3. R8-ST2: DynamoDB restore procedure runbook + test

---

## v3.7.15 — 2026-03-13: Architecture Review #8 execution

### Summary
Full Architecture Review #8 conducted. Grade: A-. Executed immediate fixes: stale CV_THRESHOLDS comments in anomaly detector, new IAM/secrets consistency CI lint (`test_iam_secrets_consistency.py`), SCHEMA.md added to `sync_doc_metadata.py`, P0 verification script for webhook auth + secret reconciliation. Review document produced at `docs/reviews/architecture_review_8_full.md`.

### Key Review Findings (see full report)
- **FINDING-1 (HIGH):** COST-B created `ingestion-keys` references in 4 IAM policies that don’t match documented 9-secret list. Needs runtime verification.
- **FINDING-2 (HIGH):** Webhook Lambda IAM has no Secrets Manager access but code calls `get_secret_value()`. Auth may be broken. Needs runtime verification.
- **FINDING-3 (HIGH):** Complexity approaching single-operator sustainability limits. SIMP-1 is the strategic priority.
- **FINDING-4 (MEDIUM):** No integration/E2E test in CI.
- 12 total findings documented. 4 SLOs validated. 23 ADRs reviewed.

### Changes
- **lambdas/anomaly_detector_lambda.py**: Fixed stale CV_THRESHOLDS inline comments (said Z=2.0/1.75/1.5 but actual values are Z=2.5/2.0/2.0)
- **tests/test_iam_secrets_consistency.py** (new): R8-8 CI lint — cross-references IAM secret ARN patterns against known-secrets list. Rules S1–S4.
- **.github/workflows/ci-cd.yml**: Added `test_iam_secrets_consistency.py` to Job 2 (Unit Tests)
- **deploy/sync_doc_metadata.py**: Added SCHEMA.md to sync rules; bumped PLATFORM_FACTS to v3.7.15
- **deploy/r8_p0_verify.sh** (new): P0 verification script — checks secrets inventory, Lambda env vars, webhook auth, MCP concurrency, runs IAM lint

### Files Changed
- `lambdas/anomaly_detector_lambda.py`
- `tests/test_iam_secrets_consistency.py` (new)
- `.github/workflows/ci-cd.yml`
- `deploy/sync_doc_metadata.py`
- `deploy/r8_p0_verify.sh` (new)
- `docs/CHANGELOG.md`

### Post-P0 Fixes (same session, after verification)
- **docs/ARCHITECTURE.md**: Secrets table rewritten to match actual 10-secret state (was 9 with 2 nonexistent). Fixed webhook auth reference (`api-keys` → `ingestion-keys`). Fixed OAuth management section (dedicated → bundled reality). Updated AWS resources summary.
- **docs/PROJECT_PLAN.md**: Rebuilt from scratch with all R8 action items extracted, prioritized into 4 tiers (Tier 1 30d / Tier 2 60d / Tier 3 90d / Tier 4 deferred), with effort estimates and dependencies. 25 items total.
- **docs/SIMP1_PLAN.md** (new): Full SIMP-1 consolidation plan. Analyzed 116 tools by domain (20 domains). Identified 14 merge groups in Phase 1 (−28 tools, 116→88). Phase 2 EMF-driven cuts (−5-10, →78-83). Phase 3 pre-compute unlocks. Execution: ~5 sessions.

### Next Steps
1. R8-QS2: Integration test for qa-smoke (Tier 1, high ROI)
2. SIMP-1 Phase 1: read-only merges can begin immediately
3. Google Calendar integration (~6-8h)

---

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
