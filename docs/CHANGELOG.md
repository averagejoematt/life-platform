## v3.9.4 — 2026-03-23: CI/CD pipeline activation — 3 blockers resolved

### Summary
Activated the dormant CI/CD pipeline (GitHub Actions + OIDC). The pipeline was fully designed
(7 jobs, auto-rollback, 9 integration checks) but had never passed. Three sequential blockers
resolved: F821 lint errors, missing boto3 CI dependency, bash pipefail crash in deprecated
secrets scan. Shared layer (v10) attached to all 15 consumer Lambdas. Pipeline now passing
lint + unit tests + plan (pending final verification). Draft `ask_endpoint.py` archived.

### Changes

**lambdas/daily_brief_lambda.py**
- Fix F821: `hrv_30d_recs` undefined in `lambda_handler` trend-building section
- Added local `_whoop_30d = fetch_range("whoop", ...)` call (was referencing variable
  from `gather_daily_data()` scope which doesn't exist in `lambda_handler`)
- All 3 trend arrays (HRV, sleep, recovery) now use `_whoop_30d` instead of `hrv_30d_recs`

**lambdas/ask_endpoint.py → deploy/archive/ask_endpoint.py**
- Archived draft integration file (7 F821 errors: `_error`, `CORS_HEADERS` undefined)
- Was never deployed — functionality already merged into `site_api_lambda.py`

**.github/workflows/ci-cd.yml**
- Add `boto3 botocore` to test job dependencies (was only installing `pytest`)
- Remove unsupported `--quiet` flag from `python3 -m venv` in CDK diff step
- Fix deprecated secrets scan: add `|| true` to grep pipeline to prevent
  `bash -eo pipefail` crash when zero matches found (false positive failure)
- Fix layer version check: JMESPath used `LayerArn` but AWS API returns `Arn`
  (both Plan and Deploy jobs had same bug — layers were attached but query found nothing)

**AWS infrastructure**
- Attached `life-platform-shared-utils:10` layer to all 15 consumer Lambdas
  (daily-brief, weekly-digest, monthly-digest, nutrition-review, wednesday-chronicle,
  weekly-plate, monday-compass, anomaly-detector, character-sheet-compute,
  daily-metrics-compute, daily-insight-compute, adaptive-mode-compute,
  hypothesis-engine, dashboard-refresh, weekly-correlation-compute)

### CI/CD pipeline status
- OIDC role: ✅ exists (`github-actions-deploy-role`)
- Lint + Syntax: ✅ passing
- Unit Tests (8 linters + deprecated secrets scan): ✅ passing
- Plan (CDK diff + AWS checks + layer verify): ✅ passing (run 23470795396)
- Deploy: ✅ ready (skipped correctly — no code changes in dispatch run)
- GitHub `production` Environment: needs verification (manual approval gate for deploys)

---

## v3.8.9 — 2026-03-22: Nav restructure — rename + reorganise

### Summary
Board-reviewed navigation restructure. Consulted all 6 AI board personas on clarity and
throughline alignment. Applied renaming and structural changes across all 44 HTML files.
Zero URL changes — only nav labels and groupings updated.

### Changes

**All `site/**/*.html` (44 files) — desktop nav + mobile overlay**
- THE STORY: removed "Home" dropdown child (logo links home); renamed "About" → "The Mission"
- THE DATA: renamed "Character" → "Character Sheet"; renamed "Accountability" → "Progress";
  moved Sleep, Glucose, Supplements, Benchmarks from THE SCIENCE into THE DATA
- THE SCIENCE: now only Protocols, Experiments, Discoveries (the methodology pipeline)
- THE BUILD: renamed "Board" → "AI Board"
- FOLLOW: renamed "Chronicle" → "Weekly Journal"; renamed "Ask" → "Ask the Data"
- `is-active` parent-dropdown class correctly migrated for pages whose active item moved
  from THE SCIENCE to THE DATA (sleep, glucose, supplements, benchmarks pages)

**site/start/index.html**
- Path card title "The Chronicle" → "Weekly Journal"; CTA "Read the chronicle →" → "Read the journal →"

**docs/WEBSITE_ROADMAP.md**
- Updated "Navigation Architecture" section to reflect 5-section dropdown structure

### Board findings (condensed)
- Unanimous: "My Story" vs "About" was the #1 friction point — two doors to the same room
- "Chronicle" is opaque to new visitors; "Weekly Journal" is immediately legible
- THE SCIENCE was bloated at 8 items; Sleep/Glucose/Supplements/Benchmarks are data views, not science
- "Board" in THE BUILD reads as kanban/dashboard; "AI Board" disambiguates

---

## v3.8.8 — 2026-03-22: Phase 0 website data fixes

### Summary
Surgical data fixes across the live site per WEBSITE_REDESIGN_SPEC.md Phase 0 task list.
No page redesigns — these are correctness fixes only.

### Changes

**lambdas/site_api_lambda.py**
- G-3: `handle_vitals()` — always return last known weight via `_latest_item("withings")` regardless
  of date window; add `weight_as_of` field to response; fix `if current_weight` to `is not None`
- G-4: `handle_journey()` — remove `_error(503)` fallback when no 120d weight data;
  fall back to `_latest_item("withings")` for last known weight; if no weight at all,
  use journey start (302 lbs) so progress_pct always computes

**site/index.html**
- G-3: Ticker weight display — secondary fetch to `/api/vitals` when public_stats has null weight;
  shows "287.7 LBS (MAR 7)" format when `weight_as_of` is >3 days old

**site/story/index.html** — STORY-1
- Add IDs `story-lambda-count`, `story-data-sources-stat`, `story-tools-count` to data-moment spans
- Wire to `platform.lambdas`, `platform.data_sources`, `platform.mcp_tools` in existing loader
- test_count and monthly_cost left static (not in public_stats.json yet)

**site/platform/index.html** — PLAT-1
- Add IDs `plat-mcp-tools`, `plat-data-sources`, `plat-lambdas` to header stat cards
- New JS loader reads public_stats.json and updates all three values on page load

**site/protocols/index.html** — PROTO-1
- Remove hardcoded fallback adherence values (78%, 82%, 90%, etc.)
- `applyFallback()` now shows "—" (em dash) when API is unavailable

### Investigated (no code change needed)
- CHRON-1: All post navs (week-00, 01, 02, 03) already have current 5-section structure ✓
- CHRON-2: `site/journal/posts/week-01/` exists but has no content ("See S3" placeholder);
  added to backlog for Elena Voss content generation session
- G-5: Streak already defaults to 0 in unified loader (line 1354, `!= null` check) ✓
- G-7: `/api/subscribe` routes to `email_subscriber_lambda.py` via CloudFront; code looks correct;
  suspect SES verification issue — check `lifeplatform@mattsusername.com` verified in us-west-2

### Pending (requires Matthew input)
- G-8: Privacy page contact email `matt@averagejoematt.com` — confirm correct address

---

## v3.8.7 — 2026-03-22: CI/CD pipeline activation

### Summary
The GitHub Actions CI/CD pipeline (ci-cd.yml) was fully built post-R13 but never activated.
This version fixes the one outstanding gap (lambda_map.json) and activates the pipeline.
The pipeline covers: lint → pytest (83+ tests) → plan (cdk diff + layer check) → deploy
(manual approval gate) → smoke test → auto-rollback → SNS notify on failure.

### Changes

**ci/lambda_map.json** — site_api fix
- Moved `lambdas/site_api_lambda.py` from `skip_deploy` → `lambdas` section
  with `function: life-platform-site-api`. Was incorrectly skipped (it's a real
  deployed Lambda in us-west-2, deployable via deploy_lambda.sh).
- Bumped `_updated` to v3.8.7.

**Activation steps (run manually):**
1. `bash deploy/setup_github_oidc.sh` — creates OIDC provider + IAM role in AWS
2. Create 'production' Environment in GitHub repo settings
3. `git add -A && git commit -m "v3.8.7: activate CI/CD pipeline" && git push`
4. Approve the deploy job in GitHub Actions UI (or skip if no Lambda changes)

---

## v3.8.6 — 2026-03-22: Phase 2 /live/ + /character/ enhancements

### Summary
Phase 2 completes its first three targets. /live/ gets a glucose snapshot panel (new data
not previously shown). /character/ gets a live state banner and dynamic tier highlighting.

### Changes

**site/live/index.html** — Glucose snapshot panel
- New `<!-- Glucose Snapshot -->` panel-section inserted after sleep section.
  Shows: Time In Range % (today) with progress bar and status label, 30-day TIR avg,
  variability status, days tracked, and a 20-point TIR sparkline SVG.
- New `initGlucose()` async function fetches `/api/glucose` (endpoint exists; was unused on live page).
  Gracefully hides the section on 503 or missing data.
- Added `initGlucose()` call in init sequence (after sleep, before training).

**site/character/index.html** — Live state banner + dynamic tier
- New `#char-state-banner` div inserted between page-header and intro narrative.
  Two rows: Level · Tier · Days active | Strongest pillar → Bottleneck pillar.
  All fields populated by `hydrate()` from live character data.
- `hydrate()` extended: populates banner fields (cbs-level, cbs-tier, cbs-days,
  cbs-strongest, cbs-bottleneck). Tier highlight logic resets all 4 tier rows to
  `text-faint` then marks the current tier in `accent` with `← current` label.
- Tier description rows now have IDs (td-foundation, td-momentum, td-chisel, td-elite)
  and `.td-name` / `.td-desc` classes for JS targeting.
- Removed hardcoded `color:var(--accent)` on Chisel row; tier is now data-driven.

---

## v3.8.5 — 2026-03-22: Phase 2 /discoveries/ empty state

### Summary
Task 47: /discoveries/ no longer shows a blank page when correlation data is absent.
Replaced bare "No correlation data yet." messages with a rich empty state showing
days collected, a progress bar toward the 90-day rolling window, and a clear unlock
condition. When data IS present, adds a "last updated" note below the stats strip.

### Changes

**site/discoveries/index.html** — JS rewrite
- `renderEmptyState()`: calculates days since journey start (2026-02-09), pct toward
  90-day window, needed days remaining. Renders consistent banner in featured card,
  spotlight grid, and archive table.
- `loadDiscoveries()`: early-exit to `renderEmptyState()` on 503, empty pairs, or fetch
  error. Removes now-dead `strong` variable and the `if (top)` branch.
- Last-updated note injected below stats strip when data loads: week of last run,
  next run day (Sunday), days tracked count.
- Minor: spotlight tag spacing fix (space before `·`).

---

## v3.8.4 — 2026-03-22: Phase 2 /experiments/ depth + Keystone group fix

### Summary
Two items: /experiments/ page gets Active Experiment Spotlight + delta chips on completed cards.
Keystone Spotlight group data fix — `handle_habits()` was reading `SOURCE#habit_scores` for
group data but groups live in `SOURCE#habitify` as `by_group`. Added second DynamoDB query
to cross-join. Verified live: `keystone_group: "Nutrition"` at 63% 90-day avg.

### Changes

**lambdas/site_api_lambda.py** — two endpoints updated
- `handle_experiments()`: returns `outcome`, `result_summary`, `primary_metric`,
  `baseline_value`, `result_value`, `metrics_tracked`, `duration_days`, `days_in`,
  `progress_pct`, `confirmed`, `hypothesis_confirmed`. All previously dropped silently.
- `handle_habits()`: added second DynamoDB query against `SOURCE#habitify` to pull
  `by_group` data. Cross-joined into history `groups` field when `habit_scores` has
  no flat `group_*` fields. `pct` (0.0–1.0) converted to 0–100 integer.
  `group_90d_avgs` and `keystone_group` now populate correctly.

**site/experiments/index.html** — Phase 2 content depth
- Active Experiment Spotlight: accent-bordered card above filter list showing name,
  hypothesis, day counter, progress bar (if `planned_duration_days` set), metric chips.
  Hidden when no active experiment.
- Delta chips on completed cards: `↑ +8.2 HRV` / `↓ -4.1 weight` in green/red.
  Lower-is-better metrics (weight, rhr, glucose) auto-flip color logic.
- Confirmed/refuted badges from `hypothesis_confirmed` field.
- Primary metric replaces generic Category field when available.

### Verification
- `keystone_group: "Nutrition"`, `keystone_group_pct: 63` — confirmed live
- `by_group` has all 9 groups: Nutrition, Growth, Wellbeing, Data, Performance,
  Discipline, Recovery, Hygiene, Supplements
- `best_day: 6` (Sunday is strongest day)

---

## v3.8.3 — 2026-03-22: Phase 2 /habits/ page — Keystone Spotlight + Day-of-Week Pattern

### Summary
First Phase 2 content-depth item. `/habits/` page gains two new intelligence sections
powered by new fields added to `handle_habits()` in `site_api_lambda.py`. Both sections
are gracefully hidden when group/DOW data is absent from DynamoDB — no empty states.

### Changes

**lambdas/site_api_lambda.py** — handle_habits() extended
- `day_of_week_avgs`: [Mon–Sun] average Tier 0 completion % over 90 days.
- `best_day` / `worst_day`: index (0=Mon, 6=Sun) of peak and most vulnerable day.
- `group_90d_avgs`: dict of per-group 90-day adherence averages.
- `keystone_group` / `keystone_group_pct`: strongest habit group by 90-day avg.
- All new fields are additive — backwards compatible with existing page JS.

**site/habits/index.html** — two new sections added
- Keystone Spotlight: accent-bordered card showing #1 group name, 90-day %, and
  contextual description. Position: between Tier 0 streak block and Weekly Trend.
- Day of Week Pattern: 7-bar chart (green=best, red=worst) with insight line.
  Position: between Weekly Trend and Streak Records.
- Both sections hidden by default (`display:none`); shown only when API returns data.
- All 9 group descriptions pre-coded in `KEYSTONE_DESCRIPTIONS` map.

### Deploy
- `lambdas/site_api_lambda.py` → deployed to `life-platform-site-api` (us-west-2) manually.
- `site/habits/` synced to S3 + CloudFront invalidated `/habits/*` + `/api/habits`.

---

## v3.8.2 — 2026-03-22: D10 baseline + Phase 1 Task 20 reading path CTAs

### Summary
Completes Phase 0 (D10 — last remaining data fix) and Phase 1 Task 20 (reading path CTAs).
D10: the compare card Day 1 column now pulls from `public_stats.json` baseline object
instead of hardcoded HTML values. Baseline flows: profile → daily_brief Lambda → site_writer
→ public_stats.json. Phase 1 Tasks 13-19 + 21 were already done by Claude Code sessions;
Task 20 (reading path CTAs) is the final Phase 1 item.

### Changes

**lambdas/site_writer.py** — v1.3.0
- Added `baseline: dict = None` parameter to `write_public_stats()`.
- Passes baseline into `public_stats.json` payload as top-level `"baseline"` key.
- Tightened `CacheControl` from 24h to 1h for more responsive updates.
- Version bumped: v1.2.0 → v1.3.0.

**lambdas/daily_brief_lambda.py** — v2.82.2
- Extended `write_public_stats()` call to pass `baseline={}` dict.
- Reads `baseline_date`, `baseline_weight_lbs`, `baseline_hrv_ms`, `baseline_rhr_bpm`,
  `baseline_recovery_pct` from PROFILE#v1; falls back to Feb 22 actuals (302.0 / 45 / 62 / 55%).

**deploy/add_reading_path_ctas.py** — new script
- Injects "Continue the story" reading-path CTAs before `<!-- Mobile bottom nav -->` on
  7 pages: /story/ /live/ /character/ /habits/ /experiments/ /discoveries/ /intelligence/
- Each CTA links to the next logical page in the story loop.
- Idempotent: skips pages that already have reading-path markup.

**deploy/deploy_d10_phase1.sh** — new script
- Orchestrates full deploy: inject CTAs → fix_public_stats --write → Lambda deploy →
  S3 sync → CloudFront invalidation.

### Website Strategy Status
- Phase 0: ✅ COMPLETE (D1–D10 all resolved)
- Phase 1: ✅ COMPLETE (Tasks 13–21 all done)
- Next: Phase 2 — content depth (habits page, character expansion, accountability rethink)

---

## v3.8.1 — 2026-03-22: Phase 0 Data Fixes — D1 weight null, hardcoded platform stats removed

### Summary
Diagnosed and fixed the root cause of `public_stats.json` being frozen since March 16.
Root cause: the sick day Lambda early-return path skipped `write_public_stats`, so every
sick day left the S3 file unchanged. Withings data stops at 2026-03-07 (last weigh-in
before illness). Fixed with a 30-day lookback that correctly surfaces the last known weight.
All hardcoded platform stats removed from both the Lambda and the rebuild script —
everything now sourced from profile, DynamoDB computed_metrics, or auto-discovered from
source files (registry.py, CDK stacks, CHANGELOG).

### Changes

**lambdas/daily_brief_lambda.py** — v2.82.1
- **D1-FIX**: Added `write_public_stats` call to sick day early-return path — website
  no longer goes stale during multi-day illness periods. Uses `gather_daily_data` data
  already in memory (30-day Withings lookback) — zero extra DynamoDB cost.
- **Hardcodes removed**: `mcp_tools`, `data_sources`, `lambdas`, `last_review_grade`
  now pulled from `profile.get("platform_meta", {})` in both sick day and normal paths.
- **Hardcodes removed**: `zone2_target_min` now pulled from profile (`zone2_weekly_target_min`
  or `zone2_target_min_weekly`), with 150 as last-resort fallback only.

**deploy/fix_public_stats.py** — new script
- One-shot script to rebuild and push `public_stats.json` to S3 from live DynamoDB data.
- Zero hardcoded values: weight from Withings (30-day lookback), vitals from Whoop,
  training from `computed_metrics`, platform counts auto-discovered from registry.py +
  CDK stacks + CHANGELOG.md.
- Runs CloudFront invalidation automatically on `--write`.
- Usage: `python3 deploy/fix_public_stats.py` (dry run) / `--write` (push live).

**deploy/deploy_daily_brief_fix.sh** — new script
- Packages and deploys `daily-brief` Lambda with all required layer files.

### Data fixes applied (live on averagejoematt.com)
| Field | Before | After |
|-------|--------|-------|
| `vitals.weight_lbs` | null | 287.7 lbs |
| `journey.current_weight_lbs` | 0.0 | 287.69 lbs |
| `journey.lost_lbs` | 0 | 14.3 lbs |
| `journey.progress_pct` | 0% | 12.2% |
| `journey.weekly_rate_lbs` | 287.69 (broken) | -2.45 lbs/wk |
| `journey.days_in` | missing | 28 |
| `journey.projected_goal_date` | null | 2027-03-07 |
| `training.total_miles_30d` | 0 | 34.6 |
| `training.activity_count_30d` | 0 | 18 |
| `training.zone2_this_week_min` | 42 | 42 (now live) |
| `platform.mcp_tools` | 87 (stale) | 95 (from registry.py) |
| `platform.lambdas` | 42 (stale) | 50 (from CDK stacks) |
| `platform.last_review_grade` | A (stale) | A- (from CHANGELOG) |

### DynamoDB changes
- `USER#matthew / PROFILE#v1`: added `platform_meta` map field
  (`mcp_tools`, `data_sources`, `lambdas`, `last_review_grade`)

### Deploys
- Lambda `daily-brief` (us-west-2): ✅ 2026-03-22
- S3 `site/public_stats.json`: ✅ 2026-03-22 (CloudFront invalidation I35NKA9GH69M27BAVXM1U6L4XH + ID90AC5Z3GENXGHAPXKGQ0UEP)

---

## v3.8.0 — 2026-03-21: Sprint 8 — Mobile Navigation, Content Safety Filter, Grouped Footer

### Summary
Unified Board Summit #3 convened (Technical Board, Personal Board, Web Board — 30+ personas including Jony Ive, Lenny Rachitsky, Julie Zhuo, Andrew Chen, David Perell, Ethan Mollick). Three critical findings: (1) mobile visitors have ZERO navigation (nav__links display:none with no hamburger), (2) site needs three-tier nav architecture (top nav for discovery, bottom nav for engagement, footer for completeness), (3) content filter needed to hide sensitive vices from all public surfaces. All 30 HTML pages patched. Content filter deployed to site-api Lambda.

### Navigation Architecture (30 pages patched)
- **Mobile hamburger menu** — ☰ icon in top-right, opens full-page overlay with grouped sections (The Journey / The Data / The Platform / Follow)
- **Mobile bottom nav** — persistent 60px bar with 5 thumb-zone icons: Home · Ask · Score · Journal · More
- **Updated top nav** (desktop) — Story · Live · Journal · Platform · About · [Subscribe →] (was: Story · Live · Journal · Platform · Character)
- **Grouped footer v2** — 4-column layout (The Journey / The Data / The Platform / Follow) replaces flat 12-link footer
- **nav.js shared component** — handles hamburger toggle, bottom nav active state, overlay open/close, keyboard escape, theme toggle prep

### Content Safety Filter
- **S3 config** — `config/content_filter.json` with blocked vices ("No porn", "No marijuana") and blocked keywords
- **Lambda integration** — `_load_content_filter()` loads from S3 (cached in warm container), `_scrub_blocked_terms()` strips mentions from AI responses, `_is_blocked_vice()` utility for future endpoints
- **System prompt** — `/api/ask` prompt now explicitly instructs Claude to never mention blocked terms
- **Response scrubbing** — both `/api/ask` and `/api/board_ask` responses pass through `_scrub_blocked_terms()` before returning

### Website Versioning Infrastructure
- **`deploy/rollback_site.sh`** — git-tag-based rollback: checkout tag → S3 sync → CloudFront invalidate
- **`site-v3.8.0` tag** — first tagged deploy for instant rollback capability
- **Theme system architecture** designed (Layer 1: git tags for structural, Layer 3: CSS data-theme for visual) — implementation deferred to next session

### Unified Board Summit #3 — Feature Vision
- Full inventory of 87+ MCP tools mapped to proposed website pages
- 12 new page concepts identified with data sources already built (habits, achievements, supplements, benchmarks, glucose, sleep, intelligence, progress, accountability, methodology, journal/archive, genome)
- Gamification vision: SVG avatar evolving with pillar tiers, badge/achievement wall, "since your last visit" indicators
- Commercialization ladder: Free newsletter → Premium ($10/mo) → Course ($99-299) → Community ($29/mo) → Advisory ($500+/hr)
- Full website roadmap written to `docs/WEBSITE_ROADMAP.md` for Claude Code continuation

### Files Created
| File | Purpose |
|------|---------|
| `site/assets/js/nav.js` | Shared navigation JS component |
| `site/assets/css/base.css` (appended) | +5,219 chars: hamburger, bottom nav, overlay, grouped footer CSS |
| `seeds/content_filter.json` | Content safety filter config (uploaded to S3) |
| `deploy/deploy_sprint8_nav.py` | Master nav patching script (30 pages) |
| `deploy/patch_content_filter.py` | Lambda content filter integration script |
| `deploy/rollback_site.sh` | Git-tag-based site rollback script |
| `docs/WEBSITE_ROADMAP.md` | Comprehensive roadmap for Claude Code continuation |
| `handovers/HANDOVER_v3.8.0.md` | Session handover |

### Deploys
- S3 site sync: ✅ (30 pages + nav.js + base.css)
- CloudFront invalidation: ✅ (`I8XRHMEYNI8GYEPZFJZHDVCTQJ`)
- Lambda life-platform-site-api (us-east-1): ✅ (content filter)
- S3 config: ✅ (`config/content_filter.json`)
- Git tag: ✅ (`site-v3.8.0`)

### Key Metrics Update
| Metric | Before | After |
|--------|--------|-------|
| Website pages | 15 | 15 (no new pages, all patched) |
| HTML files patched | 0 | 30 |
| Mobile navigation | None (display:none) | Hamburger + bottom nav + overlay |
| Content filter | None | 3-layer (S3 config + prompt + response scrub) |
| Git tags | None | site-v3.8.0 (first tagged deploy) |

---

## v3.7.84 — 2026-03-20: Sprint 7 World-Class Website — Expert Panel Review + 15 Items Shipped

### Summary
Conducted a 30+ persona expert panel website strategy review (Jony Ive, Peter Attia, Paul Graham, Andrew Chen, David Perell, Lenny Rachitsky, full Technical Board + Personal Board). Key finding: "The site has world-class infrastructure but undersells the story by 10x." Created Sprint 7 (19 items, WR-14 through WR-46) and shipped 15 of 19 items in-session. 4 new pages live. 5 new homepage sections. Multiple /platform/ and /character/ enhancements. Site-api safety filter deployed. CloudFront 404 routing fixed via CDK.

### New Pages Live
- `/protocols/` — 6 protocol cards (sleep, training, nutrition, metabolic, habits, supplements) with data sources and compliance status (WR-39)
- `/platform/reviews/` — Public architecture review #17: 14-member AI board grades, selected findings, grade history (WR-36)
- `/journal/sample/` — Newsletter sample page with browser-frame mock email UI for The Weekly Signal (WR-32)
- `/404.html` — Branded 404 page matching site design language (WR-28)

### Homepage Enhancements
- **WR-38: Discoveries section** — 3 real correlations with r values, p values, and sample sizes (sleep→recovery, bed temp→deep sleep, Zone 2→HRV)
- **WR-33: Day 1 vs Today comparison card** — side-by-side: weight 302→287.7, HRV 45→66 (+47%), RHR 62→52, recovery 55%→89%
- **WR-31: "New here? Start with the story" CTA** — amber banner in hero section
- **WR-30: Real daily brief excerpt** — replaced "coming soon" placeholder with actual AI coaching brief content
- **WR-29: Fixed live data double-path bug** — `/site/public_stats.json` → `/public_stats.json` (CloudFront origin already adds `/site` prefix)
- Sample issue links added to all email CTAs across homepage, platform, character pages

### /platform/ Enhancements
- **WR-34: Animated data flow diagram** — SVG with animated green dots showing 19 Sources → Ingest → Store → Serve → Emails/Website/Ask
- **WR-35: FinOps cost section** — $13/month total, $3 Claude, $10 AWS, 0 engineers grid
- **WR-44: Tool of the Week spotlight** — `get_sleep_environment_analysis` with input/output/finding
- Link to public architecture review from reviews section

### /character/ Enhancements
- **WR-37: Scoring methodology section** — pillar data sources table showing what feeds each of the 7 pillars
- Sample issue link added to email CTA

### Infrastructure
- **WR-28: CloudFront 404/403 fix** — CDK updated: 404→custom 404.html, 403→200/index.html for S3 routing. Deployed via `cdk deploy LifePlatformWeb`.
- **WR-40: /api/ask response safety filter** — 6 blocked regex categories (PII, financial, medical diagnosis, credentials) + system prompt safety guardrails. Deployed to us-east-1.
- `deploy/deploy_sprint7_tier0.sh` — deploy script handling us-east-1 site-api Lambda

### Documentation
- `docs/reviews/WEBSITE_PANEL_REVIEW_2026-03-20.md` — Full 10-section expert panel review document
- `docs/PROJECT_PLAN.md` — Website Strategy Review #2 section added (19 items)
- `docs/SPRINT_PLAN.md` — Sprint 7 added (3 tiers, 19 items, 15 complete)
- `site/sitemap.xml` — 5 new entries (board, journal/sample, subscribe, protocols, platform/reviews)

### Sprint 7 Scorecard
| Tier | Total | Done | Remaining |
|------|-------|------|-----------|
| Tier 0 (Foundations) | 7 | 5 built + 2 Matthew-only | WR-14 (/story/ prose), WR-15 (photos) |
| Tier 1 (Retention) | 8 | 8 | All complete |
| Tier 2 (Growth) | 4 buildable | 1 | WR-43 (heartbeat), WR-45 (media kit), WR-46 (open data) |

### Deploys
- S3 site sync: ✅ (3 syncs this session)
- CloudFront invalidation: ✅ (3 invalidations)
- CDK LifePlatformWeb: ✅ (WR-28 error responses)
- Lambda life-platform-site-api (us-east-1): ✅ (WR-40 safety filter)

### Key Metrics Update
| Metric | Before | After |
|--------|--------|-------|
| Website pages live | 12 | 15 (+protocols, +platform/reviews, +journal/sample) |
| Homepage sections | 4 | 7 (+discoveries, +comparison card, +start-here CTA) |
| Sprint 7 items | 0/19 | 15/19 |
| WR items total | WR-24 | WR-46 |

---

## v3.7.83 — 2026-03-20: Operational Efficiency Roadmap + Claude Code Adoption

### Changes

**docs/PROJECT_PLAN.md** — updated
- Added Operational Efficiency Roadmap section (OE-01 through OE-10), stack-ranked by ROI
- Derived from full conversation history analysis across all Life Platform sessions
- Covers: Claude Code adoption, shell aliases, tool surface management, Project Knowledge, terminal anti-patterns, test discipline, memory strategy, Deep Research, doc consolidation, dev environment

**OE-01: Claude Code installed and verified (v2.1.80)**
- Native binary installed via `curl -fsSL https://claude.ai/install.sh | bash`
- PATH configured in ~/.zshrc
- Authenticated via browser (uses existing Pro subscription)
- First session launched in life-platform directory
- Claude Code cheat sheet PDF created (2-page transition guide: before/after comparisons, essential commands, Chat vs Code decision matrix)

---

## R17 Architecture Review — 2026-03-20

### Summary
Architecture Review #17 conducted (grade A-). 13 findings across security, observability, architecture, compliance, and code hygiene. 6 board decisions made. Sprint 6 (R17 Hardening) created with 18 items across 3 tiers. Grade drops from A to A- because the platform crossed the public-exposure threshold (AI endpoints on the open internet) and defensive controls haven't fully caught up.

Key board decisions: WAF rate-based rules on CloudFront (+$7/mo, replaces in-memory rate limiting as primary layer), move site-api to us-west-2 (60-day, $0), separate Anthropic API key for public endpoints (+$0.40/mo), graceful degradation pattern for AI calls (no new deps), UptimeRobot free tier for external monitoring. Platform cost increases from ~$13 to ~$20.40/month (under $25 budget cap). All decisions approved by Matthew.

Critical pre-DIST-1 items: WAF, privacy policy page, CloudWatch dashboard, PITR drill, separate API key.

### Changes

**docs/reviews/REVIEW_2026-03-20_v17.md** — new
- Full R17 review document (14-member board, 13 findings, 6 board decisions)
- Per-panelist grades: Yael B+ (security gaps on public endpoints), Raj B+ (distribution vs infrastructure ratio), Viktor B+ (attack surface analysis), all others A- to A
- Board deliberation on 6 open decisions with full rationale

**docs/SPRINT_PLAN.md** — updated
- Sprint 6 (R17 Hardening) added: 8 Tier 0 items (pre-DIST-1), 6 Tier 1 (60-day), 4 Tier 2 (90-day)
- Sprint Timeline Summary updated with Sprint 6 and corrected R18 target
- Footer updated with R17 review reference

### Architecture Review #17 Findings Summary
| ID | Severity | Finding |
|----|----------|---------|
| R17-F01 | Critical | Public AI endpoints lack persistent rate limiting |
| R17-F02 | High | In-memory rate limiting resets on cold start |
| R17-F03 | High | No WAF on public-facing CloudFront distributions |
| R17-F04 | Medium | Subscriber email verification has no rate limit |
| R17-F05 | High | Cross-region DynamoDB reads (site-api us-east-1 → DDB us-west-2) |
| R17-F06 | Medium | No observability on public API endpoints |
| R17-F07 | Medium | CORS headers not evidenced on site API |
| R17-F08 | Low | google_calendar still in config.py SOURCES list |
| R17-F09 | Low | MCP Lambda memory discrepancy in documentation |
| R17-F10 | Low | Site API AI calls use hardcoded model strings |
| R17-F11 | Medium | No privacy policy or terms of service on public website |
| R17-F12 | Medium | PITR restore drill still not executed (carried since R13) |
| R17-F13 | Medium | 95 tools creates context window pressure for Claude |

---

## v3.7.81 — 2026-03-19: Standardise nav + footer across all 12 pages

### Summary
Navigation audit revealed 8 of 12 pages were unreachable from the main nav — including /story/ (the distribution gate), /board/, /ask/, /explorer/, /experiments/, /biology/, /about/, and /live/. New consistent nav ships Story · Live · Journal · Platform · Character · Subscribe across all 12 pages. New full footer links all 12 pages. `deploy/update_nav.py` added for future nav maintenance.

### Changes

**deploy/update_nav.py** — new script
- Regex-patches nav + footer blocks across all 12 site pages in one pass
- Per-page active state on nav links, dry-run mode

**All 12 site pages — nav updated**
- Old: The experiment · The platform · Journal · Character (4 items, inconsistent)
- New: Story · Live · Journal · Platform · Character · [Subscribe →] (6 items, consistent)
- /story/ promoted into nav — was completely invisible despite being the distribution gate
- /live/ promoted into nav — was only reachable via homepage dual-CTA

**All 12 site pages — footer updated**
- Old: Story · Journal · Platform · Character · Subscribe
- New: Story · Live · Journal · Platform · Character · Experiments · Explorer · Biology · Ask · Board · About · Subscribe + Privacy
- /board/, /ask/, /explorer/, /experiments/, /biology/ no longer orphaned

### Deploys
- 12 static pages: ✅ S3 synced, CloudFront invalidated `/*`

---

## v3.7.80 — 2026-03-19: WR-24 subscriber gate, S2-T2-2 /board/ page, sprint plan cleanup

### Summary
Three pure dev items shipped: (1) WR-24 — subscriber verification gate on /ask/ (3 anon q/hr → 20/hr for confirmed subscribers via HMAC token + /api/verify_subscriber endpoint); (2) S2-T2-2 — "What Would My Board Say?" lead magnet page at /board/ with 6 AI personas (Attia, Huberman, Patrick, Norton, Clear, Goggins) and /api/board_ask endpoint; (3) Sprint plan cleanup marking S2-T1-9 and S2-T1-10 as done. CDK deployed LifePlatformWeb with 2 new CloudFront behaviors. Full site synced to S3.

### Changes

**lambdas/site_api_lambda.py**
- `_get_token_secret()` — derives HMAC signing secret from existing Anthropic API key (no new secrets)
- `_generate_subscriber_token(email)` — 24hr HMAC token (base64-encoded, `email:expires:sig` format)
- `_validate_subscriber_token(token)` — constant-time compare, expiry check
- `_is_confirmed_subscriber(email)` — DDB lookup: `USER#matthew#SOURCE#subscribers / EMAIL#{sha256}`, `status=="confirmed"`
- `_handle_verify_subscriber(event)` — GET `/api/verify_subscriber?email=...` → 404 if not found, 200 + token if confirmed
- `PERSONA_PROMPTS` — 6 persona system prompts (Attia, Huberman, Patrick, Norton, Clear, Goggins)
- `_handle_board_ask(event)` — POST `/api/board_ask` → per-persona Haiku 4.5 calls, 5/hr IP rate limit
- `ROUTES` dict updated, `lambda_handler` updated, `CORS_HEADERS` updated
- `_ask_rate_check(ip_hash, limit=3)` — parameterised limit (was hardcoded 5)

**site/ask/index.html — WR-24 subscriber gate**
- `MAX_QUESTIONS = 3`, `SUBSCRIBER_LIMIT = 20`, `effectiveLimit()`, `verifySubscriber()`
- Rate-banner replaced with subscriber gate UI
- `X-Subscriber-Token` header forwarded on every `/api/ask` POST

**site/board/index.html — S2-T2-2 new page**
- "What Would My Board Say?" — 6 AI personas, selector grid, skeleton loaders, subscribe CTA

**cdk/stacks/web_stack.py**
- Added `/api/verify_subscriber` and `/api/board_ask` cache behaviors

**docs/SPRINT_PLAN.md**
- S2-T1-9, S2-T1-10 marked ✅ Done; WR-24 + S2-T2-2 added as completed Sprint 5 rows

### Deploys
- `LifePlatformWeb` CDK stack: ✅ 2026-03-19 (130s)
- `site/ask/index.html`, `site/board/index.html`: ✅ S3 synced
- CloudFront: ✅ Invalidated `/*`

---
