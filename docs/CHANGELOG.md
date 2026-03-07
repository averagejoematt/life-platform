# Life Platform — Changelog

## v2.85.0 — 2026-03-07: Prompt Intelligence Fixes (P1–P5) + IC-1 Platform Memory

### Prompt Intelligence
- **P1 — Weekly Plate memory** (`weekly_plate_lambda.py`): loads last 4 plate summaries from DDB `platform_memory` partition before AI call; stores new plate summary after generation. Anti-repeat rules injected into prompt: Wildcard must change each week, recipes can't repeat, Greatest Hits gets fresh angles. Fixes "cottage cheese" problem where AI rediscovers same foods weekly.
- **P2 — Journey context block** (`ai_calls.py`): new `_build_journey_context()` injects week number, days-in, stage label (Foundation/Momentum/Building/Advanced), and stage-appropriate coaching principles into all 4 AI calls. Prevents AI from coaching Week 2 like an intermediate athlete.
- **P3 — Walk coaching rewrite** (`ai_calls.py`): training coach prompt overhauled to treat walks as PRIMARY training sessions at Foundation stage. At 300+ lbs, a 45-min walk carries real cardiovascular load. Old "brief NEAT acknowledgment" language removed. Walk coaching now covers pace, duration, HR, and bodyweight-adjusted progress.
- **P4 — Habit→outcome connector** (`ai_calls.py`): new `_build_habit_outcome_context()` passes 7-day T0/T1 completion trend to BoD + TL;DR calls, with known causal mappings (wind-down → sleep_score, protein-first → protein_g, etc.). Explicit prompt instruction to trace causal chain when habits were missed.
- **P5 — TDEE/deficit context** (`ai_calls.py`): new `_build_tdee_context()` surfaces estimated TDEE (from MacroFactor or derived as calorie_target + phase deficit). Nutrition prompt now includes TDEE, planned deficit, actual intake, actual deficit %, and flag if intake is >25% below target (possible logging gap).

### IC-1: Platform Memory DDB Partition
- **New module:** `mcp/tools_memory.py` (28th module, 4 new tools: 136–139)
- **DDB pattern:** `pk=USER#matthew#SOURCE#platform_memory`, `sk=MEMORY#<category>#<date>`
- **Tools:** `write_platform_memory`, `read_platform_memory`, `list_memory_categories`, `delete_platform_memory`
- **Categories seeded:** `weekly_plate` (live via P1), `failure_pattern`, `what_worked`, `coaching_calibration`, `personal_curves`, `journey_milestone`, `insight`, `experiment_result`
- This is the compounding substrate enabling IC-2 through IC-14. No new Lambda — reads/writes via existing MCP Lambda.

### deploy_lambda.sh Multi-Module Fix
- Added `--extra-files file1.py file2.py ...` flag to `deploy/deploy_lambda.sh`
- Validates all extra files exist before deploying
- Main handler verification updated to check presence (not uniqueness) — works with multi-file zips
- Fixes latent redeploy risk for `daily-brief` (which imports `html_builder`, `ai_calls`, `output_writers`, `board_loader`)

### Counts
- **MCP tools:** 139 (+4) | **Modules:** 28 (+1: tools_memory.py)
- **Lambdas:** 32 (unchanged)

## v2.84.4 — 2026-03-07: Prompt Intelligence Audit + Tier 7 Roadmap

- **Full prompt audit:** Evaluated every AI-facing prompt across all 5 Lambdas (ai_calls.py, weekly_plate, nutrition_review, weekly_digest, wednesday_chronicle)
- **5 prompt intelligence fixes identified and added to PROJECT_PLAN.md (P1–P5):**
  - P1: Weekly Plate memory (no stored history — cottage cheese bug)
  - P2: Journey context block (no week number / fitness baseline / stage-aware coaching)
  - P3: Training coach walk/early fitness rewrite (walks wrongly dismissed as "NEAT" at Week 2)
  - P4: Habit → outcome connector (causal chain not traced; pre-compute not feeding AI)
  - P5: TDEE / deficit context in nutrition prompts
- **Tier 7 Intelligence Compounding added to PROJECT_PLAN.md (IC-1 through IC-14):** Architecture foundation (platform_memory DDB partition, pre-compute insight Lambda, chain-of-thought two-pass); near-term (failure pattern recognition, momentum detection, milestone architecture, cross-pillar trade-off reasoning, intent vs execution gap); medium-term (episodic memory, personalized response curves, coaching calibration); longer-term (coaching effectiveness feedback loop, vector store, personal knowledge graph)
- **Architecture Decision Record documented:** Vector store / RAG deferred (corpus too small, cost too high); local LLM not appropriate for reasoning tasks; fine-tuning wrong solution for a reasoning gap; `platform_memory` DDB + pre-compute Lambda are the right infrastructure additions
- No code deployed — planning and documentation session

## v2.84.3 — 2026-03-07: Data-Aware Idempotency for Daily Metrics Compute

- **Problem fixed:** `daily-metrics-compute` used time-based idempotency ("skip if computed today") — late-arriving data (e.g. HAE syncing after 9:40 AM) produced stale scores with missing hydration/glucose components
- **Solution:** Compute is now data-aware. On each run it compares `source_fingerprints` (per-source `webhook_ingested_at` timestamps stored in the computed_metrics record) against current DDB values. If any source has updated since the last compute, it reruns automatically.
- **New functions:** `get_source_fingerprints()`, `fingerprints_changed()` in `daily_metrics_compute_lambda.py`
- **`store_computed_metrics()`:** now persists `source_fingerprints` map alongside scores
- **EventBridge:** New `daily-metrics-compute-catchup` rule (`rate(30 minutes)`) — fires every 30 min all day; costs pennies and is a no-op after inputs stabilise
- **Net effect:** Any late-arriving source data (HAE, Notion, MacroFactor) self-heals within 30 minutes; `force=true` still available for manual overrides

## v2.84.2 — 2026-03-07: Secret Sweep + QA Infrastructure Health Check

- **Root cause found:** `health-auto-export-webhook` and `notion-journal-ingestion` had stale `SECRET_NAME` env vars pointing to deleted per-service secrets (`life-platform/health-auto-export`, `life-platform/notion`) — both broken since v2.75.0 secret consolidation
- **Impact:** Every HAE sync since v2.75.0 silently rejected at auth layer — no Apple Health data written for affected dates; Notion journal similarly affected
- **Fixed:** Both Lambdas updated to `SECRET_NAME=life-platform/api-keys` via `aws lambda update-function-configuration`
- **`tests/validate_lambda_secrets.py`:** New sweep script — checks all Lambda `SECRET_NAME` env vars against live Secrets Manager inventory; `--fix` flag auto-corrects stale refs to `life-platform/api-keys`. Run after any secret rename/delete.
- **`lambdas/qa_smoke_lambda.py`:** New `check_lambda_secrets()` check (CHECK 5) — sweeps all Lambda functions and flags any `SECRET_NAME` pointing to a missing/deleted secret. Fires daily at 10:30 AM PT. IAM inline policy `qa-smoke-infra-read` added to `lambda-weekly-digest-role` (`lambda:ListFunctions`, `secretsmanager:ListSecrets`).
- **QA green suppression:** Email now suppressed entirely when all checks pass (warnings also trigger email); warnings-only subject fixed from ✅ to ⚠️

## v2.84.1 — 2026-03-07: Daily Brief Hotfix + QA Green Suppression

- **Hotfix:** `daily-brief` zip was missing `html_builder.py`, `ai_calls.py`, `output_writers.py`, `board_loader.py` after todoist deploy — redeployed with all local module dependencies bundled
- **QA smoke:** Email suppressed when all checks green (no-op run); warnings-only state now shows ⚠️ subject instead of ✅

## v2.84.0 — 2026-03-07: Todoist Life OS — Bulk Rescheduling + Write Tools

- **`patches/todoist_reschedule.py`:** one-shot bulk rescheduler — fetches all ~292 tasks live from Todoist API, applies `every!` completion-based recurrence (except hard-date anchored tasks: birthdays, anniversaries, holidays), and intelligently scatters first-fire dates across 12 months
- **Smart scatter logic:** Finance → Health → Growth → Home sequencing across all cadences; weekly tasks spread across 4 onboarding weeks (not all at once); monthly tasks stagger across Mar/Apr/May by domain; quarterly spread across Apr/May/Jun; semi-annual in two waves (Apr/May/Jun + Oct/Nov/Dec); annual tasks keyword-matched to logical calendar month + deferred high-effort tasks (DEXA, cognitive baseline, hearing test) pushed to H2 2026
- **Day-of-week by domain:** Sunday=review/reflection, Monday=Finance, Wednesday=Health, Thursday=Growth, Saturday=Home
- **Dry-run mode:** prints full plan table + monthly distribution bar chart before any writes; `--apply` flag to commit
- **6 Todoist write tools** added to `mcp/tools_todoist.py` (tools 130-135): `get_todoist_projects`, `list_todoist_tasks`, `update_todoist_task` (supports `every!` syntax), `create_todoist_task`, `close_todoist_task`, `delete_todoist_task`
- **`mcp/registry.py`:** 6 additional write tool registrations (total tools: 135)
- **Bug fixed:** `todoist-data-ingestion` Lambda had stale `SECRET_NAME=life-platform/todoist` env var (old per-service secret deleted during v2.75.0 consolidation) — updated to `life-platform/api-keys` via `aws lambda update-function-configuration`

## v2.83.0 — 2026-03-07: Todoist Integration — MCP Tools + Daily Brief Task Load
- **Enhanced `todoist_lambda.py`:** now captures `overdue_count`, `due_today_count`, `priority_breakdown` (P1-P4), `tasks_due_today[]` via Todoist filter API. New `get_filtered_tasks()` helper with pagination + graceful fallback.
- **New `mcp/tools_todoist.py`:** 5 MCP tools — `get_task_completion_trend`, `get_task_load_summary`, `get_project_activity`, `get_decision_fatigue_signal`, `get_todoist_day`
- **`mcp/registry.py`:** import + 5 tool registrations added (tools 125-129)
- **`html_builder.py`:** new TASK LOAD section (after blood pressure tile) — shows completed/overdue/due-today/active with cognitive load signal (CLEAR/MODERATE/ELEVATED/HIGH) + top 3 projects by completion
- **`daily_brief_lambda.py`:** `gather_daily_data()` fetches `todoist_yesterday` and passes to html_builder via `data["todoist"]`
- **Roadmap item #34 (decision fatigue):** now live via `get_decision_fatigue_signal` — correlates task load with T0 habit compliance, Pearson r, load threshold analysis
- **Deploy:** `deploy/deploy_todoist_integration.sh` (3 Lambdas: todoist-data-ingestion → life-platform-mcp → daily-brief)

## v2.82.0 — 2026-03-07: Daily Metrics Compute Lambda (#53)
- **32nd Lambda:** `daily-metrics-compute` — pre-computes all derived metrics at 9:40 AM PT (between character-sheet-compute at 9:35 and daily-brief at 10:00)
- **New DDB partition:** `SOURCE#computed_metrics` stores: day_grade score/letter/component scores+details, readiness score/colour, habit streaks (tier0/tier01/vice), TSB, HRV 7d/30d avgs, sleep debt, weight (latest/week-ago/avatar)
- **Existing partitions preserved:** `SOURCE#day_grade` and `SOURCE#habit_scores` still written by compute Lambda for MCP tool + backfill compatibility
- **Daily Brief refactored:** reads `computed_metrics` record instead of computing inline. Falls back to full inline computation + stores if record missing (safe degradation)
- **Brief log signals:** `[INFO] Using pre-computed metrics` vs `[WARN] ... computing inline (fallback)`
- **Idempotent:** compute Lambda skips re-compute if record already exists (override with `force:true`)
- **Backfill-friendly:** event payload supports `{"date": "YYYY-MM-DD", "force": true}` for any historical date
- **Zip:** `lambda_function.py` + `scoring_engine.py` (512 MB, 120s timeout)
- **Deploy:** `deploy/deploy_daily_metrics_compute.sh`
- **CloudWatch alarms:** `daily-metrics-compute-errors` (≥1 error/day) + `daily-metrics-compute-duration-high` (p99 > 90s of 120s timeout)

## v2.81.0 — 2026-03-07: QA Smoke Test + Blog Cleanup
- **31st Lambda:** `life-platform-qa-smoke` — daily 10:30 AM PT health check email (5 categories, 20+ assertions)
- **3 new test/patch scripts:** `tests/smoke_test.py`, `tests/validate_links.py`, `lambdas/qa_smoke_lambda.py`
- **Deploy fix:** corrected role name `lambda-weekly-digest-role` in deploy script
- **Dashboard freshness threshold:** 2h → 4h (correct for pre-DST 5 PM PT evening refresh)
- **Blog:** deleted ghost DDB record ("The Week Everything Leveled Up"), rebuilt index from scratch, restored week-02.html with correct Empty Journal content
- **Roadmap:** added #53 Daily Brief compute refactor (Tier 3)

## v2.80.2 — 2026-03-06: Show & Tell PDF + Pipeline
- Built complete Show & Tell PDF (v5) for internal presentation — boss/peers/delegates audience
- Privacy redactions: habit substance rows (shot02/05), weight numbers (shot06/16/18), Brittany vulnerable content (shot07)
- Content reframe: removed personal weight loss narrative → data aggregation framing throughout
- New PDF section 12: Documentation System (changelog, handovers, incident log, RCA)
- New PDF section: Source-of-truth callout in Data Model
- Board of Directors concept box rebuilt as Paragraph layout (text wraps correctly)
- Tier progression diagram: consistent pixel art avatars across all 5 tiers
- Built `show_and_tell/` pipeline: setup.sh, run.sh, manifest.json, update_manifest.py, capture_screenshots.py, redact_screenshots.py, build_pdf.py
- Pipeline reduces future Show & Tell prep from ~1 day → ~20 min
- update_manifest.py auto-reads version/incidents/handovers/tools from live docs
- redact_screenshots.py codifies all redaction rules with documented reasons and resolution-independent coordinates

## v2.80.1 — 2026-03-06: Git/GitHub setup
- Added `.gitignore` rules for `datadrops/`, Lambda backups, dashboard data JSON, `.tar.gz` files
- Set up SSH key auth (`~/.ssh/id_ed25519`) for GitHub — no more token-in-URL
- Committed and pushed full platform catch-up to `git@github.com:averagejoematt/life-platform.git` (555 objects)
- Added Session Close Checklist to `docs/RUNBOOK.md`
- Updated session close ritual to include `git add -A && git commit && git push`


> Recent versions only. For older entries, see CHANGELOG_ARCHIVE.md.

---

## v2.80.0 — 2026-03-06 — Brittany Email Fixes & Design Refinements

- **Parser fix:** Sonnet wraps headers in `## 🪞` markdown — strip `#` and `*` before emoji check
- **Prompt fix:** Explicit no-markdown instruction added
- **Debug log:** Raw Sonnet response (first 300 chars) logged to CloudWatch
- **Design:** Weight card removed; "From his Board of Directors" section label removed; email subject simplified
- **Journey context:** Week number computed dynamically from Feb 22 baseline; AI given accurate timeline (week N of ~10 months) with instruction not to frame as percentage or imply mid-journey

---

## v2.79.0 — 2026-03-06 — Brittany Weekly Email

### New Lambda: `brittany-weekly-email` (30th Lambda)
- Weekly partner-focused email sent to Brittany every Sunday 9:30 AM PT
- **Full Board of Directors consultation** with elevated weighting on psychological and relationship experts
- **Rodriguez** (Behavioral Performance): How He's Feeling — emotional/behavioral state in plain language
- **Dr. Conti** (Psychiatry): What's Happening Underneath — psychological patterns, what Matthew won't say
- **Dr. Murthy** (Social Connection): How to Show Up for Him — specific, actionable partner guidance
- **The Chair**: His Body This Week — physical health board synthesis for Brittany
- **Elena Voss**: This Week in One Line — journalist's narrative lede
- Data sections: mood/energy/sleep/recovery/weight progress/training/habits/Character Sheet
- Model: Sonnet 4.6 · Schedule: Sunday 17:30 UTC (9:30 AM PT) · Recipient: `BRITTANY_EMAIL` env var
- Warm, partner-focused HTML design (distinct from clinical weekly digest)

### Stats
- Lambdas: 29 → 30
- Files: `lambdas/brittany_email_lambda.py`, `deploy/deploy_v2.79.0.sh`

---

## v2.78.0 — 2026-03-06 — Fitness Intelligence: Lactate Threshold, Exercise Efficiency, Hydration + Monthly Digest Character Sheet

### New MCP Tools (3)
- **`get_lactate_threshold_estimate`** (#27): Zone 2 cardiac efficiency analysis. Tracks pace-per-HR across steady-state sessions, linear regression reveals aerobic base direction. Chen: closest proxy to lab lactate curve.
- **`get_exercise_efficiency_trend`** (#39): Pace-at-HR by sport type. Same workout + lower HR = improving fitness. Attia: purest fitness signal from consumer data.
- **`get_hydration_score`** (#30): Bodyweight-adjusted hydration adequacy (35ml/kg). Daily target, deficit days, streak, exercise correlation. Source: Apple Health `water_intake_ml`.

### Monthly Digest Enhancements
- **Character Sheet section** added to monthly digest email: Level, XP delta (30d), total XP, all 7 pillars with prior-month deltas
- **Model fix**: `monthly_digest_lambda.py` was still on `claude-haiku-4-5-20251001` — corrected to `claude-sonnet-4-6` (missed in v2.77.2 sweep)

### Stats
- MCP: 121 → 124 tools
- Files: `mcp/tools_training.py`, `mcp/tools_health.py`, `mcp/registry.py`, `lambdas/monthly_digest_lambda.py`

---

## v2.77.2 — 2026-03-06 — Model Upgrades: Haiku → Sonnet 4.6 across synthesis tasks

### Model audit and upgrades (no infrastructure changes)
- **Audited** all Anthropic API calls across the codebase
- **Upgraded Haiku → Sonnet 4.6:** `ai_calls.py` (all 4 daily brief calls: BoD insight, training coach, nutrition coach, journal coach + TL;DR), `weekly_digest_lambda.py` (BoD commentary), `monthly_digest_lambda.py` (monthly council)
- **Updated outdated Sonnet strings → Sonnet 4.6:** `wednesday_chronicle_lambda.py`, `nutrition_review_lambda.py`, `weekly_plate_lambda.py` (all were on deprecated `claude-sonnet-4-5-20250929`)
- **Kept Haiku:** `journal_enrichment_lambda.py` (extraction/classification), `anomaly_detector_lambda.py` (simple causal reasoning)
- Platform model standard: Sonnet 4.6 for synthesis/generation, Haiku for extraction/classification

---

## v2.77.1 — 2026-03-05 — Housekeeping: State of Mind resolved, Phase 4 rewards assessed

### Investigations (no code deployed)
- **State of Mind resolved:** How We Feel permissions were toggled OFF in iPhone Settings → Privacy → Health. Toggled ON — pipeline confirmed working (CloudWatch logs show 1 entry landed in S3 + DynamoDB). Fully operational going forward.
- **Prologue + Chronicle v1.1:** Confirmed both were already complete from prior sessions (incorrectly carried as pending). Closed permanently.
- **Character Sheet Phase 4 assessment:** All reward/protocol machinery is already wired (set_reward + get_rewards MCP tools, evaluate_rewards() in output_writers, protocol_recs in character_sheet.json, rendering in html_builder). Only missing: reward definitions in DynamoDB. Full reward ideation menu generated for Matthew + Brittany to review together — 24 reward ideas across 7 categories. Seeding deferred pending their picks.

---

## v2.77.0 — 2026-03-05 — Daily Brief Monolith Extraction (html_builder, ai_calls, output_writers)

### Three modules extracted from `daily_brief_lambda.py` (4,002 → 1,366 lines, 66% reduction)

**`html_builder.py`** — Pure rendering, no AWS dependencies
- Exports: `build_html(...)` (with new `triggered_rewards` / `protocol_recs` params), `hrv_trend_str()`, `_section_error_html()`
- Inlines tiny utilities to avoid circular imports (safe_float, d2f, avg, clamp, fmt_num, get_current_phase)

**`ai_calls.py`** — All Anthropic API calls + data summary builders
- `init(s3_client, bucket, has_board_loader, board_loader_module)` — called at module import time
- 4 AI call functions (BoD, training+nutrition, journal coach, TL;DR+guidance)
- 4 data summary builders (build_data_summary, build_food_summary, build_activity_summary, build_workout_summary)

**`output_writers.py`** — S3 JSON writers + reward evaluation + demo sanitizer
- `init(...)` — late-bound via `_init_output_writers()` in lambda_handler (fetch functions defined after imports)
- `write_dashboard_json`, `write_clinical_json`, `write_buddy_json`
- `evaluate_rewards(character_sheet)` and `get_protocol_recs(character_sheet)` — pre-computed and passed as params to `build_html` so html_builder has zero AWS dependencies
- `sanitize_for_demo`, `_build_avatar_data`

**`daily_brief_lambda.py`** patched: 4,002 → 1,366 lines (36 orchestration functions remain)

### Architecture decisions
- `_evaluate_rewards_brief` / `_get_protocol_recs_brief` moved from html_builder → output_writers; lambda_handler pre-computes and passes results as `triggered_rewards` / `protocol_recs` to `build_html` — keeps html_builder truly pure (no AWS)
- `output_writers.init()` called lazily from `lambda_handler` via `_init_output_writers()` because `fetch_range` / `fetch_date` / `_normalize_whoop_sleep` are defined after the import block
- `ai_calls.init()` called at module import time (no dependency on locally-defined functions)

### Deploy
- `deploy/deploy_daily_brief_v2.77.0.sh` — packages all 6 files, renames entry point, smoke tests
- Clean deploy: all 4 AI calls fired, email sent, 3 JSON files written, 15s duration, 110 MB memory

### Also this session
- Removed stale `ANTHROPIC_SECRET` env var from daily-brief Lambda (was pointing to deleted secret; code now correctly defaults to `life-platform/api-keys`)

---

## v2.76.1 — 2026-03-05 — dropbox-poll Secrets Consolidation Fix

- **dropbox-poll broken since secrets consolidation (v2.75.0):** Lambda had `SECRET_NAME=life-platform/dropbox` hardcoded in env vars, overriding the correct code default after the old secret was deleted. Fixed: env var updated to `life-platform/api-keys` via `update-function-configuration`
- **Key name mismatch in api-keys bundle:** Lambda referenced `app_key`/`app_secret`/`refresh_token` but consolidated bundle uses `dropbox_app_key`/`dropbox_app_secret`/`dropbox_refresh_token`. Patched in `dropbox_poll_lambda.py`
- **Lesson learned:** Any Lambda with an explicit `SECRET_NAME` env var is a latent risk during secret consolidation — audit other Lambdas for stale env var overrides
- Three alarms investigated: dashboard-refresh and life-platform-data-export self-cleared (IAM already fixed in v2.75.0); dropbox-poll required code + env var fix

---

## v2.76.0 — 2026-03-05 — Snapshot Fixes + Doc Debt + scoring_engine.py Extraction

### Snapshot tooling fixes (`audit/platform_snapshot.py`)
- **DDB pagination bug:** `gather_dynamodb()` scan used `Limit=500` — only saw first page of 15,420 items, missing ~17 sources. Fixed with `while True` / `LastEvaluatedKey` loop
- **EventBridge keyword list:** Added 6 missing Lambdas: `wednesday-chronicle`, `weekly-plate`, `adaptive-mode-compute`, `character-sheet-compute`, `nutrition-review`, `dashboard-refresh`

### Documentation debt cleared
- `COST_TRACKER.md` updated from v2.63.0 → v2.75.0 (6 secrets, $3/mo, actuals, planned features)
- `INFRASTRUCTURE.md` updated from v2.67.0 → v2.75.0 (29 Lambdas, 35 alarms, 121 tools, secrets rewritten)
- `INCIDENT_LOG.md` updated from v2.61.0 → v2.75.0 (4 new incidents, resolved gaps section)
- `USER_GUIDE.md` updated from v2.66.1 → v2.75.0 (121 tools, 3 new emails, new Q&A sections, new tool tables)

### `scoring_engine.py` — Phase 1 monolith extraction
- Extracted 13 functions from `daily_brief_lambda.py` into standalone `lambdas/scoring_engine.py` (422 lines)
- `daily_brief_lambda.py`: 4,002 → 3,589 lines, 61 → 48 functions
- Consolidated duplicate dedup functions: `_dedup_activities` (simpler) removed; call site updated to `dedup_activities`
- Deploy script: `deploy/deploy_daily_brief_v2.76.0.sh` (bundles both files in one zip)
- **Pending deploy** — run `./deploy/deploy_daily_brief_v2.76.0.sh` in terminal

### Alarm triage + dropbox-poll fix
- `dashboard-refresh` alarm: self-resolved — IAM was fixed in v2.75.0; earlier failed runs had already triggered the alarm. Cleared on next run
- `life-platform-data-export` alarm: same pattern, self-resolved
- `dropbox-poll` alarm: actively broken since secrets consolidation (v2.75.0). Root cause: `SECRET_NAME=life-platform/dropbox` env var overriding correct code default after old secret deleted. Secondary: key names differ (`dropbox_app_key` vs `app_key`). Fixed: env var updated to `life-platform/api-keys`, code patched (`deploy/fix_dropbox_poll_secret.sh`)
- Added "secrets consolidation watch-out" pattern to INCIDENT_LOG observations

---

## v2.75.0 — 2026-03-05 — Platform Health Audit + P0/P1 Fixes + Secrets Consolidation

### P0 Fixes

**wednesday-chronicle packaging bug (was failing since last deploy)**
- `Runtime.ImportModuleError: No module named 'lambda_function'` — zip contained `wednesday_chronicle_lambda.py` but handler expects `lambda_function.py`
- Fixed via universal `deploy_lambda.sh` (auto-reads handler config from AWS)
- Missed Chronicle installment published; DLQ purged (5 stale messages)

**anomaly-detector same packaging bug**
- Same root cause and fix
- Backfilled Mar 4–5 anomaly detection

### P1 Fixes

**Log retention — 10 log groups set to 30 days**
- us-west-2: adaptive-mode-compute, character-sheet-compute, dashboard-refresh, life-platform-data-export, life-platform-key-rotator, nutrition-review, wednesday-chronicle, weekly-plate
- us-east-1: life-platform-buddy-auth, life-platform-cf-auth

**CloudWatch error alarms — 5 previously unmonitored Lambdas**
- New alarms: `adaptive-mode-compute-errors`, `character-sheet-compute-errors`, `dashboard-refresh-errors`, `life-platform-data-export-errors`, `weekly-plate-errors`
- 86400s period, threshold 1, `notBreaching` on missing data → SNS `life-platform-alerts`
- Total alarms: 30 → 35

**dashboard-refresh IAM fix (discovered via new alarm)**
- Alarm fired immediately on creation — revealed Lambda had been `AccessDenied` on S3 every run since deployment
- Root cause: `lambda-mcp-server-role` missing `s3:PutObject` and `s3:ListBucket`
- Added `s3-dashboard-write` inline policy: `PutObject`/`GetObject` on `dashboard/*`, `buddy/*`, `profile.json` + `ListBucket` on bucket
- Dashboard had been silently failing on every refresh since deployed — fixed

**mcp/config.py version bump + MCP Lambda redeploy**
- `__version__` corrected from `2.50.0` → `2.74.0` (was 24 versions stale)
- MCP Lambda redeployed with full `mcp/` package: 216KB → 1.16MB (confirms complete bundle)

**weekly_digest_lambda.py hardcoded values**
- `dynamodb.Table("life-platform")` → `os.environ.get("TABLE_NAME", "life-platform")`
- `ses` and `secrets` boto3 clients: hardcoded `"us-west-2"` → env var
- `RECIPIENT` and `SENDER`: hardcoded emails → env vars
- Lambda redeployed

### Secrets Manager Consolidation (12 → 6 secrets, saves $2.40/month)

**New secret: `life-platform/api-keys`** — merges 6 static API key secrets:

| Merged Secret | Key in `api-keys` |
|---|---|
| `life-platform/anthropic` | `anthropic_api_key` |
| `life-platform/todoist` | `todoist_api_token` |
| `life-platform/habitify` | `habitify_api_key` |
| `life-platform/health-auto-export` | `health_auto_export_api_key` |
| `life-platform/notion` | `notion_api_key` + `notion_database_id` |
| `life-platform/dropbox` | `dropbox_app_key` + `dropbox_app_secret` + `dropbox_refresh_token` |

**Kept separate** (OAuth tokens written back by Lambdas, or rotation-enabled):
`whoop`, `withings`, `strava`, `eightsleep`, `garmin`, `mcp-api-key`

**13 Lambda code changes** — all use `.get("new_key") or .get("old_key")` backwards-compatible pattern:
`daily_brief`, `weekly_digest`, `journal_enrichment`, `wednesday_chronicle`, `weekly_plate`, `monthly_digest`, `nutrition_review`, `anomaly_detector` → `anthropic_api_key`
`todoist` → `todoist_api_token`, `habitify` → `habitify_api_key`, `health_auto_export` → `health_auto_export_api_key`, `notion` → `notion_api_key`/`notion_database_id`, `dropbox` → field names unchanged

**9 IAM role updates** — `api-keys-read` inline policy added to all roles reading the new secret

**Old secrets deleted with 7-day recovery window** (restorable if needed)

### Files
| File | Change |
|------|--------|
| `mcp/config.py` | Version 2.50.0 → 2.74.0 |
| `lambdas/daily_brief_lambda.py` | Secret name env var + `anthropic_api_key` field |
| `lambdas/weekly_digest_lambda.py` | Hardcoded table/clients/emails → env vars + secret consolidation |
| `lambdas/journal_enrichment_lambda.py` | Secret default + field fallback chain |
| `lambdas/wednesday_chronicle_lambda.py` | `get_anthropic_key()` → env var + new field |
| `lambdas/weekly_plate_lambda.py` | Same as chronicle |
| `lambdas/monthly_digest_lambda.py` | Same as chronicle |
| `lambdas/nutrition_review_lambda.py` | Same as chronicle |
| `lambdas/anomaly_detector_lambda.py` | Same as chronicle |
| `lambdas/todoist_lambda.py` | Secret name env var + `todoist_api_token` with fallback |
| `lambdas/habitify_lambda.py` | Secret name env var + `habitify_api_key` with fallback |
| `lambdas/health_auto_export_lambda.py` | Secret name env var + `health_auto_export_api_key` with fallback |
| `lambdas/notion_lambda.py` | Secret name env var + `notion_api_key`/`notion_database_id` with fallbacks |
| `lambdas/dropbox_poll_lambda.py` | Secret name env var (field names unchanged) |
| `deploy/fix_p0_broken_lambdas.sh` | NEW — P0 chronicle + anomaly redeployment |
| `deploy/fix_p1_infra.sh` | NEW — log retention + alarms + MCP/weekly-digest redeploys |
| `deploy/migrate_secrets_consolidation.sh` | NEW — full secrets consolidation migration |

---

## v2.74.0 — 2026-03-05 — Hydration Fix: HAE Water Pipeline

### Health Auto Export Webhook — Water Metric Mapping Fix
- Added `"Water"` and `"water"` to webhook metric map (previously only `"Dietary Water"` / `"dietary_water"`)
- HAE app sends metric as `"Water"` — webhook was silently dropping all water data
- Threshold raised from 118ml to 500ml to reject ~350ml morning HAE artifacts (incomplete sync noise)
- `score_hydration()` now returns `None` + `"NO DATA"` signal instead of fake low value when below threshold
- Daily Brief guidance prompt updated: explicitly instructs AI not to give hydration tips when data is unavailable

### New HAE Automation (Matthew)
- Dedicated water-only HAE automation running at 9pm PT
- Sends `Water` metric for past 7 days on first run — all 7 days backfilled successfully
- Webhook `update_item` pattern means water merges safely into existing apple_health records without overwriting other fields
- 7-day backfill confirmed: 4309 / 3557 / 3834 / 3259 / 3059 / 3117 / 3182 ml

### Adaptive Mode Lambda — Bug Fixes (deployed as part of v2.73.0 rollout)
- Fixed: DynamoDB keys were uppercase `PK`/`SK` — table uses lowercase `pk`/`sk`
- Fixed: habit field names were `t0_possible`/`t0_completed` — actual fields are `tier0_total`/`tier0_done`
- Fixed: journal source was `"journal"` — correct source is `"notion"`
- Fixed: day grade field tried `grade_numeric` first — actual field is `score`
- Fixed: deploy script used relative `DEPLOY_DIR` path, broke after `cd /tmp`
- Fixed: `AWS_REGION` in Lambda env vars (reserved key — removed)
- Fixed: IAM role hardcoded as `lambda-basic-execution` — switched to auto-detect from existing Lambda
- 7-day backfill results: Feb 27 = Rough Patch (35.9), all other days = Standard (40-58)

---

## v2.73.0 — 2026-03-05 — Feature #50: Adaptive Email Frequency

### New Lambda: `adaptive-mode-compute` (29th Lambda)
- Runs at 9:36 AM PT daily (after character sheet at 9:35, before Daily Brief at 10:00)
- Computes **engagement score (0-100)** from 4 signals: journal completion (25%), T0 habit adherence (30%), T1 habit adherence (20%), 7-day grade trend (25%)
- Determines **brief_mode**: `flourishing` (≥70), `standard` (40-69), `struggling` (<40)
- Stores to DynamoDB `SOURCE#adaptive_mode / DATE#YYYY-MM-DD`
- Backfill supported via `{"date": "YYYY-MM-DD"}` event payload

### Daily Brief Lambda — Adaptive Mode Integration
- Fetches pre-computed adaptive mode record at startup (non-fatal fallback to standard)
- **Flourishing mode**: Green 🌟 banner + BoD prompt told to be energising/reinforcing
- **Struggling mode**: Amber 💛 "Rough Patch" banner + BoD prompt told to be warm/gentle/no-guilt
- **Standard mode**: no banner, existing behaviour unchanged
- All changes are additive / non-fatal — brief works without a mode record

### New MCP Module: `mcp/tools_adaptive.py` (26th module)
- `get_adaptive_mode(days=14)` — current mode, engagement score, 4-factor breakdown, mode distribution over requested window, streak in current mode

### Infrastructure
- **EventBridge rule**: `adaptive-mode-compute` at 9:36 AM PT (17:36 UTC) daily
- **Total**: 121 MCP tools, 29 Lambdas, 26 modules, 19 sources

---

## v2.72.0 — 2026-03-05 — 5 Features: Defense Patterns, Biological Age, Metabolic Score, Food Database, Data Export

### New Module: `mcp/tools_longevity.py`
- **#33 Biological Age Estimation** (Sponsor: Okafor/Attia) — `get_biological_age`. Levine PhenoAge algorithm computes biological age from 9 blood biomarkers (albumin, creatinine, glucose, CRP, ALP, lymphocyte %, MCV, RDW, WBC). Trajectory across all 7 draws, genome context for longevity SNPs, Board assessment. The single most meaningful longevity number.
- **#38 Continuous Metabolic Health Score** (Sponsor: Attia/Okafor) — `get_metabolic_health_score`. Composite score (0-100) from CGM (30%), lab biomarkers (35%), weight/BMI (20%), blood pressure (15%). NCEP ATP III metabolic syndrome criteria check. Grade A-F classification.
- **#29 Meal-Level Glycemic Response Database** (Sponsor: Webb/Attia) — `get_food_response_database`. Personal food ranking by estimated glycemic impact. Macro-based proxy scoring (carbs, sugar, fiber ratio), best/worst foods, leaderboard with confidence levels. Builds on existing `get_glucose_meal_response`.
- **#41 Defense Mechanism Detector** (Sponsor: Conti) — `get_defense_patterns`. Queries enriched journal entries for psychological defense mechanisms (intellectualization, avoidance, displacement, etc.). Frequency analysis, mood/stress correlation per pattern, Conti-informed assessment.

### Journal Enrichment Lambda — Defense Mechanism Detection
- Second Haiku call added after main enrichment pass
- Conti-informed prompt for 11 defense mechanisms
- Fields: `enriched_defense_patterns`, `enriched_primary_defense`, `enriched_defense_context`, `enriched_emotional_depth`, `defense_enriched_at`
- Non-blocking: defense enrichment failure doesn't affect main enrichment
- Skips entries already defense-enriched unless `force=true`

### #19 Data Export & Portability
- **New Lambda:** `life-platform-data-export` (28th Lambda)
- Full DynamoDB table dump to `s3://matthew-life-platform/exports/YYYY-MM-DD/`
- One JSON file per source partition + profile + manifest
- Monthly EventBridge schedule: 1st of month at 3 AM PT
- S3 Standard-IA storage class for cost efficiency
- Supports single-source export: `{"export_type": "source", "source": "whoop"}`

### Infrastructure
- `mcp/config.py`: FOOD_RESPONSES_PK constant
- `mcp/registry.py`: tools_longevity import, 4 new tool registrations
- **Tool count: 116 → 120**
- **Lambda count: 27 → 28**
- Deploy: `deploy/deploy_v2.72.0.sh`

---

## v2.71.0 — 2026-03-05 — Character Sheet Phase 4: Rewards, Protocol Recs, Weekly Digest

### Daily Brief — Rewards & Protocol Recommendations
- Wired `_evaluate_rewards_brief()` into character sheet HTML section
  - Queries `rewards` DynamoDB partition for active rewards
  - Checks conditions (character_level, character_tier, pillar_level, pillar_tier)
  - Triggered rewards show gold banner: "🏆 REWARD UNLOCKED: {title}"
  - Auto-updates reward status to `triggered` with timestamp
- Wired `_get_protocol_recs_brief()` into character sheet HTML section
  - Reads `config/character_sheet.json` protocols config from S3
  - Shows recommendations for dropped pillars or pillars below level 41
  - Tier-specific protocol suggestions (up to 2 per pillar)
- Both are try/except wrapped — graceful no-op when no rewards/protocols configured

### Weekly Digest — Character Sheet Section
- **Fixed latent NameError:** `{character_section}` was in template but variable was never defined
- Built full character sheet weekly summary section:
  - Header: tier-colored banner with level, delta, tier, XP
  - 7 pillar mini-bars with weekly level deltas and avg raw scores
  - Level/tier events from the week (pill-style badges)
  - Closest-to-tier-up nudge ("Movement is 3 levels from Momentum")
- Data from `ex_character_sheet()` extraction (already existed, now consumed)

### Deploy
- `deploy/deploy_cs_phase4.sh` — deploys Daily Brief + Weekly Digest (10s gap)

---

## v2.70.1 — 2026-03-05 — State of Mind Pipeline Fix + Universal Deploy Helper

### Bug Fix: State of Mind Ingestion (two stacked bugs)

**Bug 1 — Deploy filename mismatch (systemic, primary blocker)**
- All `health-auto-export-webhook` deploy scripts zipped source as `lambda_function.py`, but Lambda handler is `health_auto_export_lambda.lambda_handler` — expects `health_auto_export_lambda.py`
- Lambda silently loaded stale cached code on every deploy; cold starts, successful deploys, and correct source files all appeared normal
- Fix: zip with original filename matching handler config

**Bug 2 — HAE date field name**
- Health Auto Export sends State of Mind timestamps as `"start"` field, but `process_state_of_mind()` only checked `"date"`, `"startDate"`, `"start_date"`, `"timestamp"`
- Every SoM entry silently dropped because date extraction returned empty
- Fix: added `raw.get("start")` and `raw.get("end")` to date field chain

### New: Universal Lambda Deploy Helper
- `deploy/deploy_lambda.sh` — reads handler config from AWS before packaging
- Extracts expected module name from handler string, zips with correct filename
- Validates zip contents match handler before deploying
- Confirms deploy with LastModified timestamp
- Usage: `./deploy/deploy_lambda.sh <function-name> <source-file>`
- Eliminates entire class of filename mismatch deploy bugs

### Verification
- State of Mind data now flowing: March 5 entry landed (proud, work, valence 0.405)
- `get_state_of_mind_trend` MCP tool returns data successfully

### Files
| File | Action |
|------|--------|
| `lambdas/health_auto_export_lambda.py` | Fixed — added `"start"` and `"end"` to SoM date extraction |
| `deploy/deploy_lambda.sh` | **NEW** — Universal deploy helper |
| `deploy/deploy_som_date_fix.sh` | Created during debugging |
| `deploy/deploy_som_debug.sh` | Created during debugging |

---

## v2.70.0 — 2026-03-04 — Social & Behavioral Tools (Features #28, #35, #36, #40, #42)

### New Module: `mcp/tools_social.py`
- **#40 Life Event Tagging** (Sponsor: Voss) — `log_life_event`, `get_life_events`. Structured log of birthdays, losses, milestones, conflicts, achievements. 13 event types, people tagging, emotional weight (1-5), recurring events. Creates narrative architecture for Chronicle. DDB partition: `life_events`.
- **#42 Contact Frequency Tracking** (Sponsor: Murthy) — `log_interaction`, `get_social_dashboard`. Log meaningful interactions with specific people: type (call/text/in_person/video), depth (surface/meaningful/deep), duration, initiated_by. Dashboard: weekly trends, depth distribution, Murthy threshold assessment (3-5 close relationships), stale contact detection, connection health rating. DDB partition: `interactions`.
- **#35 Temptation Logging** (Sponsor: Rodriguez) — `log_temptation`, `get_temptation_trend`. Log resist/succumb moments across 8 categories (food, alcohol, sleep_sabotage, skip_workout, screen_time, social_avoidance, impulse_purchase, other). Trend analysis: resist rate, category breakdown, trigger patterns, intensity analysis, weekly trends. DDB partition: `temptations`.
- **#36 Cold/Heat Exposure** (Sponsor: Huberman) — `log_exposure`, `get_exposure_log`, `get_exposure_correlation`. Log cold/heat sessions (7 types: cold_shower, cold_plunge, ice_bath, sauna, hot_bath, contrast, other). Correlation engine: same-day and next-day comparison vs rest days for HRV, sleep, recovery, mood. DDB partition: `exposures`.

### Exercise Variety Scoring in `mcp/tools_training.py`
- **#28 Exercise Variety** (Sponsor: Chen) — `get_exercise_variety`. Shannon diversity index across movement patterns, staleness detection (≤2 patterns in rolling window), missing category identification, variety score (0-100) with grade. 10 movement pattern classifications.

### Infrastructure
- `mcp/config.py`: 4 new PK constants (LIFE_EVENTS_PK, INTERACTIONS_PK, TEMPTATIONS_PK, EXPOSURES_PK)
- `mcp/registry.py`: 11 new tool registrations, tools_social import
- **Tool count: 105 → 116**
- **4 new DDB partitions** (no schema changes — single-table pattern)
- Deploy: `deploy/deploy_social_tools_v2.70.sh`

---

## v2.69.0 — 2026-03-04 — Character Sheet Phase 3: Avatar Data Pipeline

### Daily Brief Lambda — Avatar Data Fix
- **Deployed:** `_build_avatar_data()` function (written in v2.64.0 but never deployed)
- Dashboard and buddy `data.json` now include `avatar` object with tier, body_frame, badges, effects, expressions, elite_crown, alignment_ring
- Avatar weight lookback extended from 7 → 30 days to prevent avatar resetting to frame 1 on missed weigh-ins
- Fallback chain: 7-day weight → 14-day weight → 30-day weight → start_weight (302)
- Buddy page weight fallback also improved: uses 30-day avatar weight before falling back to journey start weight

### Daily Brief Email — Inline Avatar
- 96×96 pixel art avatar now rendered in the Character Sheet email section between level header and pillar bars
- Uses pre-composed email composites from S3 (`/avatar/email/{tier}-composite.png`)
- `image-rendering: pixelated` for crisp pixel art scaling in email clients

### P0 Fix — Character Sheet Compute IAM
- **Root cause:** `lambda-mcp-server-role` had no `s3:GetObject` on `config/*` — character-sheet-compute Lambda silently failing since initial deploy
- Added `S3ReadConfig` statement to `mcp-server-permissions` inline policy: `arn:aws:s3:::matthew-life-platform/config/*`
- Lambda now loads `config/character_sheet.json` successfully — test invoke wrote March 4 entry
- 2 days of missing character sheet data (March 3–4) caused `character_sheet: null` in `data.json`

### Data Patch
- One-time `patches/patch_avatar_data.sh` script to backfill avatar + character_sheet into dashboard and buddy `data.json` without triggering a full Daily Brief email

---

## v2.68.0 — 2026-03-04 — Board v2.0 + Infrastructure Hardening

### Board of Directors v2.0.0
- **Added:** Dr. Paul Conti (real_expert) — psychiatry, grief, defense mechanisms, identity, self-compassion. Features: daily_brief (journal interpreter), weekly_digest (psychological patterns), chronicle (interviewee)
- **Added:** Dr. Vivek Murthy (real_expert) — social connection, loneliness, male isolation, friendship, belonging. Features: weekly_digest (social health analyst), chronicle (interviewee)
- **Retired:** Dr. Matthew Walker — sleep domains folded into Dr. Lisa Park
- **Expanded:** Dr. Lisa Park — added sleep_science, cognitive_performance, sleep_stages, chronotype + chronicle feature
- **Board:** 12 → 13 members (net +1: two added, one removed)
- **Rationale:** Board was stacked on physical health optimization but had zero coverage for mental health, grief, identity, loneliness, or social connection — the actual themes of Matthew's journey

### Infrastructure Reference Doc
- **New:** `docs/INFRASTRUCTURE.md` — single-page reference for all URLs, IDs, DNS, CloudFront, Route 53, API Gateway, S3, DynamoDB, SES, SNS, Secrets Manager, Lambda names, EventBridge schedules, local project structure
- Replaces scattered Apple Notes — everything needed to reconstruct or reference the platform in one place

### CloudWatch Alarm Cleanup
- Removed OK-state notifications from 4 alarms that were sending recovery emails (anomaly-detector, daily-brief, monthly-digest, weekly-digest)
- All 26 alarms now ALARM-only — no more noise emails for resolved incidents

### IAM Fix — Blog S3 Write Permission
- Added `arn:aws:s3:::matthew-life-platform/blog/*` to `dashboard-s3-write` inline policy on `lambda-weekly-digest-role`
- Chronicle Lambda can now publish blog posts to S3 (was failing with AccessDenied since blog launch)
- Sid renamed: `DashboardAndBuddyWrite` → `DashboardBuddyBlogWrite`

### Habitify Lambda Packaging Fix
- Same `lambda_function.py` packaging bug as Chronicle — supplement bridge deploy broke the Lambda
- Fix: `deploy/fix_habitify_packaging.sh` — redeploy with correct filename
- Verified: test invoke succeeded, habit ingestion restored

---

## v2.67.0 — 2026-03-04 — Chronicle Week 2 + Lambda Fix

### Chronicle Week 2: "The Empty Journal"
- **Format:** Off-the-record interview (Elena × Matthew) in lieu of empty journal week
- **Thesis:** The empty journal is the story — gap between what's easy to measure and what's hard to face
- **Content:** Hand-written by Elena (not AI-generated), covers backstory (mum, Jo, reorg, Rolex), the "I don't know what I want" moment, Brittany showing up with meals, Maslow's hierarchy framing, onboarding metaphor
- **Published to:** DynamoDB chronicle partition + S3 blog (week-02.html) + email newsletter + updated blog index
- **Week 1 blog backfill:** week-01.html also published (was missing due to earlier Lambda AccessDenied on s3:PutObject)
- **Content file:** `content/chronicle_week2.md` (new directory for manually-written installments)

### Chronicle Lambda Packaging Fix
- **Bug:** March 3 deploy (Phase 3) packaged zip with `wednesday_chronicle_lambda.py` instead of `lambda_function.py`
- **Impact:** Today's 7:00 AM scheduled run failed 3× with `Runtime.ImportModuleError`
- **Fix:** Deploy script now correctly `cp wednesday_chronicle_lambda.py lambda_function.py` + includes `board_loader.py` in zip
- **Known issue:** Lambda role still lacks `s3:PutObject` for `blog/*` prefix — future Lambda-triggered blog publishes will fail until IAM is updated

---

## v2.66.1 — 2026-03-04 — Supplement Bridge + State of Mind Investigation

### Supplement Bridge (Habitify → Supplements partition)
- Built supplement mapping config: 21 Habitify habits → structured supplement entries with dose, unit, timing, category
- 3 timing batches: morning (fasted, 4), afternoon (with food, 12), evening/sleep stack (before bed, 5)
- Integrated `bridge_supplements()` into `habitify_lambda.py` — auto-fires after every `write_to_dynamo()` call
- Non-fatal: supplement bridge errors caught and logged, never block Habitify ingestion
- Backfilled 7 existing Habitify days (78 entries, 21 unique supplements)
- `get_supplement_log` and `get_supplement_correlation` MCP tools now have real data
- Deploy: `deploy/deploy_v2.55.1_habitify_supplement_bridge.sh` (function: `habitify-data-ingestion`)

### State of Mind Investigation
- Traced full ingestion path: How We Feel → HealthKit → Health Auto Export → Lambda webhook v1.5.0
- Lambda code fully deployed and functional — parsing logic runs on every webhook invocation
- Identified probable root cause: How We Feel may not write to Apple's `HKStateOfMind` data type
- All webhook hits show `som_entries_new: 0` — no SoM payloads arriving from Health Auto Export
- User to verify on iPhone: Settings → Privacy → Health → How We Feel → check Write permissions for State of Mind
- Fallback plan: use Apple's native State of Mind logger (Health app / Watch Mindfulness app)

---

## v2.66.0 — 2026-03-03 — Dashboard Refresh Lambda + Bug Fixes

### Dashboard Refresh (27th Lambda)
- New `dashboard-refresh` Lambda runs at 2 PM and 6 PM PT (in addition to 10 AM Daily Brief)
- Lightweight intraday refresh: re-queries weight, glucose, zone2, TSB, source count
- Reads existing `data.json` from S3, preserves AI-computed fields (day_grade, TL;DR, BoD, character sheet)
- Re-computes `buddy/data.json` with fresh signals (food, exercise, routine, weight)
- No AI calls, no email — pure data refresh (~$0.01/month cost impact)
- EventBridge rules: `dashboard-refresh-afternoon` (22:00 UTC), `dashboard-refresh-evening` (02:00 UTC)

### Radar Chart Fix
- SVG viewBox widened: 240×240 → 300×290, center shifted to (150,145)
- Labels now readable: Sleep, Move, Nutrition, Metabolic, Mind, Social, Habits (was: Nutri, Meta, Relate, Consist)
- Label distance increased: maxR+16 → maxR+22 for breathing room
- Badge positions adjusted for new center point

### Weekly Plate Hallucination Fix
- Tightened Greatest Hits prompt: AI must use ONLY exact food names from log data
- Added explicit anti-hallucination rules: no fabricating meal pairings, side dishes, or accompaniments
- CRITICAL section renamed to "HALLUCINATION PREVENTION" with specific examples
- "Try This" section explicitly marked as the creative zone for recipe suggestions

### DST Script Updates
- Added missing `character-sheet-compute` rule (9:35 AM PT) to DST spring forward script
- Added new `dashboard-refresh-afternoon` and `dashboard-refresh-evening` rules
- Added `weekly-plate-schedule` rule
- Updated rule count: 21 → 25

---

## v2.65.0 — 2026-03-03 — PNG Sprite Migration: Pixel Art Avatar System

### Sprite Asset Pipeline
- 48 PNG sprites generated via Python/Pillow: 15 base characters (5 tiers × 3 frames), 21 badges, 6 effects, 1 crown, 5 email composites
- Tier progression: Foundation (black hoodie, slouched) → Momentum (grey tee, straightening) → Discipline (blue performance, tall) → Mastery (charcoal henley, smile) → Elite (emerald shirt, crown)
- All sprites uploaded to `s3://matthew-life-platform/dashboard/avatar/` with CloudFront CDN
- Self-contained deploy script with base64-embedded PNGs (`deploy/deploy_sprites_v2.sh`)

### Dashboard + Buddy Page Migration
- `lambdas/dashboard/index.html`: Replaced 65-line SVG `renderAvatar()` with PNG `<img>` loader (48px→192px, `image-rendering: pixelated`)
- `lambdas/buddy/index.html`: Replaced 28-line SVG renderer with PNG loader (48px→96px)
- Sprite URL: `https://dash.averagejoematt.com/avatar/base/{tier}-frame{frame}.png`
- Avatar data fallback: dashboard derives tier + body_frame from `character_sheet` when `data.avatar` is absent

### Bug Fixes
- Fixed CloudFront double-pathing: origin path `/dashboard` caused `dashboard/dashboard/avatar/...` 404s
- Documented correct CloudFront distribution IDs: dashboard=`EM5NPX6NJN095`, blog=`E1JOC1V6E6DDYI`

---

## v2.64.0 — 2026-03-03 — Character Sheet Phase 3: Visual Layer

### Chronicle Integration
- `wednesday_chronicle_lambda.py`: Added `character_sheet` fetch to `gather_chronicle_data()` (queries DDB character_sheet partition for weekly data)
- New CHARACTER SHEET section in `build_data_packet()`: overall level + tier, 7 pillar breakdown with week-over-week deltas, level events as narrative hooks, active cross-pillar effects
- Elena guidance added to both config-driven and fallback system prompts: tier transitions as story moments, effects as built-in metaphors, natural weaving (not RPG mechanic explanations)

### Avatar Data Contract
- `daily_brief_lambda.py`: New `_build_avatar_data()` helper function computes full avatar state from character_sheet + weight data
  - `tier`: tier name for base sprite selection
  - `body_frame`: 1/2/3 based on composition_score (302→260 / 259→215 / 214→185 lbs)
  - `badges`: 7 pillar states (hidden/dim/bright) based on level thresholds (41+ = dim, 61+ = bright)
  - `effects`: active cross-pillar effect names for CSS class matching
  - `expressions`: 4 micro-detail states (eyes, posture, skin_tone, ground) from pillar levels
  - `elite_crown` / `alignment_ring`: boolean flags for rare achievement states
- Avatar data added to both `write_dashboard_json()` and `write_buddy_json()` outputs

### Dashboard Avatar UI
- Programmatic SVG avatar renderer (`renderAvatar()`) in `index.html`
  - 48×48 pixel canvas, 3x render (144×144px) — matches AVATAR_DESIGN_STRATEGY.md spec
  - Body frame morphing: torso/shoulder width varies by frame (16/14/12px torso)
  - Tier-specific aura glow (Foundation: none → Elite: double ring)
  - Character features: brown hair, beard, blue-grey eyes, black tee, Whoop band (right), watch (left)
  - Expression system: bright/dim eyes (Sleep), forward posture (Movement), warm/cool skin (Metabolic), solid/faded ground (Consistency)
  - Discipline+ chest emblem, Elite crown/halo
  - 7 badge constellation at clock positions with hidden/dim/bright states and emoji icons
  - Ground glow effect matching expressions.ground
  - Frame label showing body frame number + composition % to goal
- Positioned between Character Sheet header and radar chart

### Buddy Page Avatar
- Compact SVG avatar renderer (`renderBuddyAvatar()`) in buddy `index.html`
  - 72×72px render, simpler than dashboard (no badges — pillar bars show that info)
  - Same body frame morphing and tier aura as dashboard
  - Positioned between Character Sheet header and pillar bars

### Technical Notes
- All avatars are programmatic SVG placeholders — will be replaced with real pixel art PNGs once generated and uploaded to S3 at `dashboard/avatar/` path
- Avatar data is non-fatal: missing avatar data = section hidden (graceful degradation)
- No new Lambdas, no cost increase
- Deploy: `deploy/deploy_character_sheet_phase3.sh`

---

## v2.63.0 — 2026-03-03 — The Weekly Plate: Friday Food Magazine Email (26th Lambda)

### New Feature

**The Weekly Plate** — A personalized Friday evening food email (6:00 PM PT). Magazine-style couch read built from 14 days of MacroFactor data, designed to be enjoyable for both Matthew and Brittany.

5 sections:
1. **This Week on Your Plate** — narrative week recap with weight trend woven in
2. **Your Greatest Hits** — most frequent meals/ingredients, why they work, small tweaks
3. **Try This** — 2-3 recipe riffs based on actual ingredients and flavor profiles (not random Pinterest)
4. **The Wildcard** — one ingredient missing from recent logs + Met Market product suggestion
5. **The Grocery Run** — screenshot-able grocery list by store section (protein, produce, dairy, pantry)

Technical: Sonnet 4.5 at temperature 0.6, 14-day food log lookback, ~$0.04/week. Lambda `weekly-plate`, EventBridge `cron(0 2 ? * SAT *)` (Friday 6 PM PT = Saturday 02:00 UTC).

---

## v2.62.0 — 2026-03-03 — Daily Brief QA: Dynamic Weight, 7-Day Training Context, Subject Line Fixes

### Bug Fixes

**Subject line shows wrong date** — subject displayed yesterday's date (e.g. "Mon Mar 2" on Tuesday). Brief runs Tuesday morning *for* Tuesday; now shows today's date.

**Subject line cryptic readiness code** — G/M/E/- replaced with 🟢/🟡/🔴/⚪ emoji for at-a-glance readability.

**"Losing 117 lbs" hardcoded in 4 AI prompts** — training coach, journal coach, BoD intro (config + fallback), and TL;DR/guidance all had static `302->185` / `losing 117 lbs` text. AI misinterpreted this as "already lost 117 lbs." Now dynamically computed from `latest_weight`, `journey_start_weight_lbs`, and `goal_weight_lbs` (e.g. "Started at 302 lbs, currently 290 lbs, goal 185 lbs (12 lost so far, 105 to go)").

**Training coach panics on rest days** — coach only saw yesterday's activities. On a walk day after 3 days of lifting, it warned about "zero strength training" and "hemorrhaging muscle." Now includes LAST 7 DAYS TRAINING CONTEXT with all recent activities, plus explicit instruction: if yesterday was a rest/light day after recent strength sessions, acknowledge recovery is appropriate.

### New Helpers

- `_build_weight_context(data, profile)` — dynamic weight string for all AI prompts
- `_build_recent_training_summary(data)` — 7-day activity summary from `strava_7d`
- `strava_7d` added to `gather_daily_data()` return dict (filtered from existing `strava_60d` fetch, no extra DDB call)

---

## v2.61.0 — 2026-03-03 — Data Integrity Sweep (Buddy Fixes, Dedup, Hydration Regrade)

### Bug Fixes

**MacroFactor Field Name Mismatch** (`write_buddy_json`)
- Buddy page showed "No food logged in 99 days" despite active daily logging
- Root cause: code checked `calories`/`energy_kcal`, MacroFactor stores `total_calories_kcal`
- Fix: added fallback chain `total_calories_kcal` → `calories` → `energy_kcal` (and protein equivalent)

**Activity Dedup — WHOOP + Garmin → Strava** (`_dedup_activities()`)
- Both WHOOP and Garmin push to Strava independently, causing duplicate activities
- New `_dedup_activities()` function: if two activities start within 15 min and durations within 40%, keep higher-priority device (Garmin > Apple > WHOOP)
- Applied at read-time in buddy page and daily brief Lambda

**Hydration Data Missing** (Health Auto Export pipeline)
- Health Auto Export app wasn't including Dietary Water/Caffeine in automatic webhook pushes
- Only activity metrics (steps, energy, distance) were being sent; water/caffeine excluded
- User's change to hourly sync cadence resolved the issue
- 7-day water backfill via forced push restored correct data (3,000+ ml/day vs 0–350ml)

### Improvements

**Buddy Page UX Overhaul**
- Subtitle: "For Tom" → "Thank you for looking out for me!"
- Timestamp: now includes PST time (e.g., "Tuesday morning, March 3 at 9:43am PT")
- Exercise count: changed from rolling 7-day to true Monday–Sunday weekly reset
  - Monday/Tuesday with 0 sessions shows yellow "No sessions yet this week (Tuesday)" instead of red
  - Status text says "X sessions this week" / "X sessions so far this week"
- Deploy script now includes CloudFront cache invalidation (distribution `ETTJ44FT0Z4GO`)

**Day Grade Regrade Mode** (`lambda_handler`)
- New `regrade_dates` event parameter: `{"regrade_dates": ["2026-02-24", ...]}`
- Recomputes and stores day grades for specified dates without sending email
- Regraded Feb 24–Mar 2 with corrected hydration data (hydration 0→100 across all days)
- Permanent feature for future data corrections

### Notion Journal v1.2 (earlier session)
- Schema-flexible property extraction — no hardcoded field names
- Handles any Notion database schema dynamically

### Deploy
```bash
bash deploy/deploy_buddy_food_fix.sh        # MacroFactor field fix
bash deploy/deploy_buddy_fixes_v256.sh       # Dedup + UX + CloudFront invalidation
bash deploy/deploy_regrade_hydration.sh      # Regrade 7 days
```

---

## v2.60.0 — 2026-03-02 — Character Sheet: Phase 3 (Dashboard Radar + Buddy Tile + Avatar Design)

### Feature: 🎮 Character Sheet — Phase 3: Visual Layer

**Dashboard Radar Chart Tile** (`lambdas/dashboard/index.html`)
- 7-axis SVG radar chart (Sleep, Move, Nutri, Meta, Mind, Relate, Consist)
- 5 concentric grid rings, data polygon with tier-colored fill + stroke
- Dots at each pillar level, labels with name + level number
- Overall level (large number) + tier badge with emoji + XP counter
- Level events (▲/▼ arrows, green for up, yellow for down)
- Active effects as pill chips
- Tier-colored top accent bar (Foundation grey → Elite purple)
- Bug fix: renamed `tc` TSB color variable to `tsbCol` to prevent shadowing `tc()` tier color function
- Position: between 2×2 metric grid and day grade card (slot d6, day grade shifted to d7)

**Buddy Page Character Sheet Tile** (`lambdas/buddy/index.html`)
- Overall level (32px) + tier badge + XP count
- 7 pillar mini-bars: emoji + name + tier-colored fill bar + level number
- Up to 3 recent level events with directional arrows
- Active effect pills
- Tier-colored accent bar matching dashboard design language
- Position: between Journey progress bar (d6) and Tom's prompt (d8)
- Gracefully hidden if character_sheet missing from data.json

**Avatar Design Strategy** (`docs/AVATAR_DESIGN_STRATEGY.md`)
- 620-line creative consultation from panel of 7 virtual experts
- Art direction: 48×48 pixel canvas, 4x render (192×192), 16-bit SNES/Stardew Valley style
- Three-quarter facing right, relaxed ready stance
- Progression model: "Same Person, Growing Power" — body stays recognizable, aura/energy evolves
- 5 tier visual states: Day One → The Spark → The Forge → The Aura → The Apotheosis
- Body morphing: 3 discrete frames tied to weight milestones (302→260, 259→215, 214→185)
- Pillar-specific micro-expressions: bright eyes (Sleep), forward lean (Movement), warm skin (Metabolic), solid ground (Consistency)
- 7 pillar badge constellation (8×8 icons, clock positions, hidden/dim/bright states)
- 6 active effect visualizations (Sleep Drag zzz, Training Boost energy lines, etc.)
- CSS compositing architecture: ~45 individual PNGs layered vs pre-composed
- `image-rendering: pixelated` for pixel-perfect scaling
- Production strategy: AI-generate base → hand polish (Option A)
- Updated data contract with body_frame, composition_score, expressions fields

### Deploy
```bash
cd ~/Documents/Claude/life-platform
./deploy/deploy_dashboard_v260.sh   # Dashboard radar chart
./deploy/deploy_buddy_v260.sh       # Buddy page character sheet tile
```

### Status: ✅ DEPLOYED

---

## v2.59.0 — 2026-03-02 — Character Sheet: Phase 2 (Compute Lambda + Daily Brief Integration)

### Feature: 🎮 Character Sheet — Phase 2: Standalone Compute + Email Integration

**Architecture decision:** Character sheet computation extracted to its own Lambda rather than embedding in Daily Brief. This enables future consumers (gamification digest, push notifications, Chronicle) to read pre-computed records without re-engineering.

**New Lambda: `character-sheet-compute`** (25th Lambda)
- `lambdas/character_sheet_lambda.py` — Standalone compute Lambda (~290 lines)
- Queries 8 source partitions + 5 rolling windows (sleep 14d, strava 7d/42d, macrofactor 14d, withings 30d)
- Loads previous day's state + 21-day raw_score histories for EMA continuity
- Imports `character_engine.py` for scoring, stores result to DDB
- Idempotent (skips if already computed, override with `{"force": true}`)
- Date override for testing: `{"date": "2026-03-01", "force": true}`
- Schedule: 9:35 AM PT daily (EventBridge `character-sheet-compute`)
- 512 MB, 60s timeout, python3.12
- Deploy: `deploy/deploy_character_sheet_compute.sh`

**Daily Brief v2.59.0 updates:**
- `lambda_handler` — fetches pre-computed `character_sheet` record from DDB
- `build_html` — new Character Sheet section after Scorecard: overall level/tier, 7 pillar mini-bars with tier-colored progress, level-up/down event callouts, active effects (Sleep Drag, Synergy Bonus)
- `call_board_of_directors` — receives character context (level, pillar summary, events, effects) for commentary on tier transitions
- `write_dashboard_json` — includes character_sheet summary (level, tier, pillars, events, effects)
- `write_buddy_json` — includes character_sheet summary (level, tier, events)
- Deploy: `deploy/deploy_daily_brief_v259.sh`

---

## v2.58.0 — 2026-03-02 — Character Sheet: Phase 1 Complete (Deploy Pending)

### Feature: 🎮 Character Sheet — Gamified Life Score (Phase 1)
Full scoring engine built and ready to deploy. Persistent Character Level (1-100) composed of 7 weighted pillars: Sleep (20%), Movement (18%), Nutrition (18%), Mind (15%), Metabolic Health (12%), Consistency (10%), Relationships (7%). Features XP accumulation, named tiers (Foundation→Momentum→Discipline→Mastery→Elite), cross-pillar buffs/debuffs (Sleep Drag, Training Boost, Synergy Bonus, etc.), and asymmetric leveling rules (5 days sustained to level up, 7 days sustained to level down).

**Phase 1 deliverables (all code complete):**
- `lambdas/character_engine.py` — 640+ line scoring engine: 7 pillar scorers, EMA smoothing, level/tier transitions, cross-pillar effects, DDB read/write helpers. Follows board_loader.py pattern (importable utility).
- `config/character_sheet.json` — S3 config with all pillar weights, component definitions, tier thresholds, XP bands, cross-pillar effect conditions. Editable via MCP.
- `mcp/tools_character.py` — 3 read-only tools: get_character_sheet (sparklines + effects), get_pillar_detail (component breakdown), get_level_history (timeline + milestones). 102→105 tools.
- `mcp/registry.py` — updated with import + 3 tool registrations
- `backfill/retrocompute_character_sheet.py` — sequential retrocompute from 2026-02-22 baseline. Batch-queries all sources, processes day-by-day maintaining state. Dry run / write / force modes.
- `deploy/deploy_character_sheet_phase1.sh` — uploads config to S3, deploys MCP Lambda with new module

**Spec:** `docs/archive/SPEC_CHARACTER_SHEET.md` (full 12-section Board-reviewed spec)

**Remaining phases:**
- Phase 2: Daily Brief email integration (Character Sheet section + level-up events + Board commentary)
- Phase 3: Dashboard radar chart + pixel-art avatar + buddy page + Chronicle hooks
- Phase 4: User-defined rewards, protocol recommendations, Weekly Digest integration

**Architecture:**
- DynamoDB: `USER#matthew#SOURCE#character_sheet` / `DATE#YYYY-MM-DD`
- Baseline: 2026-02-22, Level 1, Weight 302lb→185lb goal
- Config: `s3://matthew-life-platform/config/character_sheet.json`
- Cost: $0 incremental

### Files Changed
- `lambdas/character_engine.py` — **NEW** — 640+ line scoring engine with 7 pillar scorers, EMA, level/tier transitions, cross-pillar effects, DDB helpers
- `config/character_sheet.json` — **NEW** — Full S3 config: pillar weights, components, thresholds, XP bands, tier definitions, cross-pillar effects
- `mcp/tools_character.py` — **NEW** — 3 read-only MCP tools (get_character_sheet, get_pillar_detail, get_level_history)
- `mcp/registry.py` — Added import + 3 tool registrations (102→105)
- `backfill/retrocompute_character_sheet.py` — **NEW** — Sequential retrocompute script with rolling window assembly, dry run / write / force / stats modes
- `deploy/deploy_character_sheet_phase1.sh` — **NEW** — Deploy script: S3 config upload + MCP Lambda packaging
- `docs/archive/SPEC_CHARACTER_SHEET.md` — Full feature spec with Board review (from design session)
- `docs/PROJECT_PLAN.md` — Version bump to v2.58.0, tool count 102→105
- `docs/CHANGELOG.md` — This entry

---

## v2.57.0 — 2026-03-02 — Board Centralization Phase 2: Lambda Refactor

### Feature: Config-Driven Board Prompts Across All 5 Lambdas
All Lambdas now dynamically build their AI prompts from `s3://matthew-life-platform/config/board_of_directors.json` via shared `board_loader.py` utility. Every Lambda falls back to its original hardcoded prompt if S3 config is unavailable — zero-risk deploy.

**Shared utility: `lambdas/board_loader.py`** (163 lines)
- `load_board()` — S3 read with 5-min in-memory cache
- `get_feature_members()` — filter members by Lambda feature name
- `build_panel_prompt()`, `build_section_prompt()`, `build_member_voice()` — prompt assembly
- `build_narrator_prompt()`, `build_interviewee_descriptions()` — Chronicle-specific
- `get_member_color()`, `get_matthew_context()` — HTML styling + context

**5 Lambdas refactored:**

| Lambda | Version | Prompt Var Renamed | Config Builder | Key Change |
|--------|---------|-------------------|----------------|------------|
| Monthly Digest | v1.0→v1.1.0 | `MONTHLY_PROMPT` → `_FALLBACK_MONTHLY_PROMPT` | `_build_monthly_prompt_from_config()` | 6 advisors from config |
| Weekly Digest | v4.2→v4.3.0 | `BOARD_PROMPT` → `_FALLBACK_BOARD_PROMPT` | `_build_weekly_prompt_from_config()` | 6 advisors + voice; JOURNEY_PROMPT unchanged |
| Nutrition Review | v1.0→v1.1.0 | `SYSTEM_PROMPT` → `_FALLBACK_SYSTEM_PROMPT` | `_build_nutrition_prompt_from_config()` | 3 experts (Norton/Patrick/Attia), card colors from config |
| Daily Brief | v2.53.1→v2.54.0 | inline prompt → `_FALLBACK_BOD_INTRO` | `_build_daily_bod_intro_from_config()` | Unified panel desc from titles; Huberman protocol_tips |
| Chronicle | v1.0→v1.1.0 | `ELENA_SYSTEM_PROMPT` → `_FALLBACK_ELENA_PROMPT` | `_build_elena_prompt_from_config()` | Elena voice/principles from config; 5 interviewee personalities |

**Safety pattern (all 5 Lambdas):**
1. `try: import board_loader` with `_HAS_BOARD_LOADER` flag
2. Config builder returns `None` on any failure
3. Caller checks `None` → falls back to `_FALLBACK_*` constant
4. Logs `[INFO] Using config-driven...` or `[INFO] Using fallback hardcoded...`

### Deploy
- `deploy/deploy_board_centralization.sh` — deploys all 5 Lambdas with `board_loader.py` bundled
- Supports: `--dry-run`, single target (`monthly`, `weekly`, `nutrition`, `daily`, `chronicle`)
- 10-second delay between sequential deploys for Lambda propagation

### Files Changed
- `lambdas/board_loader.py` (NEW, 163 lines)
- `lambdas/monthly_digest_lambda.py` (741→839 lines)
- `lambdas/weekly_digest_v2_lambda.py` (1884→1975 lines)
- `lambdas/nutrition_review_lambda.py` (645→759 lines)
- `lambdas/daily_brief_lambda.py` (3329→3393 lines)
- `lambdas/wednesday_chronicle_lambda.py` (1232→1363 lines)
- `deploy/deploy_board_centralization.sh` (NEW)

---

## v2.56.0 — 2026-03-01 — Board of Directors Centralization

### Feature: Centralized Board of Directors Config
`config/board_of_directors.json` — single source of truth for all 12 expert personas across 5 Lambdas. S3-stored, human-readable, MCP-manageable.

**12 members defined:**
- 6 fictional advisors: Dr. Sarah Chen (training), Dr. Marcus Webb (nutrition), Dr. Lisa Park (sleep), Dr. James Okafor (longevity), Coach Maya Rodriguez (behavioral), The Chair (synthesis)
- 5 real experts: Dr. Layne Norton (macros), Dr. Rhonda Patrick (micronutrients/genomics), Dr. Peter Attia (metabolic), Dr. Andrew Huberman (protocols), Dr. Matthew Walker (sleep science)
- 1 narrator: Elena Voss (Chronicle journalist)

**Each member includes:** name, title, type, emoji, color, domains, data_sources, voice profile (tone/style/catchphrase), principles, relationship_to_matthew, focus_areas, per-feature config (role, section_header, prompt_focus)

### MCP Tools: +3 (99 → 102)
- `get_board_of_directors` — View/filter board members by ID, type, feature, or active status
- `update_board_member` — Add new members or partial-update existing ones (deep-merge)
- `remove_board_member` — Soft-delete (deactivate) or hard-delete members

### Architecture
- New module: `mcp/tools_board.py` — S3-backed CRUD for board config
- Config path: `s3://matthew-life-platform/config/board_of_directors.json`
- Pattern mirrors existing `config/profile.json` — read-heavy, rarely written, consumed as whole unit

### Deploy
- `deploy/deploy_board_of_directors.sh` — uploads config to S3 + redeploys MCP server

### Next Steps
- Phase 2: Refactor Lambdas (Weekly Digest, Monthly Digest, Nutrition Review, Chronicle, Daily Brief) to consume board config from S3 instead of hardcoded inline prompts
- This decouples persona definitions from Lambda code — edit a persona without redeploying

---

## v2.55.2 — 2026-03-01 — Freshness Checker + Withings Token Fix

### Bug Fix: Freshness Checker — False stale alerts from sub-record sorting
`date_str` now truncated to `YYYY-MM-DD` (`[:10]`). Previously, sub-records (e.g., individual workouts) could sort above the daily record, causing the freshness checker to compare against a sub-record key instead of the actual date — triggering false ❌ stale alerts.

### Bug Fix: Withings Lambda — Stale refresh_token in gap-fill loop
`get_secret()` is now called per iteration in the gap-fill loop. Previously, the token was fetched once at the start; if Withings invalidated the old refresh_token mid-loop (as it does after each use), subsequent iterations would fail silently. Each iteration now gets a fresh token.

### Operational
- Withings Lambda invoked manually to pick up today's weigh-in

---

## v2.55.1 — 2026-03-01 — Daily Brief P0 Bug Fixes (Dashboard + Buddy JSON)

### Bug Fix: `write_dashboard_json()` — NameError on `component_details`
The hotfix v2.54.1 restored from a backup that predated the `component_details` parameter addition to `write_dashboard_json()`. The function referenced `component_details` as a free variable → `NameError` on every invocation, caught by internal try/except → dashboard tiles silently missing habit tier data. Fix: current code on disk already had `component_details=None` default parameter + handler passes it as kwarg. Redeployed.

### Bug Fix: `write_buddy_json()` — IAM AccessDenied on `buddy/data.json`
`lambda-weekly-digest-role` inline policy (`weekly-digest-access`) lacked `s3:PutObject` for `buddy/*` path. Added alongside existing `dashboard/*` permission. Buddy page data.json will now refresh daily.

### Deploy
- `deploy/fix_daily_brief_p0_bugs.sh` — IAM policy update (Python-based merge, preserves existing statements) + Lambda redeploy + demo-mode smoke test

---

## v2.55.0 — 2026-03-01 — Sleep SOT Redesign: Whoop → Primary Sleep Source

### Architecture Change
Sleep Source-of-Truth split from a single Eight Sleep domain into two sub-domains:
- **Sleep Duration, Staging, Score, Efficiency** → **Whoop** (wrist sensor captures ALL sleep regardless of location)
- **Sleep Environment** (bed temperature, toss & turns, bed presence) → **Eight Sleep** (pod sensor, unchanged)

Driven by couch-sleep scenario: Eight Sleep truncates sleep starting outside the pod (reports 6h when Whoop correctly reports 9h). Whoop becomes SOT for "how much and how well did you sleep" while Eight Sleep stays SOT for "what happened in your bed environment."

### New: `normalize_whoop_sleep()` Shared Normalizer
Added to `mcp/helpers.py`. Maps Whoop DynamoDB fields to common schema used by all consumers:
- `sleep_quality_score` → `sleep_score`, `sleep_efficiency_percentage` → `sleep_efficiency_pct`
- Stage hours → percentages: `slow_wave_sleep_hours` → `deep_pct`, `rem_sleep_hours` → `rem_pct`
- ISO timestamps → decimal hours: `sleep_start` → `sleep_onset_hour`, `sleep_end` → `wake_hour`
- Idempotent: won’t overwrite existing fields

### MCP Tool Updates (Phase 1)
- **`tools_sleep.py`**: `tool_get_sleep_analysis()` now queries Whoop + normalizes. Environment tool unchanged.
- **`tools_correlation.py`**: All 3 sleep correlation tools (caffeine, exercise, alcohol) switched to Whoop.
- **`tools_health.py`**: `get_readiness_score()` sleep component switched to Whoop (key: `eight_sleep` → `sleep_quality`). `get_health_trajectory()` recovery section uses single Whoop query instead of Whoop + Eight Sleep.

### Documentation
- **`DATA_DICTIONARY.md`**: SOT domain table split, Metric Overlap Map updated, Sleep metric reference rewritten with full field mapping.

### Lambda Migrations (Phase 2–3 — Deployed)
- **`daily_brief_lambda.py`**: Sleep section fully migrated to Whoop fields
- **`weekly_digest_lambda.py`**: Sleep analysis migrated to Whoop
- **`monthly_digest_lambda.py`**: Added `ex_whoop_sleep()` extractor
- **`anomaly_detector_lambda.py`**: METRICS list switched from `("eightsleep", "sleep_score")` / `("eightsleep", "sleep_efficiency")` to `("whoop", "sleep_quality_score")` / `("whoop", "sleep_efficiency_percentage")`
- **`wednesday_chronicle_lambda.py`**: Sleep data packet section → Whoop. Added separate "SLEEP ENVIRONMENT (Eight Sleep)" section for bed temp/room temp/toss & turns
- **`mcp/tools_lifestyle.py`**: Migrated (intentional Eight Sleep refs retained for bed-specific metrics like onset latency)
- **DynamoDB PROFILE#v1**: `source_of_truth.sleep` → `"whoop"`, `source_of_truth.sleep_environment` → `"eightsleep"`

### Not Yet Migrated
- Dashboard `data.json` / Buddy `data.json` — sleep fields still from Eight Sleep (non-critical, display only)
- Clinical Summary JSON — still references Eight Sleep sleep metrics

### Files
| File | Action |
|------|--------|
| `mcp/helpers.py` | Added `normalize_whoop_sleep()` |
| `mcp/config.py` | `"sleep": "whoop"`, `"sleep_environment": "eightsleep"` |
| `mcp/tools_sleep.py` | SOT flipped: eightsleep → whoop + normalize |
| `mcp/tools_correlation.py` | All 3 sleep correlations → whoop + normalize |
| `mcp/tools_health.py` | Readiness + trajectory → whoop + normalize |
| `mcp/tools_lifestyle.py` | Migrated (bed-specific ES refs intentional) |
| `lambdas/daily_brief_lambda.py` | Sleep section → Whoop |
| `lambdas/weekly_digest_lambda.py` | Sleep analysis → Whoop |
| `lambdas/monthly_digest_lambda.py` | Added `ex_whoop_sleep()` |
| `lambdas/anomaly_detector_lambda.py` | METRICS → Whoop sleep fields |
| `lambdas/wednesday_chronicle_lambda.py` | Sleep → Whoop + ES environment section |
| `deploy/deploy_sleep_sot_redesign.sh` | 7-step deploy (6 Lambdas + DDB profile) |
| `docs/DATA_DICTIONARY.md` | SOT tables, metric overlap, field reference updated |
| `handovers/2026-03-01_sleep_sot_completion.md` | Final handover |

---

## v2.54.3 — 2026-03-01 — Freshness Checker + Withings Token Fix

### Bug Fixes
- **Freshness Checker: sub-record SK parsing** — Reverse-sort query with `Limit=1` could return a workout sub-record like `DATE#2026-03-01#WORKOUT#uuid` instead of the daily record. `date_str` now truncated to first 10 chars (`[:10]`) so only `YYYY-MM-DD` is parsed. Fixes false ❌ for Whoop (and any source with sub-record SKs).
- **Withings gap-fill token rotation** — Withings OAuth invalidates the old refresh_token when issuing a new one. The gap-fill loop called `get_secret()` once before the loop, so iteration 2+ used a stale refresh_token and failed with `503: invalid refresh_token`. Now calls `get_secret()` at the start of each iteration to always use the latest token from Secrets Manager.

### Root Cause Analysis
- **Withings Feb 28 outage:** `ImportModuleError` at 14:15 UTC (wrong filename in zip from prior deploy). Fixed by redeploy at 17:29 UTC, but scheduled 6:15 AM run was lost. Gap-fill then failed on subsequent dates due to the token rotation bug.
- **Withings Feb 25–26:** `URLError: Cannot assign requested address` (transient Lambda networking). Retried successfully on 3rd attempt.

### Files
| File | Action |
|------|--------|
| `lambdas/freshness_checker_lambda.py` | Fixed — `[:10]` on date_str |
| `lambdas/withings_lambda.py` | Fixed — `get_secret()` per gap-fill iteration |
| `deploy/deploy_freshness_withings_fix.sh` | Created |

---

## v2.54.2 — 2026-03-01 — P0 Bug Fixes: Dashboard JSON + Buddy IAM

### Bug Fixes
- **`write_dashboard_json()` NameError** — `component_details` was used at lines 2497–2498 but never passed as a parameter. Added `component_details=None` to function signature with safe empty-dict default, and passed it from handler call. Dashboard tiles now get habit tier0/tier1 completion data.
- **`write_buddy_json()` IAM permission** — `lambda-weekly-digest-role` inline policy `dashboard-s3-write` only allowed `s3:PutObject` on `dashboard/*`. Updated to also allow `buddy/*`. Buddy page `data.json` will now update daily.

### Files
| File | Action |
|------|--------|
| `lambdas/daily_brief_lambda.py` | Fixed — `component_details` param added to `write_dashboard_json()` |
| `deploy/deploy_p0_bugfixes_v2.54.2.sh` | Created — deploys both fixes |
| IAM `dashboard-s3-write` policy | Updated — added `buddy/*` resource |

---

## v2.54.1 — 2026-03-01 — Hotfix: Daily Brief Indentation Fix

### Incident
- **Symptom:** Daily Brief Lambda failing with `Runtime.UserCodeSyntaxError: expected 'except' or 'finally' block` at line 1853
- **Impact:** No morning brief email since Feb 28 (last successful brief was for Feb 27 data)
- **Root cause:** Indentation corruption in `build_html()` — 26 lines across 8 try/except sections dropped from 6-space to 4-space indent, breaking Python block structure
- **First occurrence:** Feb 23 (line 367 f-string error), then Feb 25 (ImportModuleError), then Mar 1 (line 1853 persistent)

### Fix
- Restored from clean backup (`daily_brief_lambda.py.backup-20260301-123650`)
- Applied surgical `sed` fix to 26 specific lines at 9 line ranges (1862–1869, 1871–1874, 1963–1965, 1984, 1994–1998, 2035, 2111–2112, 2118, 2131)
- Verified with `python3 -m py_compile`, deployed, invoked successfully
- Brief sent: Grade 77 (B) for Feb 28 data

### Pre-existing Issues Discovered (non-fatal)
- `write_dashboard_json()`: `component_details` not passed — `name 'component_details' is not defined`
- `write_buddy_json()`: `lambda-weekly-digest-role` missing `s3:PutObject` for `buddy/` prefix

### Files
| File | Action |
|------|--------|
| `lambdas/daily_brief_lambda.py` | Fixed — 26 lines re-indented |
| `deploy/hotfix_daily_brief_v7.sh` | Created — working deploy script |
| `deploy/hotfix_daily_brief_v[1-6].sh` | Created during debugging (v1–v4 had bugs, v5–v6 unused) |

---

## v2.54.0 — 2026-03-01 — Feature #15: MCP API Key Rotation

### Rotator Lambda
- **Lambda:** `life-platform-key-rotator` (Python 3.12, 128 MB, 30s timeout)
- **Role:** `lambda-key-rotator-role` with scoped Secrets Manager permissions
- **Protocol:** Standard 4-step Secrets Manager rotation (createSecret → setSecret → testSecret → finishSecret)
- **Key format:** URL-safe base64, 44 chars from 32 cryptographic random bytes

### Rotation Configuration
- **Secret:** `life-platform/mcp-api-key` — 90-day auto-rotation enabled
- **Rotator ARN:** `arn:aws:lambda:us-west-2:205930651321:function:life-platform-key-rotator`
- **Permission:** `SecretsManagerInvoke` resource policy on rotator Lambda

### Bearer Token Cache TTL
- **`mcp/handler.py`:** `_BEARER_TOKEN_CACHE` now has 5-min TTL (was: forever)
- Ensures warm Lambda containers pick up new key within 5 min of rotation
- No redeployment needed after key rotation

### Helper Scripts
- `deploy/sync_bridge_key.sh` — updates `.config.json` after rotation for bridge transport
- `deploy/deploy_key_rotation.sh` — 6-phase deployment script

### Files
| File | Action |
|------|--------|
| `lambdas/key_rotator_lambda.py` | Created |
| `deploy/deploy_key_rotation.sh` | Created |
| `deploy/sync_bridge_key.sh` | Created |
| `mcp/handler.py` | Modified — Bearer cache TTL |

---

## v2.53.0 — 2026-03-01 — Buddy Accountability Page (buddy.averagejoematt.com)

### Buddy Page Infrastructure
- **URL:** `https://buddy.averagejoematt.com/` — accountability partner interface for Tom (Singapore)
- **CloudFront distribution:** `d1empeau04e0eg.cloudfront.net` (PriceClass_100, HTTP/2+3)
- **ACM certificate:** `arn:aws:acm:us-east-1:205930651321:certificate/cfaf8364-1353-48d3-8522-6892a5aef680`
- **Route 53:** A record alias `buddy.averagejoematt.com` → CloudFront
- **Lambda@Edge auth:** `life-platform-buddy-auth` (nodejs20.x, separate password from dashboard)
- **Secret:** `life-platform/buddy-auth` (us-east-1) — separate from dashboard auth
- **S3 bucket policy:** Added `BuddyPublicRead` statement for `buddy/*` path
- **Cost:** ~$0/month (CloudFront free tier)

### Buddy Page Design
- **Mobile-first, single-screen:** Dark mode (#0d0f14), Outfit font, warm personal aesthetic
- **Beacon system:** 🟢 Green / 🟡 Yellow / 🔴 Red — engagement-based, not metric-driven
- **4 status signals:** Food Logging, Exercise, Routine, Weight — each with colored dot + plain English
- **Activity highlights:** Last 4 workouts with friendly names, distance, duration
- **Food snapshot:** Weekly calorie/protein averages
- **Journey progress bar:** Days elapsed, lbs lost, % to goal (185 lbs)
- **Tom's prompt:** Contextual action guidance based on beacon state
- **Auto-refresh:** Every 30 minutes with cache-busting

### Beacon Logic (engagement-based, conservative)
- **Green (default):** Matthew is logging food, exercising, in routine
- **Yellow:** 1 red signal OR 2+ yellow signals — "might be a quiet stretch"
- **Red:** 2+ red signals — "check in on him"
- **Signal thresholds:** Food (3+ days dark = red), Exercise (7+ days = red), Routine (4+ days = red), Weight (8+ days no weigh-in = red)

### Daily Brief Lambda Integration
- **`write_buddy_json()`** added to daily_brief_lambda.py (before HANDLER section)
- Called after `write_clinical_json()` in lambda_handler (non-fatal, try/except wrapped)
- 7-day lookback using existing `fetch_range()` helper
- Queries: MacroFactor, Strava, Habitify, Withings from DynamoDB
- Writes `buddy/data.json` to S3 daily at 10:00 AM PT

### Files
- `lambdas/buddy/index.html` — buddy page frontend
- `lambdas/buddy/write_buddy_json.py` — data generator (reference copy)
- `deploy/deploy_buddy_page.sh` — 7-phase deployment script

---

## v2.52.0 — 2026-03-01 — Wednesday Chronicle Blog Launch + Dashboard Auth Fix

### Blog Infrastructure (blog.averagejoematt.com)
- **CloudFront distribution:** `E1JOC1V6E6DDYI` (`d1aufb59hb2r1q.cloudfront.net`)
- **ACM certificate:** `arn:aws:acm:us-east-1:205930651321:certificate/952ddf18-d073-4d04-a0b7-42c7f5150dc2`
- **Route 53:** A record alias `blog.averagejoematt.com` → CloudFront
- **Origin:** S3 website endpoint `/blog` path (public, no auth)
- **Content:** `blog/index.html`, `blog/week-00.html`, `blog/style.css`, `blog/about.html`
- **Prologue stored:** DynamoDB `USER#matthew#SOURCE#chronicle` partition (Week 0)
- **Cost:** ~$0.01/month (CloudFront free tier)

### Wednesday Chronicle Lambda v1.1 — Editorial Voice Overhaul
- **System prompt rewrite:** Added "EDITORIAL APPROACH" section explicitly requiring synthesis over day-by-day recounting
- **New section:** "METRICS AS TEXTURE, NOT STRUCTURE" — numbers illuminate narrative, not structure it
- **Editorial guidance:** Injected into every user message with anti-recap steering
- **Core principle:** Each installment needs a THESIS, not a timeline; data is evidence, not the story
- **Bio fix:** Age corrected to 37, added Brittany as girlfriend
- **What NOT to do:** Added "Don't walk through the week day by day — this is the cardinal sin"

### Blog Homepage Redesign
- **Hero layout:** Featured/latest installment with prominent title, excerpt, and clear CTA
- **Series intro:** One-paragraph hook below hero
- **Archive section:** Clean list with title, label (Prologue/Week N), and date
- **Lambda updated:** `build_blog_index()` generates new layout automatically for future weeks
- **Static version:** `blog/index.html` for immediate deploy

### Dashboard Auth Fix
- **Root cause:** CloudFront `AllowedMethods` was `[GET, HEAD]` only — POST to `/__auth` rejected at CloudFront level before Lambda@Edge executed
- **Fix:** Updated to full REST method set `[GET, HEAD, OPTIONS, PUT, POST, PATCH, DELETE]`
- **Distribution:** `EM5NPX6NJN095` (dash.averagejoematt.com)
- **Deploy:** `deploy/fix_cf_auth_methods.sh`

### Prologue Content Fix
- **Issue:** Prologue stated "thirty-five" and "lives alone" — should be "thirty-seven" and "lives with his girlfriend, Brittany"
- **Deploy:** `deploy/fix_prologue.sh` (downloads from S3, sed replace, re-uploads, invalidates cache)

### Deploy Scripts
- `deploy/fix_cf_auth_methods.sh` — CloudFront POST method fix
- `deploy/fix_prologue.sh` — Prologue age/bio correction
- `deploy/deploy_chronicle_v1.1.sh` — Lambda + homepage deploy

---

## v2.51.0 — 2026-02-28 — Weekly Nutrition Review Email

### Nutrition Review Lambda (#23)
- **New Lambda:** `nutrition-review` — Saturday 9:00 AM PT email with AI-powered nutrition analysis
- **Expert panel:** Layne Norton (macros/protein), Rhonda Patrick (micronutrients/genome), Peter Attia (metabolic/CGM)
- **Data sources:** MacroFactor food logs, Withings weight, Strava training, Apple Health CGM, Genome SNPs, DEXA, Supplements
- **AI model:** Sonnet 4.5 (temperature 0.3, 4096 tokens) — complex multi-source reasoning requires more than Haiku
- **Output:** Color-coded summary table + expert analysis cards + grocery list (Metropolitan Market) + meal ideas + supplement check
- **Trending:** Weekly summary stored to `nutrition_review` DynamoDB partition for week-over-week delta comparisons
- **Email design:** Dark theme, expert cards with colored borders (Norton=#10b981, Patrick=#8b5cf6, Attia=#f59e0b)
- **EventBridge rule:** `nutrition-review-saturday` (cron 0 17 ? * SAT *)
- **Deploy:** `deploy/deploy_nutrition_review.sh` (--test/--update modes)

### Design
- Comprehensive design doc: `design/nutrition-review-design.md`
- Genome × nutrition crossover analysis: vitamin D triple-unfavorable, FADS2 ALA conversion, choline triple risk, VKORC1 vitamin K

---

## v2.50.0 — 2026-02-28 — Ruck Logging + Workout Ingestion

### Ruck Logging (2 new MCP tools → 99 total)
- **`log_ruck`** — Tag a Strava Walk/Hike as a rucking session with weight. Auto-matches the activity by date (with time_hint or strava_id for disambiguation). Writes overlay to `ruck_log` partition with load weight, adjusted calorie estimate (Pandolf equation), load multiplier, distance, HR, elevation.
- **`get_ruck_log`** — Retrieve ruck history with session details, totals, weekly frequency, and load trends.
- **DynamoDB partition:** `USER#matthew#SOURCE#ruck_log` with `DATE#YYYY-MM-DD` keys, `rucks[]` list (same pattern as supplements)
- **SOT compliance:** Ruck data stored as overlay — does NOT modify Strava records
- **Calorie model:** Pandolf simplified — (bodyweight + load) / bodyweight × base walking kcal, with elevation bonus
- **Usage:** "I rucked this morning with 35lbs" → Claude calls `log_ruck` → matches walk → tags it

### Deploy
- `deploy/deploy_ruck_tools.sh` — MCP server repackage

---

## v2.49.0 — 2026-02-28 — Workout Ingestion (Pliability, Breathwrk)

### Health Auto Export Webhook v1.6.0
- **Workout processing:** HAE payloads with workouts were previously logged and dropped — now fully processed
- **Recovery classification:** Workouts classified by HealthKit type into recovery categories: Flexibility (Pliability), Mind and Body, Breathing (Breathwrk), Yoga, Pilates, Cooldown, Tai Chi
- **DynamoDB fields (apple_health partition):** `flexibility_minutes`, `flexibility_sessions`, `breathwork_minutes`, `breathwork_sessions`, `yoga_minutes`, `yoga_sessions`, `recovery_workout_minutes`, `recovery_workout_sessions`, `recovery_workout_types`
- **S3 storage:** Individual workouts stored to `raw/workouts/YYYY/MM/DD.json` with deduplication by workout ID
- **SOT compliance:** Non-recovery workouts (strength, running, cycling) stored to S3 but NOT aggregated to DynamoDB — Strava remains SOT for exercise
- **Breathwrk path:** `mindful_minutes` metric already mapped in webhook (Tier 1, sum) — configure HAE to export "Mindful Minutes" data type

### Backfill
- `backfill/backfill_workouts.py` — Replays existing HAE payloads to retroactively process dropped workouts

### Deploy
- `deploy/deploy_workout_ingestion.sh`

---

## v2.48.0 — 2026-02-28 — P0 Expert Review Fixes + Doc Sprint

### P0 Infrastructure Fixes
- **config.py:** Version `2.45.0` → `2.47.2`, added 4 missing SOURCES (weather, supplements, state_of_mind, habit_scores), added 5 missing SOT domains (water, caffeine, supplements, weather, state_of_mind)
- **Reserved concurrency:** Set MCP Lambda to 10 concurrent executions ($0, replaces $5/mo WAF)
- **Log retention:** Set 30-day retention on 9 log groups (dropbox-poll, eightsleep, garmin, habitify, health-auto-export-webhook, insight-email-parser, journal-enrichment, macrofactor, notion-journal, weather)
- **DLQ purge:** Cleared 5 stale messages from Feb 28 P0 outage

### Doc Sprint (8 documents updated)
All 8 stale documents brought current to v2.47.2+:
- **MCP_TOOL_CATALOG.md** (v2.41.0 → v2.48.0): 94 → 97 tools, added 3 habit intelligence tools (get_habit_registry, get_habit_tier_report, get_vice_streak_history), updated quick reference + dependency table
- **FEATURES.md** (v2.41.0 → v2.48.0): Daily Brief v2.5 → v2.6, added Habit Intelligence section, remote MCP, 21-module architecture, updated all stats
- **USER_GUIDE.md** (v2.41.0 → v2.48.0): 94 → 97 tools, added habit tier/registry/vice query examples, updated email/MCP references
- **RUNBOOK.md** (v2.43.0 → v2.48.0): Added deployment best practices (PIR learnings), Withings re-auth procedure, updated brief version
- **INCIDENT_LOG.md** (v2.33.0 → v2.48.0): Added Feb 28 P0 ingestion outage (most significant incident), updated DLQ coverage to 20/22, added duration alarm gap
- **COST_TRACKER.md** (v2.33.0 → v2.48.0): Updated to ~$6.50/month, added CloudFront line, reserved concurrency + WAF rejection, Google Calendar in planned features
- **DATA_DICTIONARY.md** (v2.33.0 → v2.48.0): Added 3 missing SOT domains (supplements, weather, state_of_mind), added 2 data gaps (SoM, supplements)
- **ARCHITECTURE.md** (v2.46.0 → v2.48.0): 94 → 97 tools, added remote MCP section, habit_scores DDB partition, daily brief v2.6

### Deploy script
- `deploy/deploy_p0_expert_review_fixes.sh` — all 4 P0 fixes with smoke test

---

## v2.47.2 — 2026-02-28 — Expert Review + Audit Framework

### Expert Review (8 phases)
Full platform review written to `docs/reviews/2026-02-28/` across 8 documents:
1. Architecture (A-), 2. Schema (A), 3. Security/IAM (B+), 4. Costing (A+), 5. Technical (A-), 6. Observability (B+), 7. Documentation (B-), 8. Board Review (A)

Key findings: 3 config.py bugs (stale version, incomplete SOURCES, missing SOT domains), 9 log groups without retention, MCP Lambda missing reserved concurrency, 8 of 13 docs stale.

### Audit Framework
- `audit/platform_snapshot.py` — Discovery-based data gatherer (AWS APIs + filesystem). Outputs structured JSON for Claude analysis. Self-expanding: new Lambdas, sources, alarms appear automatically.
- `docs/REVIEW_RUNBOOK.md` — Rules engine for weekly reviews. 25 rules across 6 sections (infrastructure, data completeness, config drift, cost, documentation, EventBridge). Differential analysis support.
- `deploy/SMOKE_TEST_TEMPLATE.sh` — Sourceable smoke test functions per PIR recommendation

Design principle: snapshot script gathers data (slow, automated), Claude applies judgment (fast, no tool calls). Weekly reviews become a 2-minute conversation.

---

## v2.47.1 — 2026-02-28 — P0 Ingestion Fix + Freshness Checker Update

### Root Cause
Hardening deployment (v2.43.0) caused 5 of 6 API ingestion Lambdas to fail at next scheduled run:
- **4 Lambdas** (strava, habitify, eightsleep, withings): Handler mismatch — zips contained `lambda_function.py` but handlers still pointed to `X_lambda.lambda_handler`
- **Garmin**: Missing `garth`/`garminconnect` dependencies (zip rebuilt without deps) + IAM missing `dynamodb:Query` (needed for gap-fill) + macOS `.so` files instead of Linux x86_64
- **Withings**: Cascading OAuth token expiry — handler mismatch prevented daily run, rotating refresh token expired

### Fixes Applied
- Handler fix: `lambda_function.lambda_handler` for strava, habitify, eightsleep, withings
- Garmin: Rebuilt zip with `--platform manylinux2014_x86_64`, added `dynamodb:Query` to IAM role
- Withings: Browser re-authorization via `setup/fix_withings_oauth.py` (new script with local callback server)
- Gap-fill self-healed all missing data once Lambdas restored

### Freshness Checker Update
- Removed Hevy (one-time backfill, not active source)
- Added garmin + habitify (were missing from monitored sources)
- Deployed to `life-platform-freshness-checker`

### Process Improvements (PIR)
- Full post-incident review: `docs/PIR-2026-02-28-ingestion-outage.md`
- Key changes going forward: mandatory post-deploy smoke test, handler consistency guard, cross-platform build enforcement, IAM co-location, deploy manifest

### Files
- `deploy/fix_garmin_deps.sh` — Garmin Lambda rebuild with Linux deps
- `setup/fix_withings_oauth.py` — Withings OAuth re-auth with browser flow
- `lambdas/freshness_checker_lambda.py` — Updated source list
- `docs/PIR-2026-02-28-ingestion-outage.md` — Full incident review

---

## v2.47.0 — 2026-02-28 — Habit Intelligence: 65-Habit Registry + Tier-Weighted Scoring

### Habit Registry (DynamoDB PROFILE#v1)
- 65 habits with full metadata: tier (0/1/2), category, scientific mechanism, personal context (`why_matthew`), synergy groups, applicable days, scoring weight
- Tier 0 (non-negotiable, 3x weight): 7 habits — the ones that cascade if missed
- Tier 1 (high priority, 1x weight): 22 habits — daily practice
- Tier 2 (aspirational, 0.5x weight): 36 habits — frequency targets
- Vice tracking: 5 vices with streak monitoring
- 8 synergy groups: Sleep Stack, Morning Routine, Recovery Stack, etc.
- Stored in `habit_registry` field on PROFILE#v1 record

### Daily Brief v2.5 → v2.6 (lambda v2.47.0, 3011 lines)
- Tier-weighted composite scoring replaces binary habit percentage
- Registry-aware streaks: per-vice streak tracking with 90-day lookback, `applicable_days` aware
- HTML display: T0 red/green per habit, T1 individual habits with 80%+ threshold, vice sub-section with 🔥 streak chips, T2 collapsed summary
- AI prompt enrichment: missed T0 habits by name + `why_matthew` context, synergy alerts (≥50% of ≥3-habit stack missing)
- Scorecard: "3/7 T0 · 18/22 T1" format
- Dashboard JSON: `habits_tier0`, `habits_tier1` fields added

### DynamoDB: habit_scores Partition (new)
- `USER#matthew#SOURCE#habit_scores`, `DATE#YYYY-MM-DD`
- Written daily by brief: tier0/tier1/vices pct, vice streaks map, synergy group completion, missed T0 list, composite score
- Enables historical trending without recomputing from raw Habitify data
- `scoring_method: tier_weighted_v1` marks transition point

### 3 New MCP Tools (tools_habits.py)
1. `get_habit_registry` — Inspect registry with tier/category/vice/synergy filters
2. `get_habit_tier_report` — Tier-level adherence trends from habit_scores partition
3. `get_vice_streak_history` — Vice streak time series with relapse detection

### Files
- `lambdas/daily_brief_lambda.py` — v2.47.0 (3011 lines, +389 lines)
- `mcp/tools_habits.py` — 3 new tools (+220 lines)
- `mcp/registry.py` — 3 new tool registrations (+90 lines)
- `deploy/deploy_daily_brief_v247.sh` — Deploy script

---

## v2.46.0 — 2026-02-28 — Resilient Gap-Aware Backfill Across All Ingestion Lambdas

### Gap-Aware Backfill Pattern (6 Lambdas)
Every API-based ingestion Lambda now self-heals data gaps automatically. On each scheduled run, the Lambda queries DynamoDB for the last 7 days, identifies missing dates, and fetches only those from the upstream API. Normal days with no gaps: 1 DynamoDB query, 0 extra API calls.

- **Garmin:** Already had gap-fill (v1.6.0) — no changes needed
- **Whoop:** New gap-fill with 3 modes (date override incl. `today` for recovery refresh, gap-aware lookback). Cleaned up duplicate helper functions. 0.5s call delay + 1s inter-day pacing
- **Eight Sleep:** New gap-fill with `_ensure_auth()` and `_ingest_with_retry()` helpers preserving 401 retry logic. 1s inter-day pacing
- **Strava:** Simplest change — widened default fetch window from 1 day to `LOOKBACK_DAYS` (7). API returns all activities in window; `put_item` upserts safely. No explicit gap detection needed
- **Withings:** New gap-fill with `_ingest_single_day()` helper. Gracefully handles no-weigh days (API returns empty). Fixed duplicate `compute_body_comp_deltas()` call. 0.5s inter-day pacing
- **Habitify:** New gap-fill preserving existing date-range backfill mode. 3 modes: range backfill, explicit date, gap-aware lookback. 0.5s inter-day pacing

### Shared Pattern
- `LOOKBACK_DAYS` env var (default 7) on all Lambdas — tunable without redeployment
- `find_missing_dates()` function: queries DynamoDB for DATE# records, diffs against expected dates
- Whoop-specific: filters out `#WORKOUT#` sub-items from gap detection (only counts base DATE# records)
- Self-bootstrapping: no seed data, no last-sync marker — existing records ARE the reference point
- Rate-limit pacing between gap-day API calls prevents upstream throttling

### Worst-Case API Impact (all 7 days missing)
- Whoop: 28 calls (4 endpoints × 7 days)
- Eight Sleep: 7 calls
- Strava: 1 call (date range)
- Withings: 7 calls (most return empty)
- Habitify: 7 calls

### Deploy
- `deploy/deploy_gap_fill.sh` — deploys all 5 modified Lambdas sequentially with 10s spacing
- `deploy/install_gap_fill.sh` — copies source files + runs deploy

---

## v2.45.0 — 2026-02-28 — Remote MCP Live: OAuth + Security + Function URL Fix

### OAuth Auto-Approve Flow
- Implemented minimal OAuth 2.1 flow to satisfy Claude's connector requirement (connector crashes without OAuth)
- `GET /.well-known/oauth-authorization-server` — RFC 8414 metadata discovery
- `GET /.well-known/oauth-protected-resource` — RFC 9728 resource metadata
- `POST /register` — Dynamic client registration (RFC 7591), returns `lp-{hex}` client_id
- `GET /authorize` — Auto-approve, generates auth code, 302 redirect to Claude callback
- `POST /token` — Returns HMAC-derived deterministic Bearer token (from API key in Secrets Manager)

### Bearer Token Security
- HMAC-SHA256 token derived from existing Secrets Manager API key + salt `life-platform-bearer-v1`
- All MCP endpoints (POST /, HEAD /) validate Bearer token — rejects requests without valid token
- OAuth discovery endpoints remain open (required for auth flow)
- Token cached in Lambda memory after first Secrets Manager lookup (no repeated lookups)
- Uses `hmac.compare_digest()` for timing-safe comparison
- Bridge transport unchanged — still uses x-api-key header

### Function URL Recreation
- Discovered Lambda "Block public access" feature (introduced late 2024) silently blocked all Function URL requests
- Old Function URL permanently broken from accumulated permission policy conflicts (4 duplicate statements)
- Deleted old URL, created fresh one: `c5hljblvma4u2xd6wf6oe4clk40unthu.lambda-url.us-west-2.on.aws`
- Added `lambda:InvokeFunction` for `*` to bypass public access block (required for NONE auth-type)
- Cleaned up stale permission policies — 3 clean statements remain (EventBridge, FunctionURL, PublicInvoke)

### Connector Status
- Claude.ai web connector: ✅ Connected and working
- Claude mobile app: ✅ Syncs automatically from web connector
- All 94 tools available (per-tool approval on first use)

### Files Modified
- `mcp/handler.py` — OAuth endpoints, HMAC Bearer token validation, `_get_bearer_token()`, `_validate_bearer()`
- `deploy/deploy_remote_mcp.sh` — Updated Function URL reference
- Lambda resource policy — cleaned up, 3 statements

---

## v2.44.0 — 2026-02-28 — Remote MCP Connector (Claude Mobile + Web)

### Remote Streamable HTTP Transport
- Added MCP Streamable HTTP transport (spec 2025-06-18) to Lambda handler
- Lambda Function URL now serves as remote MCP endpoint for claude.ai and Claude mobile app
- Three transport modes in single handler: Remote MCP (Function URL), Bridge (boto3 invoke), EventBridge (cache warmer)
- HEAD / → protocol version discovery, POST / → JSON-RPC, GET / → 405 (no SSE in Lambda)
- Protocol version negotiation: supports both 2025-06-18 (remote) and 2024-11-05 (legacy bridge)
- Added `ping` method handler for connection keepalive
- Authless for remote connector (Function URL is unguessable 40-char token)
- API key auth preserved for local bridge (backwards compatible)
- Function URL CORS updated: HEAD/GET/OPTIONS methods, MCP headers exposed

### Files Modified
- `mcp/handler.py` — refactored into remote/bridge dual transport + shared JSON-RPC processor
- `mcp/config.py` — version bump to 2.44.0
- Function URL CORS config — expanded methods and headers

---

## v2.43.0 — 2026-02-28 — Engineering Hardening: MCP Split + Lambda Parameterization + DLQ

### P2: MCP Monolith Split
- Split 14,960-line `mcp_server.py` into 21-module package (`mcp/handler.py`, `mcp/config.py`, `mcp/utils.py` + 18 domain modules)
- 100% tool validation: all 94 tools registered, zero import errors
- Cold start 727ms, warm calls 23-29ms
- `mcp_server.py` remains as Lambda entry point (thin wrapper)
- Centralized `__version__ = "2.43.0"` in `mcp/config.py`

### P2-P3: Lambda Source Parameterization
- **19 Lambda files** parameterized: `os.environ.get()` with backwards-compatible defaults for `REGION`, `S3_BUCKET`, `DYNAMODB_TABLE`, `USER_ID`
- All `USER#matthew` partition keys replaced with `f"USER#{USER_ID}"`
- Structured logging (`import logging`) added to all 19 files
- `freshness_checker_lambda.py` extracted from inline deploy script to proper source file
- `CACHE_PK` in `mcp/config.py` fixed to use `USER_ID` variable

### P3: DLQ Coverage Complete
- Added `sqs:SendMessage` policy to 3 IAM roles (weekly-digest, anomaly-detector, freshness-checker)
- DLQ configured on 5 previously-uncovered scheduled Lambdas (monthly-digest, anomaly-detector, daily-brief, freshness-checker, weekly-digest)
- **20/22 Lambdas now have DLQ** (MCP + HAE webhook excluded — request/response pattern)

### Bug Fix: Anomaly Detector
- Fixed pre-existing `ImportModuleError` on anomaly-detector (wrong zip entry filename in prior deploy)
- Anomaly detector v2.1.0 now operational with adaptive thresholds + travel awareness

### Deploy Infrastructure
- `deploy/deploy_unified.sh` — fixed freshness checker registry entry
- `deploy/deploy_hardening_v2.sh` — simplified hardening deploy with correct handler-to-filename mapping
- Documented handler-to-filename mapping for all 22 Lambdas in handover

---

## v2.42.0 — 2026-02-28 — Infrastructure Hardening: P0-P1 Expert Review Fixes

### P0: API Key Rotation (Critical Security Fix)
- Rotated MCP API key in Secrets Manager (old key invalidated)
- `mcp_bridge.py` now reads config from `.config.json` (gitignored) — zero hardcoded secrets
- `.config.json` stores api_key, function_name, region
- `.gitignore` updated: added `.config.json`, `*.bak*`

### P1: Environment Variable Parameterization
- **All 22 Lambdas** now have standardized env vars: `TABLE_NAME`, `S3_BUCKET`, `USER_ID`, plus service-specific vars (`SECRET_NAME`, `EMAIL_RECIPIENT`, `EMAIL_SENDER`, `ANTHROPIC_SECRET`)
- MCP server (`mcp_server.py`): replaced all hardcoded region, table, bucket, user prefix, secret name with `os.environ` reads (16 changes, 0 remaining hardcoded references)
- Daily Brief (`daily_brief_lambda.py`): same parameterization (15 changes)
- All config has backwards-compatible defaults — no breaking change if env vars missing
- New module-level constants: `USER_PREFIX`, `PROFILE_PK`, `TABLE_NAME`, `S3_BUCKET`, `USER_ID`

### P1: Runtime Standardization
- All 22 Lambdas upgraded to `python3.12` (4 were on python3.11)

### P1: Cleanup
- Removed 8 `.bak` files (~450KB dead weight)
- Removed stale `.zip` files from `lambdas/` and root
- `.gitignore` now blocks `*.bak*` files

### Patchers
- `patches/patch_parameterize_mcp.py` — idempotent MCP server parameterization
- `patches/patch_parameterize_daily_brief.py` — idempotent Daily Brief parameterization

### Deploy Script
- `deploy/deploy_p1_fixes.sh` — 6-phase deploy (patch local → env vars → runtimes → MCP deploy → brief deploy → cleanup)

---

## v2.41.0 — 2026-02-27 — Feature #25: State of Mind / How We Feel Integration

### Feature #25: State of Mind Ingestion
- **1 new MCP tool** (93↔94 total):
  - `get_state_of_mind_trend`: Valence trend from How We Feel / Apple Health State of Mind. Tracks mood check-ins (momentary emotions + daily moods) with valence (-1 to +1), emotion labels, life area associations. Shows overall trend, 7-day rolling avg, time-of-day patterns, best/worst days, top labels, valence by life area, classification distribution
- **Webhook Lambda v1.5.0**: State of Mind payload detection and ingestion
  - Detects HAE State of Mind payloads (separate Data Type automation, different shape than metrics)
  - Flexible parsing: handles multiple payload structures (top-level list, nested keys, etc.)
  - Individual check-ins stored in S3 `raw/state_of_mind/YYYY/MM/DD.json` with timestamp, kind, valence, labels, associations, source
  - Daily aggregates to DynamoDB: `som_avg_valence`, `som_min_valence`, `som_max_valence`, `som_check_in_count`, `som_mood_count`, `som_emotion_count`, `som_top_labels`, `som_top_associations`
  - Idempotent: deduplicates by timestamp on re-ingestion
- **Data flow**: How We Feel app → HealthKit State of Mind → Health Auto Export (REST API automation) → Lambda → DynamoDB + S3
- **Enables**: Pre-sleep mood → sleep quality correlation, mood → HRV/recovery correlation, time-of-day circadian mood patterns, life area impact analysis
- Requires second HAE automation with Data Type = "State of Mind" (same URL + auth as existing)

### Deploy Script
- `deploy/deploy_v2.41.0_state_of_mind.sh` — deploys webhook Lambda v1.5.0

---

## v2.40.0 — 2026-02-27 — Features #23 & #24: Travel Detection + Blood Pressure (Session 28)

### Feature #23: Travel & Jet Lag Detection
- **3 new MCP tools** (88→91→93 total):
  - `log_travel`: Start/end trips with destination, timezone, purpose. Auto-computes TZ offset and eastbound/westbound direction
  - `get_travel_log`: View all trips with status filter (active/completed)
  - `get_jet_lag_recovery`: Post-trip recovery analysis — compares 7-day pre-trip baseline to post-return recovery curve across 8 metrics (HRV, recovery, sleep, stress, Body Battery, steps). Days-to-baseline per metric with Board coaching (Huberman/Attia/Walker)
- **Anomaly Detector v2.1.0**: Travel-aware suppression. Checks travel partition before alerting — if traveling, still detects and records anomalies but suppresses alert email. Records tagged with `travel_mode=True` and `travel_destination`
- **Daily Brief v2.5.0**: Travel banner with jet lag protocol coaching (light exposure timing, melatonin window, meal timing) when active trip detected
- New DynamoDB partition: `USER#matthew#SOURCE#travel` with SK `TRIP#<slug>_<date>`

### Feature #24: Blood Pressure Home Monitoring
- **2 new MCP tools**:
  - `get_blood_pressure_dashboard`: AHA classification (normal/elevated/stage1/stage2/crisis), 30-day trend, morning vs evening patterns, variability analysis (SD >12 mmHg = independent CV risk factor)
  - `get_blood_pressure_correlation`: Pearson r for systolic/diastolic vs 11 lifestyle factors (sodium, caffeine, sleep, training, stress, weight, etc.). Exercise vs rest day comparison. Sodium dose-response buckets
- **Webhook Lambda v1.4.0**: Blood pressure metrics added to Tier 1 METRIC_MAP (systolic, diastolic, pulse). Individual readings stored in S3 `raw/blood_pressure/YYYY/MM/DD.json` for AM/PM analysis
- **Daily Brief**: BP tile with reading, AHA classification badge, and elevated-reading coaching
- **Anomaly Detector**: BP systolic/diastolic added to monitored metrics (15 metrics / 7 sources) with ±8/±5 mmHg minimum absolute change filters
- Ready to activate when BP cuff syncs to Apple Health. ASCVD risk profile update planned for when real BP data accumulates

### Deploy Script
- `deploy/deploy_v2.40.0_travel_bp.sh` — deploys all 4 Lambdas (MCP, anomaly detector, daily brief, webhook)

---

## Deployment — 2026-02-27 — Feature #21 Insight Email Pipeline Live (Session 27)

### Insight Email Pipeline — End-to-End Deployed
- Deployed `insight-email-parser` v1.1.0 Lambda with `ALLOWED_SENDERS=awsdev@mattsusername.com,mattsthrowaway@protonmail.com`
- Created SES receipt rule set `life-platform-inbound` with rule `insight-capture` for `insight@aws.mattsusername.com`
- DNS: Cloudflare MX record (`aws` → `inbound-smtp.us-west-2.amazonaws.com`) + TXT (`_amazonses.aws` → SES verification token)
- SES domain `aws.mattsusername.com` verified
- S3→Lambda notification `InboundEmailInsightParser` on `raw/inbound_email/` prefix
- End-to-end tested: email → SES → S3 → Lambda → DynamoDB ✅
- Confirmation reply limited by SES sandbox (non-issue for production Daily Brief reply flow)

### Deploy Scripts Used
- `deploy/deploy_insight_email_v1.1.sh` — Lambda code + env var
- `deploy/deploy_insight_email_pipeline.sh` — SES rules + S3 notification + DNS instructions

---

## v2.39.0 — 2026-02-27 — Feature #22 Web Dashboard Phase 2 (Session 24)

### Feature #22: Web Dashboard — Phase 2 (Clinical View + CloudFront)
- **Clinical Summary page** (`clinical.html`) — white-background, doctor-visit-ready report
  - 9 sections: Vitals, Body Composition (DEXA), Lab Results, Persistent Out-of-Range Flags, Supplements, Sleep (30d), Activity (30d), Glucose/CGM, Genetic Considerations
  - Lab biomarkers table with category grouping, flag badges (HIGH/LOW), reference ranges
  - Persistent flags section: chronic/recurring/occasional classification across all draws
  - Genome flags: unfavorable + mixed risk SNPs with gene, variant, category, clinical note
  - Print/PDF button with optimized print CSS (letter size, color-adjust, no-nav)
- **`write_clinical_json()`** added to Weekly Digest Lambda
  - Queries: labs (all draws), DEXA, genome, supplements (30d), sleep (30d), activity (30d), glucose (30d), Whoop vitals (30d), Withings weight, Apple Health steps
  - Writes `dashboard/clinical.json` to S3 weekly (after Sunday digest email)
  - Adds weight, steps, and metadata fields to JSON output
- **Navigation bar** added to both dashboard pages (Dashboard ↔ Clinical)
- **CloudFront distribution** + ACM certificate for HTTPS on custom domain
  - Domain: `dash.averagejoematt.com` (CNAME to CloudFront)
  - OriginPath `/dashboard` — clean URLs without `/dashboard/` prefix
  - ACM cert (us-east-1) with DNS validation via registrar CNAME
  - HTTP/2+3, redirect HTTP→HTTPS, PriceClass_100 (NA+EU)
  - Cost: ~$0/mo (free tier: 1TB transfer + 10M requests)

### Bug Fix
- `write_clinical_json()`: `_query_source_all()` and `_query_genome_all()` used boto3 `Key()` helper which isn't imported in weekly digest. Fixed to use raw string `KeyConditionExpression` matching existing patterns in the Lambda.

### Deploy Scripts
- `deploy/deploy_dashboard_phase2_code.sh` — S3 upload + Weekly Digest Lambda deploy (zips as `digest_handler.py` to match Lambda handler config)
- `deploy/deploy_dashboard_phase2_infra.sh` — ACM cert + CloudFront (2-phase with DNS validation wait)

### Infrastructure Created
- ACM certificate: `arn:aws:acm:us-east-1:205930651321:certificate/8e560416-e5f6-4f87-82a6-17b5e7df25d0`
- CloudFront distribution: `d14jnhrgfrte42.cloudfront.net`

### Docs Updated
- CHANGELOG.md, PROJECT_PLAN.md, ARCHITECTURE.md

---

## v2.38.0 — 2026-02-27 — Feature #22 Web Dashboard Phase 1 (Session 22)

### Feature #22: Web Dashboard — Phase 1 (Daily View)
- **Static HTML dashboard** served from S3 static website hosting
- Mobile-first, dark-mode, 6-tile design (Readiness, Sleep, Weight, Glucose, Training/TSB, Day Grade)
- 7-day sparklines for sleep score, HRV, weight, and glucose
- Zone 2 weekly progress bar toward 150 min target
- Component score bar chart in day grade card
- Auto-refreshes every 30 minutes
- Dashboard JSON generated at end of Daily Brief Lambda (non-fatal, wrapped in try/except)
- S3 public read restricted to `dashboard/*` prefix only
- IAM: added `dashboard-s3-write` inline policy to `lambda-weekly-digest-role`
- Design: DM Sans + JetBrains Mono, CSS-only sparklines via inline SVG, fadeUp animations
- Board of Directors + UI expert panel design session (Attia, Huberman, Ferriss, Rams, Zhuo, Tufte)

### Architecture
- Daily Brief Lambda writes `dashboard/data.json` to S3 after sending email
- S3 static website hosting enabled on `matthew-life-platform` bucket
- No new Lambda, no CloudFront (Phase 2), no auth (obscurity via URL)
- Cost: ~$0.01/month (S3 static hosting + a few GET requests)

### Files
- `lambdas/dashboard/index.html` — Static dashboard HTML (single file, zero dependencies)
- `lambdas/dashboard/data.json` — Sample data for local testing
- `deploy/deploy_dashboard_phase1.sh` — Full deploy script
- `tests/test_dashboard_local.sh` — Local dev server for visual verification

---

## v2.37.0 — 2026-02-27 — Features #12, #18, #21, #25 Deploy (Session 21)

### Feature #12: Social Connection Scoring — 2 new MCP tools
- `get_social_connection_trend` — Aggregates `enriched_social_quality` from journal entries with rolling 7d/30d averages, meaningful-connection streaks, PERMA model context, health correlations, meaningful-vs-low-social comparison
- `get_social_isolation_risk` — Flags ≥3 consecutive days without meaningful+ social connection, correlates isolation episodes with health metric declines, risk assessment, BoD coaching nudges
- No new Lambda or DynamoDB partition — reads existing enriched journal data

### Feature #18: Automated Threshold Learning — Anomaly Detector v2.0
- Adaptive Z thresholds via coefficient of variation (CV): low-CV→1.5 SD, medium→1.75 SD, high-CV→2.0 SD
- Day-of-week normalization for steps, tasks, habits (weekday vs weekend baselines)
- Minimum absolute change filters: weight ±1.5 lbs, steps ±2000, RHR ±3 bpm
- Updated metrics: chronicling→habitify, added Body Battery + Garmin Stress (13 metrics / 7 sources)
- Threshold transparency: cv, z_threshold, baseline_type, sample_size stored in anomaly records
- `detector_version: "2.0.0"` field, handler updated to `lambda_function.lambda_handler`

### Feature #21: Insight Email Parser — new Lambda + infrastructure
- New Lambda: `insight-email-parser` (128 MB, 30s, Python 3.12)
- IAM role: `lambda-insight-email-parser-role` (DynamoDB + S3 + SES + SQS DLQ)
- CloudWatch alarm: `insight-email-parser-errors`
- Reply to any Life Platform email → insight saved to `USER#matthew#SOURCE#insights` (source: "email")
- Reply text extraction, auto-tagging, confirmation email, ALLOWED_SENDERS security
- ⚠️ Requires DNS MX + SES Receipt Rule to activate (Lambda + IAM + alarm live)

### Feature #25: Meditation & Breathwork — webhook patch + 1 MCP tool
- `mindful_minutes` added to Health Auto Export webhook METRIC_MAP (Tier 1, sum)
- `get_meditation_correlation` — meditation-day vs non-meditation-day comparison, dose-response curves, next-day effects, adherence streaks, Huberman/Attia/Walker coaching context
- Compatible with Apple Mindfulness, Headspace, Calm, Insight Timer

**Totals:** 85 → 88 MCP tools | 21 → 22 Lambdas | 21 → 22 CloudWatch alarms

---

## v2.36.0 — 2026-02-26 — Features #9, #10, #11 Deploy (Session 20)

### Feature #9: Supplement & Medication Log — 3 new MCP tools
- `log_supplement` — Write supplement entries to DynamoDB (name, dose, unit, timing, category, notes)
- `get_supplement_log` — Read supplement history with per-supplement adherence tracking
- `get_supplement_correlation` — Compare days taking a supplement vs days without across recovery, sleep, HRV, glucose, stress
- Schema: PK `USER#matthew#SOURCE#supplements`, SK `DATE#YYYY-MM-DD`, nested `supplements` list
- Enhances N=1 experiment framework with supplement-specific tracking

### Feature #10: Weather & Seasonal Correlation — 1 new MCP tool
- `get_weather_correlation` — Fetches Seattle weather from Open-Meteo (free, no auth), caches in DynamoDB
- Correlates temperature, humidity, precipitation, daylight hours, sunshine, barometric pressure, UV index with health metrics and journal mood/energy
- Auto-caches weather data in `USER#matthew#SOURCE#weather` partition — first fetch populates, subsequent reads use cache
- Adds `import urllib.request` to MCP server for HTTP calls
- No new Lambda — weather fetched on-demand from MCP tool

### Feature #11: Training Periodization Planner — 1 new MCP tool
- `get_training_periodization` — Weekly training analysis: mesocycle phase detection (base/build/peak/deload), deload trigger (4+ weeks), training polarization (Seiler 80/20), progressive overload tracking, Zone 2 target adherence, consistency scoring
- Analyzes Strava activities (cardio) + MacroFactor workouts (strength volume)
- Board of Directors provides Galpin/Seiler/Attia training guidance

**Totals:** 80 → 85 MCP tools | No new Lambdas | 2 new DynamoDB sources (supplements, weather)

### Pipeline Integration — Weather Lambda + Daily Brief enhancements
- New Lambda: `weather-data-ingestion` — fetches Seattle weather from Open-Meteo daily at 5:45 AM PT, writes to `USER#matthew#SOURCE#weather`
- New IAM role: `lambda-weather-role` (DynamoDB write + S3 write + CloudWatch)
- New EventBridge rule: `weather-daily-ingestion` (cron 13:45 UTC)
- Daily Brief v2.4: added 💊 Supplements section (after habits, before CGM) — shows today’s logged supplements + 7-day adherence chips
- Daily Brief v2.4: added 🌤 Weather Context section (after gait, before weight phase) — shows temp, daylight, precip, pressure with coaching nudges
- Daily Brief now 17 sections (was 15)
- SCHEMA.md: documented `supplements` and `weather` source schemas
- ARCHITECTURE.md: added weather Lambda, updated tool counts, updated Daily Brief description
- Hotfix: moved 8 misplaced tool functions from after TOOLS dict to before it (fixed NameError crash on import)

**Totals:** 85 MCP tools | 21 Lambdas | 18 data sources | 20 EventBridge rules

---

## v2.35.0 — 2026-02-26 — Features #6, #7, #8 Deploy (Session 19)

### Feature #7: Readiness-Based Training Recommendation — 1 new MCP tool
- `get_training_recommendation` — Synthesizes Whoop recovery, Eight Sleep sleep quality, Garmin Body Battery, training load (CTL/ATL/TSB/ACWR), recent activity history, and muscle group recency
- Outputs: recommended workout type (Zone 2, intervals, strength upper/lower, active recovery, rest), intensity, duration, HR targets, target muscle groups
- Three readiness tiers (GREEN/YELLOW/RED) with composite scoring
- Warnings: injury risk (ACWR > 1.3), consecutive training days, sleep debt, HRV suppression
- Board of Directors provides rationale (Galpin, Huberman, Attia, Walker)
- Pure MCP tool — no pipeline changes

### Feature #8: Heart Rate Recovery Tracking — 1 new MCP tool + Strava Lambda enhancement
- `get_hr_recovery_trend` — Strongest exercise-derived mortality predictor (Cole et al., NEJM)
- Strava Lambda now fetches HR streams for activities with HR data (>= 10 min)
- Computes: peak HR (30s rolling), HR at peak+60s/120s, intra-activity recovery, cooldown detection
- Clinical thresholds: >25 excellent, 18-25 good, 12-18 average, <12 abnormal
- Trend analysis (first half vs second half), sport-type breakdown, cooldown vs no-cooldown comparison
- NOTE: HR recovery data populates going forward with new Strava ingestions

### Feature #6: Sleep Environment Optimization — 1 new MCP tool + Eight Sleep Lambda enhancement
- `get_sleep_environment_analysis` — Correlates bed temperature with sleep outcomes
- Eight Sleep Lambda now fetches from `/v2/users/{id}/intervals` for temperature data
- 4 extraction methods: top-level fields, timeseries, per-stage levels, sleepQualityScore
- Bucket analysis by bed temp (°F ranges) and Eight Sleep level (-10 to +10)
- Pearson correlations for temperature vs efficiency, deep %, REM %, HRV, onset latency
- Optimal temperature finder (best bucket with >= 3 nights)
- NOTE: Temperature data populates going forward with new Eight Sleep ingestions

**Totals:** 77 → 80 MCP tools | Strava Lambda + Eight Sleep Lambda updated

---

## v2.34.0 — 2026-02-26 — Triple Feature Deploy (Session 18)

### Package 1: Strava Ingestion Dedup (#4 on roadmap)
- Added `dedup_activities()` to Strava ingestion Lambda
- Same overlap logic as daily brief: same sport_type + start within 15 min → keep richer record
- All downstream MCP tools now get clean data (training load, Zone 2, exercise-sleep correlation)
- Eliminates double-counted activities at source

### Package 2: N=1 Experiment Framework (#5 on roadmap) — 4 new MCP tools
- `create_experiment` — Start tracking a protocol change with hypothesis
- `list_experiments` — View active/completed/abandoned experiments
- `get_experiment_results` — Auto-compare before vs during across 16 health metrics
- `end_experiment` — Close experiment with outcome notes
- Schema: PK USER#matthew#SOURCE#experiments, SK EXP#<slug>_<date>
- Board of Directors evaluates each experiment result against hypothesis
- Minimum 14-day data threshold warning (Huberman/Attia consensus)

### Package 3: Health Trajectory Projections (#3 on roadmap) — 1 new MCP tool
- `get_health_trajectory` — Forward-looking intelligence across 5 domains:
  - Weight: rate of loss, phase milestones, projected goal date
  - Biomarkers: lab trend slopes, 6-month projections, threshold warnings
  - Fitness: Zone 2 trend, training consistency %, volume direction
  - Recovery: HRV trend, RHR trend, sleep efficiency trend
  - Metabolic: mean glucose trend, time-in-range from CGM
- Board of Directors longevity assessment with positives/concerns summary

### Platform Stats
- 77 MCP tools (was 72, +5 new)
- 3 North Star gaps addressed: "No did-it-work loop" (#5), "No forward-looking intelligence" (#3), Strava dedup (#4)
- Strava Lambda updated with ingestion-time dedup

---

## Docs & Reorg — 2026-02-26 — Documentation Audit + Folder Reorganization (Session 17)

No code changes. Housekeeping session.

### Tool Count Fix
- Discovered 72 actual tools (was documenting 61). Swept 6 docs + memory.

### Five New Reference Documents
- FEATURES.md — Non-technical + technical feature showcase
- MCP_TOOL_CATALOG.md — All 72 tools with params, cache, dependencies
- DATA_DICTIONARY.md — SOT domains, metric overlap, webhook filtering, known gaps
- INCIDENT_LOG.md — 13 incidents (P1-P4) with root cause and resolution
- COST_TRACKER.md — ~$6/mo breakdown, budget guardrails, cost decisions

### Folder Reorganization
- ~170 flat files → categorized into lambdas/, deploy/, backfill/, patches/, seeds/, setup/, tests/
- All .md files → docs/
- All drop folders → datadrops/ (moved from parent ~/Documents/Claude/)
- Updated ingest automation paths (process_all_drops.sh + launchd plist)

### 25-Item Feature Roadmap
- Expanded from 7 to 25 items across 4 tiers
- Cost flags: WAF (+$5/mo), Web dashboard (+$2-5/mo)
- 3 new North Star gaps identified

---

## v2.33.0 — 2026-02-26 — MCP Latency Fix + Expanded Cache Warmer (Session 16)

### Critical Hotfix
- **MCP server was broken since v2.31.0 deploy** — every invocation failing with `NameError: tool_get_day_type_analysis not defined`
- Root cause: 3 tool functions + `_load_cgm_readings` helper defined AFTER the TOOLS dict that references them at module load
- Fix: Moved block (lines 9765-10549) before TOOLS dict; all 72 tool references verified

### Memory Optimization
- Lambda memory: 512 MB → 1024 MB (CPU scales linearly)
- Heavy analytics queries (3-6s at 512 MB) should halve in duration
- Eliminates GC pressure on mega-queries that were hitting 245-273 MB

### Additional Fix: `get_table()` NameError
- 5 functions referenced undefined `get_table()` instead of module-level `table`
- Affected: `nutrition_summary`, `macro_targets`, `food_log`, `day_type_analysis`, `fasting_glucose_validation`
- Fix: Removed redundant local reassignment; module-level `table` (line 102) is correct

### Expanded Cache Warmer (6 → 12 tools)
- **6 new tools pre-computed nightly**, with inline cache-get for instant reads:
  - `readiness_score` — 4 DDB queries → <100ms on cache hit
  - `health_risk_profile` — 3 DDB queries → <100ms
  - `body_composition_snapshot` — 3 DDB queries → <100ms
  - `energy_balance` — parallel query → <100ms
  - `day_type_analysis` — 2 parallel queries → <100ms
  - `movement_score` — 2 parallel queries → <100ms
- Cache keys are date-stamped; stale data auto-expires
- Custom date ranges bypass cache, compute fresh
- `_skip_cache` flag for warmer to force fresh computation
- Warmer measured runtime: 7.0s for all 12 tools (well within 300s timeout)

### Platform Stats
- 61 MCP tools, 12 pre-cached nightly (was 6)
- Lambda: 1024 MB (was 512 MB)
- Monthly cost impact: ~+$1

---

## v2.32.0 — 2026-02-26 — Fasting Glucose Validation (Session 15)

### New MCP Tool: get_fasting_glucose_validation (#61)
- Computes proper overnight nadir (00:00-06:00) from raw S3 CGM readings
- Deep nadir window (02:00-05:00) avoids late digestion and dawn phenomenon
- Distribution stats: mean, median, p10-p90, std dev across ~139 CGM days
- Statistical validation: z-scores and percentiles of lab values vs CGM distribution
- Direct same-day validation ready for future overlapping CGM + lab draws
- Bias analysis with confidence level (high/moderate/low/very_low)
- Compares three proxies: overnight nadir, deep nadir, daily minimum (current)
- Board of Directors insights (Attia, Patrick, Huberman)
- Finding: No same-day CGM + lab overlap exists yet — statistical comparison only

### Platform Stats
- 61 MCP tools (was 60)
- CGM coverage: 2024-09-08 → 2025-01-25 (~139 days)
- Lab draws with fasting glucose: 6 (2019-2025)

---

## v2.31.0 — 2026-02-26 — Derived Metrics Phase 1f + Phase 2 Complete (Session 14)

### Phase 1f: ASCVD 10-Year Risk Score (Labs)
- Implemented Pooled Cohort Equations (2013 ACC/AHA) for all 4 race/sex cohorts
- Patched 2 labs records with `ascvd_risk_10yr_pct`, `ascvd_risk_category`, `ascvd_inputs`, `ascvd_caveats`
- Draw 1 (2025-04-08): skipped — no total cholesterol or HDL on this draw
- Draw 2 (2025-04-17): computed with TC 219, HDL 72, SBP 125 (estimated)
- Age-extrapolation caveat: PCE validated 40-79, Matthew was 36 at draw
- SBP uses estimate (125 mmHg) — flagged for update when BP monitor data available
- ASCVD now surfaces in `get_health_risk_profile` cardiovascular domain

### Phase 2c: Day Type Classification + Analysis Tool
- New utility: `classify_day_type()` — classifies days as rest/light/moderate/hard/race
- Classification priority: Whoop strain > computed load score > Strava distance/time
- Thresholds: rest (<4 strain), light (4-8), moderate (8-14), hard (14+)
- New MCP tool: `get_day_type_analysis` — segments sleep, recovery, nutrition by day type
- Batch-fetches MacroFactor data (optimized vs per-day queries)
- Auto-generates insights: HRV impact, caloric adjustment, sleep debt patterns

### Phase 2 Completion Notes
- Phase 2a (ACWR): Already implemented in `get_training_load` ✅
- Phase 2b (fiber_per_1000kcal): Already implemented in `get_nutrition_summary` ✅
- Phase 2d (strength_to_bw_ratio): Already implemented in `get_strength_standards` ✅
- Pattern A complete (6/6 metrics), Pattern B complete (4/4 metrics)

### Platform Stats
- 60 MCP tools (was 59)
- All Pattern A + Pattern B derived metrics deployed

---

## v2.30.0 — 2026-02-26 — Derived Metrics Phase 1c-1e (Session 13)

### Phase 1c: CGM Time-in-Optimal (Apple Health webhook)
- Patched `health_auto_export_lambda.py` with Attia optimal range (70–120 mg/dL)
- New field: `blood_glucose_time_in_optimal_pct` — stricter than standard 70–180 `time_in_range_pct`
- Backfilled ~139 days of historical CGM data from S3 raw readings

### Phase 1d: Protein Distribution Score (MacroFactor)
- Patched `macrofactor_lambda.py` with meal grouping + MPS threshold scoring
- Groups food_log entries into meals by 30-min time proximity
- Eating occasions <400 kcal excluded as snacks (prevents banana = failed meal)
- New fields: `protein_distribution_score`, `meals_above_30g_protein`, `total_meals`, `total_snacks`
- Constants: `MEAL_CALORIE_THRESHOLD = 400`, `PROTEIN_MPS_THRESHOLD = 30`
- Backfilled all historical MacroFactor records

### Phase 1e: Micronutrient Sufficiency (MacroFactor)
- Patched `macrofactor_lambda.py` with Board of Directors consensus targets
- 5 nutrients: Fiber (38g), Potassium (3400mg), Magnesium (420mg), Vitamin D (100mcg/4000 IU), Omega-3 (3g)
- New fields: `micronutrient_sufficiency` (nested map with actual/target/pct), `micronutrient_avg_pct`
- Each nutrient capped at 100% — exceeding target still scores 100
- Backfilled all historical MacroFactor records

### Documentation
- SCHEMA.md updated with all new derived fields

---

## v2.29.0 — 2026-02-26 — Derived Metrics Phase 1a-1b (Session 12)

### Board of Directors Schema Review
- Convened full expert panel (Huberman, Attia, Patrick, Galpin, Norton, Ferriss, MD) to review data model
- Identified 22 potential derived metrics, selected 16 for implementation
- Architecture decision: 9 stored at ingestion, 4 compute-on-read, 4 nightly batch
- Created `DERIVED_METRICS_PLAN.md` — 6-session roadmap (~18 hr)

### Phase 1a: Sleep Onset Consistency (Whoop)
- Patched `whoop_lambda.py` with sleep onset tracking
- New fields: `sleep_onset_minutes` (minutes from midnight UTC), `sleep_onset_consistency_7d` (7-day rolling StdDev)
- Clinical thresholds: <30 min excellent, 30-60 fair, >60 poor (social jetlag territory)
- Backfilled 1,816 historical records from S3 raw sleep files
- Also backfilled `sleep_start` to DynamoDB for records missing it (Phase 3 field gap)

### Phase 1b: Body Composition Deltas (Withings)
- Patched `withings_lambda.py` with 14-day rolling deltas
- New fields: `lean_mass_delta_14d`, `fat_mass_delta_14d` (lbs change vs ~14 days ago)
- Key coaching insight: during a cut, `lean_mass_delta_14d ≥ 0` = muscle preserved
- Backfilled all historical Withings records

### Audit Verification
- Confirmed anomaly detector first automated run (8:05 AM, Feb 26) — 0 anomalies, record written
- Confirmed Daily Brief SES scoping working (Feb 25 + Feb 26 briefs sent successfully)
- Notion Lambda: 16 blank pages correctly skipped (no journal entries created yet)

### Documentation
- `macrofactor_workouts` partition (422 items) documented in SCHEMA.md
- `DERIVED_METRICS_PLAN.md` created with full implementation roadmap

---

## v2.28.1 — 2026-02-25 — Audit Fixes + ARCHITECTURE.md Overhaul (Session 11)

### Critical Fixes
- **Anomaly detector EventBridge trigger** — Created `anomaly-detector-daily` rule: `cron(5 16 * * ? *)` (8:05 AM PT). Lambda existed but was never invoked on schedule. Anomaly data now flows to daily brief.
- **Enrichment alarm dimension fix** — `ingestion-error-enrichment` alarm was watching `activity-enrichment-nightly` (EventBridge rule name) instead of `activity-enrichment` (Lambda name). Deleted and recreated with correct dimension.

### Security Fixes
- **MCP role**: Removed `dynamodb:Scan` from `lambda-mcp-server-role` (GetItem + Query + PutItem retained)
- **SES scoping**: Changed `Resource: "*"` → `arn:aws:ses:us-west-2:205930651321:identity/mattsusername.com` on `lambda-weekly-digest-role` (shared by daily-brief, weekly-digest, monthly-digest) and `lambda-anomaly-detector-role`
- **DLQ coverage**: Added DLQ (`life-platform-ingestion-dlq`) to 6 Lambdas: garmin, habitify, notion, dropbox-poll, activity-enrichment, journal-enrichment. Added `sqs:SendMessage` to each role. Coverage: 5/20 → 11/20.

### Anomaly Detector Code Redeploy
- Redeployed `anomaly_detector_lambda.zip` after `update-function-configuration` caused `ImportModuleError`. Lambda now runs against current date.

### ARCHITECTURE.md Overhaul
Complete rewrite against AWS ground truth. 19 inaccuracies corrected:
- MCP endpoint: "API Gateway" → Lambda Function URL (AuthType NONE)
- MCP tools: 52/58 → 59
- Garmin schedule: 9:30 AM → 6:00 AM PT
- Daily brief schedule: 8:15 AM → 10:00 AM PT
- Cache warmer: "03:00 UTC" → 9:00 AM PT (17:00 UTC)
- Weekly digest: 8:30 AM → 8:00 AM PT
- Monthly digest: "1st Sunday" → 1st Monday
- IAM section: reconciled MCP PutItem (cache warmer) with "no writes" claim
- Composite alarm: removed (doesn't exist)
- Alarm count: "7 individual" → 21
- Alarm window: "15 minutes" → 24 hours
- Secrets: 6 → 12 (added full secret inventory table)
- DLQ coverage: "all ingestion Lambdas" → 11/20 with specifics
- Added freshness-checker Lambda (was missing entirely)
- Added email Lambda role sharing note (3 Lambdas share weekly-digest role)
- Added MacroFactor dual trigger (EventBridge + S3)
- Added DST warning on all schedules
- Added Secrets Manager section with per-secret inventory
- Separated ingestion vs operational Lambda schedule tables
- Accuracy: ~70% → ~100%

### RUNBOOK.md Refresh
- Version header: v2.22.0 → v2.28.1
- Weekly Digest: 8:30 AM → 8:00 AM, Monthly: 1st Sunday → 1st Monday
- MacroFactor: S3 trigger → EventBridge + S3 trigger
- Daily Brief: v2.2 → v2.3 (15 sections)
- MCP failure section: API Gateway → Lambda Function URL
- Log retention: 90 days → 30 days
- Anomaly detector role: corrected to show anthropic secret access
- MacroFactor S3 path: imports/ → uploads/
- Added DST warning on schedule table

### USER_GUIDE.md Rewrite
- Version header: v2.22.0 → v2.28.1, tool count: 58 → 59
- Tool reference: v2.8.0 / 45 tools → current / 59 tools (14 new tool categories)
- Added: CGM (4 tools), Gait & Mobility (3), Journal (5), Labs & Genome (8), Sleep correlations (3)
- Email layer: all schedules corrected (Daily Brief 8:15→10:00, Weekly 8:30→8:00, Monthly 1st Sun→1st Mon)
- Data sources: added Notion Journal, Health Auto Export, Labs, DEXA, Genome
- Apple Health: OneDrive → webhook (primary) + S3 XML (backfill)
- MacroFactor: OneDrive → Dropbox pipeline
- Garmin schedule: 9:30 AM → 6:00 AM
- Infrastructure table: 45 tools → 59, added freshness checker, enrichment Lambdas, alarm count
- MCP references: API Gateway → Lambda Function URL throughout

### Files
- `deploy_audit_fixes_phase1_2.sh`, `deploy_audit_fix5_dlq.sh`

---

## Audit — 2026-02-25 — Full Infrastructure Audit (Session 10)

### 6-Part Infrastructure Review
- Audited all 20 Lambdas, 18 IAM roles, 18 EventBridge rules, 21 CloudWatch alarms, S3, DynamoDB, API endpoints, SES, SNS, Secrets Manager, Budgets
- **31 findings** total: 2 critical, 12 medium, 10 low, 7 info
- Critical: anomaly detector has no EventBridge trigger (never runs); enrichment alarm watches nonexistent function name
- Medium: MCP role has Scan (docs say no), SES Resource:* on 2 roles, 6 Lambdas missing DLQ, MCP uses Function URL not API Gateway (doc wrong), habitify alarm firing
- ARCHITECTURE.md accuracy: ~70%. RUNBOOK.md accuracy: ~93%
- No code changes — audit only, fix plan generated with CLI commands
- Reports: audit-part1 through audit-part6 in claude.ai outputs
- Monthly cost: ~$5/month ($0.63 MTD) against $20 budget

---

## v2.28.0 — 2026-02-25 — Anomaly Detector Gait + Caffeine Tracking

### Anomaly Detector v1.1.0
- Added `walking_speed_mph` (low is bad — strongest mortality predictor)
- Added `walking_asymmetry_pct` (high is bad — injury indicator)
- Metrics: 9 → 11
- Needs 7+ days gait baseline before flagging

### Caffeine Tracking
- Added `caffeine_mg` (Tier 1, sum) to Health Auto Export webhook
- SOT for caffeine: Apple Health via water/caffeine tracking app
- Field: `Dietary Caffeine` / `dietary_caffeine` → `caffeine_mg`

### Files
- `patch_anomaly_gait.py` + `deploy_anomaly_gait.sh`
- `patch_caffeine.py` + `deploy_caffeine.sh`

---

## v2.27.0 — 2026-02-25 — Daily Brief v2.3 (CGM + Gait)

### Daily Brief v2.3.0 — 15 sections
- **CGM Spotlight enhanced:** Overnight Low (fasting proxy), hypo flag (⚠️ below 70), 7-day trend arrow (▲▼—), 7-day avg in extras
- **New section: Gait & Mobility** — walking speed (mph, clinical flag <2.24), step length (in), asymmetry (%, injury flag ≥5%), double support (%, fall risk)
- 7-day `apple_health` fetch added to `gather_daily_data()` for CGM trend context
- `data_summary`: +`glucose_min`, +`walking_speed_mph`, +`walking_step_length_in`, +`walking_asymmetry_pct`
- AI prompt: gait data + overnight glucose low for smarter guidance
- Sections: 14 → 15

### Files
- `patch_daily_brief_v23.py` — Patcher (supports both `lambda_function.py` and `daily_brief_lambda.py`)
- `deploy_daily_brief_v23.sh` — Deploy script

---

## v2.26.0 — 2026-02-25 — Glucose Meal Response Tool

### New MCP Tool: `get_glucose_meal_response` (Tool #59)
- **Levels-style postprandial spike analysis**: MacroFactor food_log × S3 CGM 5-min readings
- Meals grouped by 30-min timestamp proximity
- Per meal: pre-meal baseline → peak → spike → time-to-peak → AUC → return-to-baseline → letter grade (A-F)
- Aggregates: best/worst meals, per-food scores, macro correlations (carbs/fiber/protein/sugar vs spike), fiber-to-carb ratio analysis
- Scoring: A (<15 spike), B (15-30), C (30-40), D (40-50), F (>50 mg/dL)
- S3 client + `_load_cgm_readings()` helper added to MCP server
- IAM: `s3:GetObject` added to `lambda-mcp-server-role` for `raw/cgm_readings/*`
- MCP server version bumped to v2.26.0
- **Data note:** CGM restarted Feb 24, 2026. Tool will produce results once CGM + food_log overlap accumulates (~1 week for correlations).

### Files
- `patch_glucose_meal_response.py` — Patcher script
- `deploy_glucose_meal_response.sh` — Deploy with IAM update

---

## v2.25.0 — 2026-02-25 — API Gap Closure Deploy

### Phase 1: Garmin Sleep Expansion (v1.5.0)
- `extract_sleep`: 2 → 18 fields (stages, timing, SpO2, respiration, restless moments, sub-scores)
- `extract_activities`: +5 fields (avg_hr, max_hr, calories, avg/max speed)
- Garmin becomes complete second sleep source alongside Eight Sleep
- **Note:** Sleep fields returning empty — Garmin device not recording sleep despite schedule set. Battery Saver mode suspected. Debug logging added. Pending device-side fix.

### Phase 2: Strava HR Zones
- Per-activity HR zone distribution via `GET /activities/{id}/zones`
- `hr_zone_seconds`, `zone2_seconds`, `zone_boundaries` per activity
- Day-level `total_zone2_seconds` aggregation
- **Note:** Returns HTTP 402 (requires Strava Summit subscription). Code gracefully returns empty zones. Schema preserved for future.

### Phase 3: Whoop Sleep Timing + Naps
- `sleep_start`, `sleep_end` ISO timestamps — **confirmed live** ✅
- `nap_count`, `nap_duration_hours` from nap=True records
- Summary builder updated to handle string fields

### Files
- `garmin_lambda.py` — v1.5.0 (patched via `patch_garmin_phase1.py`)
- `strava_lambda.py` — Phase 2 (patched via `patch_strava_phase2.py`)
- `whoop_lambda.py` — Phase 3 (patched via `patch_whoop_phase3.py`)

---

## v2.24.0 — 2026-02-25 — Weekly Digest v4.2 (Complete Rewrite)

### Major Rewrite
- **Weekly Digest v4.0→4.2**: Complete rewrite of `weekly-digest` Lambda from v3.3.0.
- **Day grade integration**: Weekly trend bar chart, average score + letter grade with W-o-W delta, grade distribution chips, 4-week trend arrow.
- **Profile-driven everything**: All targets from `PROFILE#v1` — calories, protein, sleep, steps, water, goal weight, max HR. Zone 2 HR range computed from profile `max_heart_rate`.
- **Batch query architecture**: ~11 batch `query` calls for 4 weeks of data (was ~100+ individual `get_item` calls).
- **Data source migrations**: Habits (Chronicling → Habitify), Strength (Hevy → MacroFactor workouts), CGM/Gait/Steps (Apple Health).
- **Strava dedup**: `dedup_activities()` from daily brief v2.22.2 applied to prevent multi-device duplicates.
- **8-component scorecard**: Matches daily brief (sleep, recovery, nutrition, movement, habits, water, journal, glucose).

### Journey Assessment (v4.1)
- **New section 16**: 12-week trajectory assessment as final content section.
- **Second Haiku call** with `JOURNEY_PROMPT` — trajectory assessment, structural gap, next-week focus, momentum check.
- **Journey context**: 12-week day grade weekly averages, weight trajectory, HRV trend, nutrition logging consistency.
- **Green-themed styling** distinct from blue Board of Advisors section.

### Board Review Fixes (v4.2)
- **Steps bug fixed**: `steps_avg` + `steps_total` extracted but never rendered — now visible in Steps, CGM & Mobility section.
- **Chair deconflicted**: Chair gives weekly verdict only (biggest win + miss); Journey Assessment owns forward-looking recommendations.
- **Journey context enriched**: Added 12-week `weekly_hrvs` and `weekly_nutrition` (days logged, cal avg, protein avg).
- **Alcohol surfaced**: Extracted from MacroFactor `total_alcohol_g`, displayed as standard drinks with color coding in Nutrition.
- **Insight repositioned**: Insight of the Week now appears right after scorecard; open insights moved below Board.
- **Board prompt hardened**: Added insufficient-data rule (<3 days → acknowledge) and cross-reference rule (cite other advisors).
- **Section renamed**: "CGM & Mobility" → "Steps, CGM & Mobility".

### Files
- `weekly_digest_v2_lambda.py` — v4.2.0 (1,200+ lines)
- `deploy_weekly_digest_v2.sh` — Deployment script (handler filename fixed: `digest_handler.py`)

---

## v2.23.0 — 2026-02-25 — Day Grade Retrocompute

### New Feature
- **Historical day grades**: Backfilled 947 day grades from 2023-07-23 → 2026-02-24 using algo v1.1.
- **Batch-query architecture**: 8 source queries + 1 journal query upfront, indexed in memory. Processed 948 dates in 4.3s query + 24.5s writes (39 writes/sec), zero errors.
- **Scoring parity**: All 8 component scorers copied verbatim from `daily_brief_lambda.py` v2.2.3 — identical results to daily brief.
- **Strava dedup applied**: Same `dedup_activities()` logic from v2.22.2 applied per-day during retrocompute.
- **Chronicling fallback**: `score_habits_mvp` falls back to Chronicling data for pre-Habitify era.
- **`source: "retrocompute"` tag**: Every backfilled record tagged to distinguish from daily-brief-computed grades.
- **Skip-existing mode**: Default skips dates with existing grades; `--force` flag to overwrite.
- **Profile fix**: Updated `day_grade_algorithm_version` from "1.0" → "1.1" in profile to match actual algo.

### Results
- **947 grades computed**, avg score **66.9 (C+)**
- Grade distribution: A-range 23.5%, B-range 24.9%, C-range 20.3%, D 19.3%, F 11.9%
- Component coverage: movement 100%, sleep 91.9%, recovery 36.2%, glucose 14.6%, nutrition 9.6%, habits 1.8%
- Early days (2023-2024) mostly 2-3 components (sleep + movement ± recovery); recent days richer

### Files
- `retrocompute_day_grades.py` — standalone backfill script (dry run / stats / write / force modes)

### Unblocks
- Weekly Digest v2 grade trending (PROJECT_PLAN #2)
- MCP tools for grade history queries

---

## v2.22.3 — 2026-02-25 — Demo Mode for Sharing

### New Feature
- **Demo mode**: Invoke with `{"demo_mode": true}` to get a sanitized version of the daily brief safe to share with coworkers and friends.
- **Profile-driven rules** (`demo_mode_rules` in DynamoDB) — update anytime without deploy:
  - `redact_patterns`: Words replaced with "[redacted]" (marijuana, alcohol, etc.)
  - `replace_values`: Numeric fields masked (weight → "•••", calories → "•,•••")
  - `hide_sections`: Entire sections stripped (journal_pulse, journal_coach, weight_phase)
  - `subject_prefix`: Email subject prefixed with "[DEMO]"
- **Section markers**: HTML comment markers (`<!-- S:name -->`) added to 13 sections in build_html.
- **Demo banner**: Yellow "DEMO VERSION" banner at top of sanitized email.
- **Safety**: Demo mode skips `store_day_grade()` to avoid overwriting real data.
- **Files**: `patch_demo_mode.py`, `seed_demo_mode_rules.py`, `deploy_daily_brief_v223.sh`

---

## v2.22.2 — 2026-02-25 — Strava Activity Deduplication

### Bug Fix
- **Multi-device dedup**: WHOOP + Garmin recording the same walk → duplicate in Training Report and inflated movement score. Added `dedup_activities()` that detects overlapping activities (same sport_type, start times within 15 min) and keeps the richer record (prefers GPS/distance, then longer duration).
- **Scoring fix**: Recomputes `activity_count` and `total_moving_time_seconds` from deduped list so movement score isn't inflated.
- **Scope**: Runs in daily brief only. Strava ingestion-level dedup tracked as future work.
- **Example**: Feb 24 "Afternoon Walk" — kept Garmin (33 min, 1.7 mi, GPS), dropped WHOOP (19 min, no GPS).
- **Files**: `patch_activity_dedup.py`, `deploy_daily_brief_v222.sh`

---

## v2.22.1 — 2026-02-25 — Day Grade Zero-Score Fix

### Bug Fix
- **score_journal**: Returns `None` (excluded from grade) when no journal entries exist. Previously returned `0`, always dragging grade down.
- **score_hydration**: Added 118ml (4oz) minimum threshold. Below this is Apple Health food-content noise, not intentional water tracking. Returns `None` (excluded).
- **Algorithm version**: 1.0 → 1.1 (for retrocompute tracking).
- **Impact**: Feb 24 grade went from 69 (C+) → ~77 (B). Journal (0.05 weight) and hydration (0.05 weight) no longer penalize the grade when data is missing or noise.
- **Scorecard**: `sc_cell` already handles `None` gracefully — shows "—" in gray.
- **Files**: `patch_day_grade_zero_score.py`, `deploy_daily_brief_v221.sh`

---

## v2.22.0 — 2026-02-25 — Daily Brief v2.2 (AI Guidance, Training Workouts, TL;DR)

### Daily Brief v2.2 Features
- **MacroFactor Workouts → Training Report**: Exercise-level data (sets/reps/weight/RIR) from macrofactor_workouts integrated into training AI prompt. Supports strength, cardio, and mixed workout types.
- **Today's Guidance → AI-generated**: New `call_tldr_and_guidance()` Haiku call synthesizes readiness, sleep debt, HRV, TSB, glucose, stress, habits, weight into TL;DR + 3-4 personalized recommendations. Replaces static guidance table.
- **TL;DR line**: Single AI-generated sentence under day grade capturing #1 insight.
- **Weight weekly delta**: Weekly loss amount displayed below phase tracker with color coding by phase target.
- **Sleep architecture**: Deep sleep % and REM % added to scorecard grid via Eight Sleep `deep_pct`/`rem_pct` fields.
- **Nutrition meal timing**: AI nutritionist prompt enhanced with meal timestamp patterns from MacroFactor.
- **4 AI calls**: Board of Directors, Training+Nutrition (combined), Journal Coach (conditional), TL;DR+Guidance. All wrapped in try/except with graceful fallback.
- **Timeout**: 180s → 210s for 4 AI calls. Memory: 256MB.
- **Bug fixes carried forward**: macro_bar takes numeric val/target directly (no more str/str division), deploy packages as lambda_function.py (no more ImportModuleError).
- **Code reviewed**: Eight Sleep field names verified against 871 production records (2023-07-23 to 2026-02-24). All 6 features validated.
- **File**: 1361 → 1518 lines.

### IAM Fix
- **day_grade PutItem**: Added `dynamodb:PutItem` to `lambda-weekly-digest-role` inline policy. Was causing `AccessDeniedException` on day grade persistence since v2.0. Script: `fix_daily_brief_iam.sh`.
- **Board of Directors review**: Huberman, Attia, Walker, Galpin, Ferriss, Patrick, Contreas all provided input.

---

## v2.21.0 — 2026-02-25 — Daily Brief v2.1 (Training, Nutrition, Habits, CGM, Journal Coach)

### Daily Brief v2.1 Expansion
- **Training Report**: Strava activities with name/sport/duration/HR + AI sports scientist commentary (Haiku)
- **Nutrition Report**: Macro progress bars (cal/protein/fat/carbs vs targets) + fiber + meal count + AI nutritionist commentary (Haiku)
- **Habits Deep-Dive**: MVP habit checklist (✅/❌ per habit) + group performance breakdown + overall completion
- **CGM Spotlight**: Big number display — avg glucose, time in range %, variability (std dev). Range, readings count, time >140%
- **Journal Coach**: AI reads raw journal, returns perspective reflection + one tactical action for today. Tone: Jocko + Attia + Brené Brown
- **3 AI calls total**: Board of Directors, Training+Nutrition (combined JSON), Journal Coach. All optional — brief renders without them
- **Timeout**: 120s → 180s for 3 AI calls
- **Bug fix**: macro_bar TypeError — was passing strings like "39g" to division. Fixed to pass numeric values
- **Bug fix**: Deploy script module naming — cp to lambda_function.py before zip
- **Section count**: 10 → 14 sections. File: ~700 → 1361 lines

---

## v2.20.0 — 2026-02-25 — Daily Brief v2.0 (Day Grade + Scorecard + Streaks + Weight Phase)

### Daily Brief v2.0 Lambda Rewrite
- **Day Grade**: Weighted 0-100 composite score + letter grade (A+ through F) for yesterday
  - 8 components: sleep (20%), recovery (15%), nutrition (20%), movement (15%), habits MVP (15%), hydration (5%), journal (5%), glucose (5%)
  - Missing components excluded, weights renormalized
  - Persisted to `USER#matthew#SOURCE#day_grade / DATE#YYYY-MM-DD` for retrocompute
  - Stores component scores, weights snapshot, algorithm version per day
- **Scorecard Grid**: All 8 components displayed in a 4×2 grid with progress bars and detail text
- **Habit Streaks**: MVP streak (consecutive days with all 9 MVP habits) + full streak (100% completion)
  - Backward scan from yesterday, up to 90 days
- **Weight Phase Tracker**: Auto-detects current phase from latest Withings weight
  - Shows weekly rate vs phase target, phase progress bar, journey progress bar, milestone ETA
- **Board of Directors Insight**: Upgraded from single Haiku line to multi-sentence coaching paragraph
  - Full data context including nutrition, habits, CGM, journal raw text
  - Embodied voice: sports scientist + nutritionist + sleep specialist + behavioral coach
  - Max 60 words, 2-3 sentences, references specific numbers
- **Profile-Driven**: All targets read from DynamoDB PROFILE#v1 (no hardcoded constants)
  - Calorie, protein, step, water, wake, bedtime, eating window targets all from profile
  - Phase-specific deficit targets from weight_loss_phases
- **Expanded Data Pulls**: MacroFactor (calories, macros), Habitify (MVP habits), Apple Health (steps, water, CGM), Withings (weight + 7d delta), Garmin, today's Whoop recovery
- **Eating Window**: Added to guidance section (16:8 IF: 11:30am-7:30pm)
- **Readiness**: Now prefers today's Whoop recovery from 9:30 AM refresh, falls back to yesterday
- **Dynamic Footer**: Shows which data sources had data for that day

### Scoring Algorithms
- **Sleep**: 40% sleep_score + 30% efficiency + 30% duration adherence (±2h from 7.5h target → 0)
- **Recovery**: Whoop recovery_score direct (0-100)
- **Nutrition**: 40% calorie adherence (±10% tolerance, ±25% penalty) + 40% protein (≥190g=100, ≥170g=80) + 20% macro balance
- **Movement**: 50% exercise (0 if none, 70+ base with time bonus) + 50% steps vs 7000
- **Habits MVP**: completed / 9 × 100
- **Hydration**: water_ml / 2957ml × 100
- **Journal**: 100 (morning+evening), 60 (one), 40 (other), 0 (none)
- **Glucose**: 50% TIR (≥95%=100) + 30% avg glucose (<95=100) + 20% variability (SD<15=100)

### Lambda Config
- Timeout: increased to 120s (expanded data pulls + BoD AI call)
- Memory: increased to 256MB

### New DynamoDB Partition
- `USER#matthew#SOURCE#day_grade / DATE#YYYY-MM-DD` stores daily grade with component breakdown for retrocompute

### Files Modified
- `daily_brief_lambda.py` — complete v2.0 rewrite (~700 lines)
- `deploy_daily_brief_v2.sh` — deployment script

---

## v2.19.0 — 2026-02-25 — Profile v2.0 + Daily Brief Timing Shift

### Profile v2.0
- Complete profile rewrite with Board of Directors-approved targets
- Weight loss phases: 4-phase plan (Ignition/Push/Grind/Chisel) from 302→185 lbs
- Phase 1 Ignition: 3.0 lbs/wk to 250, Phase 2 Push: 2.5 lbs/wk to 220, Phase 3 Grind: 2.0 lbs/wk to 200, Phase 4 Chisel: 1.0 lbs/wk to 185
- Projected goal date: March 7, 2027
- Macro targets: P190g / F60g / C125g (Board consensus: high protein, moderate fat, controlled carb)
- Eating window: 11:30am-7:30pm (16:8 IF)
- MVP habits defined: 9 non-negotiable streak-tracked habits
- Day grade weights v1.0 with retrocompute architecture planned
- Mental health context, primary obstacles, coaching tone, Project40 "why" statement
- Family health history (lymphoma — flags CBC + inflammatory marker monitoring)
- Quarterly reminders: BP, waist circumference, DEXA, supplement review, blood work
- All daily brief targets now profile-driven (wake 4:30 AM, bedtime 9:00 PM, etc.)

### Daily Brief Timing Shift
- Brief moved from 8:15 AM → **10:00 AM PT** (solves stale Whoop recovery data)
- New: Whoop recovery refresh at 9:30 AM PT (`date_override: today`) pulls current morning recovery
- Freshness check moved from 8:15 AM → 9:45 AM PT
- Cache warmer moved from 8:00 AM → 9:00 AM PT
- Whoop Lambda patched to accept `date_override` event parameter (`today`, `YYYY-MM-DD`, or default yesterday)

### Daily Brief Constants Patched (stopgap for v2 rewrite)
- Wake target: 6:00 AM → 4:30 AM
- Protein target: 180g → 190g

### New Schedule (PT)
```
6:00 AM   Whoop, Garmin, Notion
6:15 AM   Withings, Habitify
6:30 AM   Strava, Journal Enrichment
6:45 AM   Todoist
7:00 AM   Eight Sleep
7:30 AM   Activity Enrichment
8:00 AM   MacroFactor
9:00 AM   Cache warmer
9:30 AM   Whoop recovery refresh (NEW)
9:45 AM   Freshness check
10:00 AM  Daily Brief email
```

---

## v2.18.0 — 2026-02-25 — Dropbox MacroFactor Pipeline + Workout Ingestion

### Dropbox Poll Lambda (NEW)
- `dropbox-poll` Lambda polls `/life-platform/` folder every 30 min via EventBridge
- OAuth2 refresh token flow with explicit scope request (files.metadata.read/write, files.content.read/write)
- Downloads MacroFactor CSVs → `s3://matthew-life-platform/uploads/macrofactor/` → triggers existing pipeline
- Content-hash dedup (SHA256) in DynamoDB tracker partition
- Processed files moved to `/life-platform/processed/` (rolling 7-day window)
- New IAM role: `lambda-dropbox-poll-role`
- CloudWatch alarm: `dropbox-poll-errors`
- Eliminates laptop dependency: phone → Dropbox → Lambda → S3 → DynamoDB

### MacroFactor Ingestion Lambda v1.1.0
- Auto-detects CSV type from headers: "Food Name" → nutrition, "Exercise" + "Set Type" → workout
- Workout parsing: set-level rows → exercises → workouts → days (merged from backfill script)
- Workout data: `USER#matthew#SOURCE#macrofactor_workouts` / `DATE#YYYY-MM-DD`
- Workout archives: `raw/macrofactor/workouts/YYYY/MM/`
- Unknown CSV formats logged and skipped gracefully

### Apple Health Webhook v1.3.0
- Water intake tracking: `dietary_water` moved from SKIP_METRICS to METRIC_MAP
- Unit conversion: fl_oz_us → mL (29.5735 factor)
- Stores `water_intake_ml` and `water_intake_oz`
- SOT domain 16: `water` → `apple_health`

### Platform Totals
- 16 Lambdas (+1 dropbox-poll)
- 16 data sources (water added)
- 57 MCP tools
- 16 SOT domains

---

## v2.17.0 — 2026-02-24 — Notion Journal Phase 4 (Brief + Digest Integration)

### Daily Brief v1.1.0
- Journal Pulse section: mood/energy/stress gauges, theme chips, notable quote
- Journal context (mood, energy, stress, themes, emotions) fed into Haiku insight prompt
- Fetches from `USER#matthew#SOURCE#notion` partition via `begins_with(sk, DATE#...#journal#)`
- Graceful degradation: section hidden when no journal entries exist
- Falls back to structured scores when enriched fields unavailable

### Weekly Digest v3.3.0
- New `ex_journal()` extractor: aggregates mood/energy/stress, theme/emotion frequency, avoidance flags, cognitive patterns, best/worst mood days, notable quotes
- Journal & Mood section in HTML (between Habits and Recovery)
- W-o-W deltas for mood/energy/stress vs prior week
- Journal data added to Haiku board prompt payload
- Coach Maya prompt updated to reference journal themes, avoidance flags, cognitive patterns
- Notion added to footer source list

### Files
- `patch_journal_phase4.py` — patches both lambdas in-place
- `deploy_journal_phase4.sh` — deploy script

### Notes
- No IAM changes: both lambdas already have table-level DynamoDB access
- Completes the Notion Journal integration (Phases 1-4 all live)
- Pipeline: Notion DB → ingestion (6:00) → enrichment (6:30) → daily brief (8:15) + weekly digest (Sun 8:30)

---

## v2.16.1 — 2026-02-24 — Apple Health Pipeline Fix + RCA Corrective Actions

### Root Cause Analysis
- **Incident:** Apple Health data not flowing to DynamoDB for 2+ days
- **Root cause:** Wrong Lambda investigated (`apple-health-ingestion` instead of `health-auto-export-webhook`); deployment timing caused 48-metric payload to hit pre-update code
- **Resolution:** Pipeline confirmed working; 786-day historical backfill (2024-01-01 → 2026-02-24) with 37,011 CGM readings
- **RCA document:** `RCA_2026-02-24_apple_health_pipeline.md`

### Corrective Actions Implemented
- **CloudWatch alarm:** `health-auto-export-no-invocations-24h` → SNS alert if webhook receives zero invocations in 24h
- **Architecture docs:** Full request path documented (endpoint → API Gateway route → integration → Lambda) with disambiguation warning for legacy `apple-health-ingestion` Lambda
- **Structured logging (v1.2.0):** JSON log line on every webhook completion — `event`, `request_id`, `metrics_count`, `matched_metrics`, `skipped_sot`, `duration_ms`, `payload_bytes` — queryable via CloudWatch Insights
- **Auth failure tracking:** Structured log on 401s with `request_id` for batch request debugging
- **Historical backfill script:** `backfill_apple_health_export.py` — SOT-aware, tier-filtered, `update_item` merge, streams 1GB+ XML

---

## v2.16.0 — 2026-02-24 — Notion Journal Integration (Phases 1-3)

### Notion Journal Lambda v1.0.0
- **New data source (#16):** Notion journal database → DynamoDB ingestion
- 5 template types: Morning Check-In, Evening Reflection, Stressor Deep-Dive, Health Event, Weekly Reflection
- Extracts all structured properties (selects, multi-selects, rich text) per template
- Multi-per-day support for ad-hoc templates (stressor#1, stressor#2, etc.)
- SK pattern: `DATE#YYYY-MM-DD#journal#<template>` (with `#<seq>` suffix for ad-hocs)
- `raw_text` field pre-built for Phase 2 Haiku enrichment
- Pagination support for large databases
- Deduplication: latest entry wins for single-per-day templates (morning, evening, weekly)
- EventBridge schedule: 6:00 AM PT daily (fetches last 2 days)
- Full sync mode for initial load / backfill

### Infrastructure
- Lambda: `notion-journal-ingestion` (Python 3.12, 128MB, 120s timeout)
- IAM: `lambda-notion-ingestion-role` (DynamoDB + Secrets Manager + CloudWatch)
- Secret: `life-platform/notion` (API key + database ID)
- Schedule: `notion-daily-ingest` EventBridge rule (6:00 AM PT)
- Alarm: `notion-ingestion-errors` → SNS
- SOT: `source_of_truth.journal = notion`

### Database Setup
- Reused existing Notion database, added 36 P40 properties via API patch
- `patch_notion_db.py`: inspects existing schema, adds only missing properties
- `create_notion_db.py`: creates fresh database with full schema (alternative path)

### Phase 2: Haiku Enrichment
- **Lambda:** `journal-enrichment` — Claude Haiku extracts 19 structured fields from raw journal text
- **Expanded expert panel:** Ferriss, Harris, Jocko, Seligman, Csikszentmihalyi, Lyubomirsky, Dalio, Beck (CBT), Hayes (ACT), Newport, Hari, Buettner
- 4 new Notion fields: Gratitude (morning), Social Connection 1-5, Deep Work Hours, One Thing I'm Avoiding (evening)
- Enriched fields: mood/energy/stress (normalized 1-5), sentiment, emotions (granular vocabulary), themes, cognitive_patterns (clinical CBT terms), growth_signals, avoidance_flags, ownership_score (locus of control), social_quality, flow_indicators, values_lived, gratitude_items, alcohol_mention, sleep_disruption_context, pain_mentions, exercise_context, notable_quote
- Schedule: 6:30 AM PT daily (30 min after Notion ingestion)
- IAM: `lambda-journal-enrichment-role`
- Alarm: `journal-enrichment-errors` → SNS
- Full enrichment spec: `NOTION_ENRICHMENT_SPEC.md`

### Phase 3: MCP Tools (52 → 57 tools)
- **get_journal_entries** — retrieve by date/template with enriched signals
- **search_journal** — full-text search across raw text + all enriched fields
- **get_mood_trend** — mood/energy/stress over time, 7-day rolling avg, trend direction, top themes
- **get_journal_insights** — cross-entry pattern analysis: emotions, themes, cognitive patterns, avoidance, ownership, flow, values, gratitude
- **get_journal_correlations** — journal vs wearable data: Pearson correlations + subjective-objective divergences
- `notion` added to SOURCES list
- `journal` → `notion` added to source-of-truth domains

### New SOT Domain
- `journal` → `notion` (15th SOT domain)

---

## v2.15.0 — 2026-02-24 — CGM Pipeline, Gait/Glucose/Energy Tools, Source Filtering

### Health Auto Export Webhook Lambda v1.1.0
- **Automated CGM ingestion** from Dexcom Stelo via Health Auto Export iOS app
- Data flow: Stelo → Apple HealthKit → Health Auto Export (4h background push) → API Gateway → Lambda → DynamoDB + S3
- **Three-tier source filtering** prevents double-counting from HealthKit aggregation:
  - Tier 1 (Apple-exclusive): steps, flights, active/basal calories, distance, gait metrics, headphone audio — all readings ingested
  - Tier 2 (cross-device): HR, RHR, HRV, respiratory rate, SpO2 — filtered to Apple Watch readings only, stored with `_apple` suffix
  - Tier 3 (skip): nutrition (MacroFactor SOT), sleep (Eight Sleep SOT), body comp (Withings SOT) — blocked at ingestion
- Derived fields: `total_calories_burned` = active + basal (Apple Watch TDEE)
- CGM fields: avg/min/max/std_dev, readings_count, time_in_range_pct, time_below_70_pct, time_above_140_pct, cgm_source
- Auto-detects CGM vs manual readings (≥20/day = dexcom_stelo)
- Individual 5-min readings archived in S3 (`raw/cgm_readings/YYYY/MM/DD.json`)
- Source detection via device name substring matching ("Matt", "iPhone", "Apple Watch")
- Bearer token auth via Secrets Manager (`life-platform/health-auto-export`)

### MCP Server v2.15.0 — 6 New Tools (46 → 52)
- **get_gait_analysis** — walking speed (strongest all-cause mortality predictor), step length (earliest aging marker), asymmetry (injury indicator), double support (fall risk). Composite score 0-100, clinical flags vs evidence-based thresholds, trend analysis, asymmetry spike detection
- **get_energy_balance** — Apple Watch TDEE (real wearable measurement) vs MacroFactor intake. Daily surplus/deficit, deficit target hit rate, implied weekly weight change. Complements formula-based get_energy_expenditure
- **get_movement_score** — NEAT estimate (active calories minus Strava exercise calories), movement composite score 0-100, step target tracking, sedentary day flags (<5000 steps + no workout + <200 active cal)
- **get_cgm_dashboard** — glucose time-in-range (target >90%), variability (SD target <20), mean glucose (target <100), fasting proxy (daily min), time above 140. Clinical flags, trend analysis
- **get_glucose_sleep_correlation** — glucose buckets (optimal/normal/elevated/high) vs Eight Sleep outcomes, Pearson correlations for variability/spikes vs sleep quality
- **get_glucose_exercise_correlation** — exercise vs rest day glucose comparison, intensity analysis (easy <140bpm vs hard), duration correlations

### Infrastructure
- **API Gateway HTTP API** (`health-auto-export-api`, a76xwxt2wa) replaces Function URL
- **Freshness alerting v3** — apple_health threshold: 504h/720h → 12h/24h (was manual XML export, now 4h webhook push). Updated impacts for gait, energy, CGM tools
- 3 new SOT domains in profile: `gait`, `energy_expenditure`, `cgm` → all `apple_health`

### Garmin Backfill v2.0.0
- `backfill_garmin.py` synced with `garmin_lambda.py` v1.5.0 extraction logic
- Sleep: 2→18 fields, training status/readiness: full extraction, activities: +5 fields

### Documentation
- SCHEMA.md: gait fields, energy fields, audio exposure, cross-device reference fields (`_apple` suffix), CGM fields, updated SOT block
- ARCHITECTURE.md: webhook ingestion layer, new API Gateway resource

Source count: 14→15. Tool count: 46→52.
Files: `health_auto_export_lambda.py`, `patch_mcp_v2150.py`, `deploy_mcp_v2150.sh`, `patch_freshness_v3.sh`

---

## v2.14.3 — 2026-02-24 — API Gap Closure: 3-Phase Deploy Ready

### Ingestion Lambda Enhancements (patch + deploy scripts ready, not yet deployed)

**Phase 1 — Garmin v1.5.0:** `extract_sleep` expanded from 2→18 fields (stages, timing, SpO2, respiration, restless moments, sub-scores). `extract_activities` gains avg_hr, max_hr, calories, avg/max speed (+5 fields). Garmin becomes a complete second sleep source alongside Eight Sleep.

**Phase 2 — Strava Zones:** New `fetch_activity_zones()` calls `GET /activities/{id}/zones` for per-activity HR zone distribution. Replaces v2.13.0 approximation (classifying whole activities by avg HR) with exact time-in-zone data. Day-level `total_zone2_seconds` aggregation added.

**Phase 3 — Whoop Naps+Timing:** Sleep start/end ISO timestamps extracted from main sleep record. Nap data (nap_count, nap_duration_hours) extracted from previously-filtered nap=True records.

### Session Work
- Validated all 3 patches against current source files (exact multi-line string matching)
- Created missing `deploy_whoop_phase3.sh` (handles `whoop_lambda.py` → `lambda_function.py` rename for Whoop's handler convention)
- All 6 files confirmed: 3 patch scripts + 3 deploy scripts

### Deploy Sequence (run from ~/Documents/Claude/life-platform/)
```
python3 patch_garmin_phase1.py && bash deploy_garmin_phase1.sh
python3 patch_strava_phase2.py && bash deploy_strava_phase2.sh
python3 patch_whoop_phase3.py && bash deploy_whoop_phase3.sh
```

---

## v2.14.2 — 2026-02-24 — Garmin Training Fix + Data Source Audit

### Garmin Lambda v1.4.0
- **Fixed `training_readiness` list parsing** — API returns list not dict; now extracts `[0]` entry
- **Replaced removed `get_training_load()`** — acute/chronic/ACWR now extracted from `get_training_status()` → `acuteTrainingLoadDTO`
- **New fields:** `training_readiness_level`, `hrv_weekly_average`, `recovery_time_hours`, `garmin_acwr`
- Fields per invocation: 12 → 20

### Data Completeness Alerting v2 Redeployed
- Redeployed with Hevy removed and Apple Health thresholds adjusted (21d/30d)

### Data Source Audit
- Comprehensive gap analysis across all 11 sources (`data-source-audit-2026-02-24.md`)
- Garmin ~50% covered, Strava ~70%, Whoop ~95%, MacroFactor + Apple Health 100%
- Phase 1 recommendation: Garmin sleep + activity detail + VO2max (~3-4h, covers 60% of missing value)

---

## v2.14.1 — 2026-02-24 — Data Completeness Alerting + Garmin Fix

### Data Completeness Alerting v2
- 10 sources monitored, per-source staleness thresholds, HTML email via SES, SNS escalation when 3+ stale

### Garmin Lambda Fix (v1.3.0)
- Fixed pydantic_core binary mismatch, display_name auth issue, expired OAuth tokens
- Gap backfill (Jan 19 – Feb 23) completed

---

## v2.14.0 — 2026-02-24 — Alcohol Impact Analyzer

`get_alcohol_sleep_correlation`: Three-source join (MacroFactor + Eight Sleep + Whoop). Dose buckets, drinking vs sober comparison, severity assessment, science alerts. Tool count 57→58.

---

## v2.13.0 — 2026-02-24 — Zone 2 Training Tracker

`get_zone2_breakdown`: 5-zone HR distribution from Strava, weekly vs 150 min target, training polarization alerts. Tool count 56→57.

---

## v2.12.0 — 2026-02-24 — Exercise Timing vs Sleep Quality

`get_exercise_sleep_correlation`: Strava end times + Eight Sleep. Time-of-day buckets, intensity×timing interaction, Pearson correlations. Tool count 55→56.

---

## v2.11.0 — 2026-02-24 — Labs / DEXA / Genome MCP Tools

8 new tools (47→55): `get_lab_results`, `get_lab_trends`, `get_out_of_range_history`, `search_biomarker`, `get_genome_insights`, `get_body_composition_snapshot`, `get_health_risk_profile`, `get_next_lab_priorities`. Automatic genome cross-referencing, derived lipid ratios, persistence classification, FFMI computation, multi-source risk synthesis. SOURCES 11→14.
