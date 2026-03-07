# Life Platform — Project Plan

> Living document. For completed work and version history, see CHANGELOG.md / CHANGELOG_ARCHIVE.md.
> Last update: 2026-03-07 (v2.84.3 — 135 MCP tools, 32 Lambdas, 19 data sources, 6 secrets, 35 alarms)

---

## Current State

- **Platform version:** v2.84.3
- **MCP Server:** 135 tools across 27-module package, serving health data through Claude Desktop + claude.ai + Claude mobile (1024 MB, 12 tools pre-cached nightly)
- **Remote MCP:** Function URL `c5hljblvma4u2xd6wf6oe4clk40unthu.lambda-url.us-west-2.on.aws` with OAuth auto-approve + HMAC Bearer token validation
- **Data Sources:** 19 (12 scheduled + 1 webhook + 3 manual/periodic + 2 MCP-managed + 1 State of Mind via webhook)
- **Lambdas:** 32 (13 ingestion + 1 webhook + 2 enrichment + 6 email/digest + 1 dropbox-poll + 1 inbound-email + 1 key-rotator + 1 character-sheet-compute + 1 adaptive-mode-compute + 1 daily-metrics-compute + 1 dashboard-refresh + 1 data-export + 1 qa-smoke)
- **Cost:** Under $25/month (~$3/month projected after secrets consolidation)
- **Secrets Manager:** 6 secrets (was 12 — consolidated anthropic/todoist/habitify/health-auto-export/notion/dropbox into `life-platform/api-keys`)
- **CloudWatch Alarms:** 35 (all Lambdas now monitored)
- **Web Dashboard:** CloudFront — `https://dash.averagejoematt.com/` (Lambda@Edge auth)
- **Blog:** CloudFront — `https://blog.averagejoematt.com/` (public, no auth) — "The Measured Life" by Elena Voss
- **Buddy Page:** CloudFront — `https://buddy.averagejoematt.com/` (Lambda@Edge auth, separate password) — accountability partner interface for Tom
- **AWS:** Account 205930651321, us-west-2, S3 `matthew-life-platform`, DynamoDB `life-platform`
- **SOT Domains:** 21 (cardio, strength, physiology, nutrition, sleep [Whoop], sleep_environment [Eight Sleep], body, steps, tasks, habits, stress, body_battery, gait, energy_expenditure, cgm, journal, water, caffeine, supplements, weather, state_of_mind)

### Daily Brief v2.6 (live as of 2026-02-28, lambda v2.62.0)
- 18 sections: readiness, day grade + TL;DR, scorecard, weight phase, training, nutrition, **habits (tier-weighted)**, **supplements**, CGM spotlight, gait & mobility, **weather context**, **travel banner**, **blood pressure**, guidance, journal pulse/coach, BoD insight, anomaly alert
- 4 AI calls (Haiku): BoD coaching, training+nutrition commentary, journal coach, TL;DR+guidance
- **Habit Intelligence:** 65-habit registry with tier-weighted scoring (T0=3x, T1=1x, T2=0.5x), vice streak tracking, synergy alerts
- Day grade + **habit_scores** persisted to DynamoDB for retrocompute and trending
- Profile-driven targets (wake, macros, eating window, weight phases, habit registry)
- **Writes `dashboard/data.json` + `buddy/data.json` to S3 after email** (non-fatal, try/except wrapped)
- **Activity dedup:** `_dedup_activities()` removes WHOOP+Garmin duplicates at read-time (15-min window, 40% duration match, Garmin preferred)
- **Regrade mode:** `{"regrade_dates": [...]}` event recomputes day grades without sending email
- Schedule: Whoop refresh 9:30 AM → Brief at 10:00 AM PT

### Wednesday Chronicle — "The Measured Life" (live as of 2026-03-01)
- **Lambda:** `wednesday-chronicle` (Sonnet 4.5, temperature 0.6, ~$0.04/week)
- **Author persona:** Elena Voss, freelance journalist embedded with Matthew
- **Editorial approach v1.1:** Synthesis over recounting — each installment has a thesis, not a timeline
- **Data packet:** 12 sources (whoop, eightsleep, garmin, strava, withings, macrofactor, journal, habits, state_of_mind, weather, experiments, anomalies)
- **Continuity:** Previous 4 installments fed to AI for callbacks and character development
- **Board of Directors:** Optional 2-3x/month expert interviews (Attia, Huberman, Norton, Walker) for milestone events
- **Output:** Email newsletter + S3 blog post + DynamoDB storage (`chronicle` partition)
- **Blog:** `https://blog.averagejoematt.com/` — CloudFront `E1JOC1V6E6DDYI`, public, editorial design
- **Schedule:** Wednesday 7:00 AM PT (EventBridge `wednesday-chronicle`)
- **About page:** Elena Voss bio with Polly neural audio introduction

### Buddy Accountability Page (live as of 2026-03-01, v2.61.0)
- **URL:** `https://buddy.averagejoematt.com/` — mobile-first, dark mode, Outfit font
- **Purpose:** Engagement-based monitoring for accountability partner Tom (Singapore, async timezone)
- **Beacon system:** Green/Yellow/Red based on data silence (not metrics). Conservative — green is default
- **4 signals:** Food Logging, Exercise, Routine, Weight — each with status dot + plain English
- **Food logging:** Fallback chain `total_calories_kcal` → `calories` → `energy_kcal` (MacroFactor field compat)
- **Exercise:** Monday–Sunday weekly count (resets Monday, not rolling 7-day). Grace period Mon/Tue for 0 sessions.
- **Activity dedup:** `_dedup_activities()` removes WHOOP+Garmin duplicates at read-time
- **Activity highlights:** Last 4 workouts | **Food snapshot:** Weekly calorie/protein avg
- **Journey progress:** Days elapsed, lbs lost, % to goal
- **Tom's prompt:** Action guidance based on beacon state (green = be a mate, yellow = casual nudge, red = reach out)
- **Subtitle:** "Thank you for looking out for me!" with PST timestamp
- **Data:** `buddy/data.json` generated daily by Daily Brief Lambda (7-day lookback)
- **Auth:** Separate Lambda@Edge function (`life-platform-buddy-auth`), separate Secrets Manager secret
- **CloudFront:** `d1empeau04e0eg.cloudfront.net` (ID: `ETTJ44FT0Z4GO`), PriceClass_100, HTTP/2+3
- **Deploy note:** Always invalidate CloudFront after S3 updates (`/buddy/*`)
- **Cost:** ~$0/month

### Board of Directors — Centralized Expert Panel (live as of v2.56.0)
- **Config:** `s3://matthew-life-platform/config/board_of_directors.json`
- **13 members:** 5 fictional advisors (Chen, Webb, Park, Okafor, Rodriguez) + 1 meta (The Chair) + 6 real experts (Norton, Patrick, Attia, Huberman, Conti, Murthy) + 1 narrator (Elena Voss)
- **Per-member schema:** name, title, type, emoji, color, domains, data_sources, voice (tone/style/catchphrase), principles, relationship_to_matthew, focus_areas, features (per-Lambda config)
- **MCP tools:** `get_board_of_directors` (view/filter), `update_board_member` (add/edit), `remove_board_member` (soft/hard delete)
- **Module:** `mcp/tools_board.py` — S3-backed CRUD, mirrors `config/profile.json` pattern
- **Shared utility:** `lambdas/board_loader.py` — S3 read with 5-min cache, feature filtering, prompt assembly
- **Phase 2 (v2.57.0, complete):** All 5 Lambdas refactored to load personas from config. Each has config-driven builder + hardcoded fallback. Deploy: `deploy/deploy_board_centralization.sh`

### Web Dashboard Phase 2 (live as of 2026-02-27)
- **Daily Dashboard** (`index.html`): S3 static HTML — mobile-first, dark mode, 6 tiles, sparklines, auto-refresh 30min
- **Clinical Summary** (`clinical.html`): white-background, print-optimized, 9 sections for doctor visits
  - Vitals, DEXA, Labs (full biomarker table + persistent flags), Supplements, Sleep, Activity, Glucose, Genome
  - `clinical.json` generated weekly by Sunday Digest Lambda
- **CloudFront** + ACM certificate: `https://dash.averagejoematt.com/`
  - OriginPath `/dashboard`, HTTP/2+3, redirect HTTP→HTTPS
- Navigation bar links both views
- Cost: ~$0.01/month (S3 + CloudFront free tier)

### Email Cadence
| Email | Schedule | Status |
|-------|----------|--------|
| Daily Brief v2.2 | 10:00 AM PT daily | ✅ Live |
| Weekly Digest v4.2 | Sunday 8:30 AM PT | ✅ Live |
| **Brittany Weekly** | **Sunday 9:30 AM PT** | **✅ Live** |
| Monthly Digest | 1st Sunday 8:00 AM PT | ✅ Live |
| Anomaly Detector | 8:05 AM PT daily | ✅ Live |
| Freshness Alerter | 9:45 AM PT daily | ✅ Live |
| Nutrition Review | Saturday 9:00 AM PT | ✅ Live |
| Wednesday Chronicle | Wednesday 7:00 AM PT | ✅ Live |
| The Weekly Plate | Friday 6:00 PM PT | ✅ Live |

### Ingestion Schedule (PT)
```
6:00 AM   Whoop, Garmin, Notion Journal
6:15 AM   Withings, Habitify
6:30 AM   Strava, Journal Enrichment
6:45 AM   Todoist
7:00 AM   Eight Sleep
7:30 AM   Activity Enrichment
8:00 AM   MacroFactor (also: Dropbox poll every 30 min)
9:00 AM   MCP cache warmer
9:30 AM   Whoop recovery refresh (today's data)
9:35 AM   Character Sheet compute (reads yesterday's data, stores to DDB)
9:40 AM   Daily Metrics compute (day grade, readiness, streaks, TSB, HRV, weight → computed_metrics)
9:45 AM   Freshness check
10:00 AM  Daily Brief email (reads character_sheet record)
2:00 PM   Dashboard refresh (lightweight, no AI — updates weight/glucose/zone2/TSB/buddy)
6:00 PM   Dashboard refresh (lightweight, no AI — updates weight/glucose/zone2/TSB/buddy)
```

---

## Known Issues

| Issue | Severity | Notes |
|-------|----------|-----------|
| **Strava multi-device duplicates (ingestion)** | Low | Dedup runs in daily brief (v2.22.2) but raw Strava records still store duplicates. Fix at ingestion level would benefit MCP tools too. |
| **Habit data gap** | Low | 2025-11-10 → 2026-02-22 (Chronicling stopped, Habitify not yet started). Historical gap, no fix possible. |
| **Strava HR zones** | Low | `/activities/{id}/zones` returns HTTP 402 (requires Strava Summit subscription). Schema preserved for future. |
| **Garmin gap** | Low | 2026-01-19 → 2026-02-23 (app sync issue). Daily Lambda fills going forward. Backfill complete from 2026-02-23. |
| **MacroFactor data recency** | Low | Real data from 2026-02-22 only. Correlation tools need more history to be meaningful. |
| **VO2 max** | Info | Apple Health proxy unreliable; no validated measurement source. |
| **html_builder.py further split** | P3 | html_builder.py is ~1,000 lines. Could be split into section builders (_build_sleep_section, etc.) for further readability. No urgency — main lambda is clean. |
| **Stale SECRET_NAME env var audit** | P3 | Dropbox-poll incident revealed that Lambdas with explicit SECRET_NAME env vars are latent risks after secret consolidation. Audit remaining Lambdas for any stale overrides. |}

---

## Feature Roadmap (51 items)

> 💰 = estimated monthly cost increase as % of $20 budget. Features marked ⚠️ COST exceed 10% ($2+/mo) — approve before building.

### Tier 1 — High Impact, Ready Now

| # | Item | Description | Effort | 💰 |
|---|------|-------------|--------|----|
| ~~26~~ | ~~**🎮 Character Sheet — Gamified Life Score**~~ | Persistent Character Level (1-100) composed of 7 weighted pillars (Sleep 20%, Movement 18%, Nutrition 18%, Mind 15%, Metabolic 12%, Consistency 10%, Relationships 7%). XP system, tier names (Foundation→Elite), cross-pillar buffs/debuffs, asymmetric leveling (5d up / 7d down). Baseline: 2026-02-22 at Level 1 (302lb). Config: `config/character_sheet.json` in S3. Pixel-art RPG avatar with 5 tier variants + pillar badges. Daily Brief, dashboard radar chart, buddy page, Chronicle hooks. 3 MCP tools + `character_engine.py`. Board-reviewed, spec: `docs/archive/SPEC_CHARACTER_SHEET.md`. | 18-24 hr (4-6 sessions) | ~$0 |
| 1 | **Monarch Money** | Financial stress pillar. Monthly spend, savings rate, net worth, category trends. `setup/setup_monarch_auth.py` exists. Correlate spending patterns with stress/sleep. | 4-6 hr | ~$0 |
| 2 | **Google Calendar** | Demand-side data — the #1 remaining gap (North Star #2). Meeting load, deep work blocks, back-to-back density, travel days. Correlate cognitive load with recovery, sleep, journal mood. | 6-8 hr | ~$0 |
| ~~3~~ | ~~**Health trajectory projections**~~ | Longitudinal modeling: weight goal date, metabolic health age, Zone 2 capacity at 40/50/60, ASCVD 10-year projection, biomarker slopes → intervention urgency. MCP tool + monthly digest section. | 4-6 hr | ~$0 |
| ~~4~~ | ~~**Strava ingestion dedup**~~ | Fix known issue: dedup at ingestion level (not just daily brief). Benefits all MCP tools, removes double-counted activities from training load, Zone 2, exercise-sleep correlation. | 2-3 hr | $0 |
| ~~5~~ | ~~**N=1 experiment framework**~~ | Track protocol changes (new supplement, diet shift, sleep hygiene tweak) with start/end dates, then auto-compare before/after across all metrics. The "did this actually work?" tool. Board of Directors evaluates each experiment. | 6-8 hr | ~$0 |

### Tier 2 — Medium Impact, High Value

| # | Item | Description | Effort | 💰 |
|---|------|-------------|--------|----|
| ~~6~~ | ~~**Sleep environment optimization**~~ | Correlate Eight Sleep bed temperature settings with sleep outcomes. Find your optimal thermal profile. | 3-4 hr | $0 |
| ~~7~~ | ~~**Readiness-based training recommendations**~~ | Auto-suggest workout type/intensity from recovery state + training load + muscle recency. | 4-6 hr | ~$0 |
| ~~8~~ | ~~**Heart rate recovery tracking**~~ | Post-exercise HR drop from Strava HR streams. Strongest exercise-derived mortality predictor. | 3-4 hr | $0 |
| ~~9~~ | ~~**Supplement & medication log**~~ | 3 MCP tools: log, view, correlate supplements with health metrics. DynamoDB partition. | 3-4 hr | $0 |
| ~~10~~ | ~~**Weather & seasonal correlation**~~ | Open-Meteo fetch+cache in MCP tool. Correlates 7 weather vars with health+journal. | 3-4 hr | $0 |
| ~~11~~ | ~~**Training periodization planner**~~ | Mesocycle detection, deload triggers, polarization check, progressive overload. | 4-6 hr | $0 |
| ~~12~~ | ~~**Social connection scoring**~~ | Mine journal entries for social interaction quality/frequency. Haiku enrichment adds social_connection_score per entry. Trend over time. Seligman PERMA: relationships are the #1 wellbeing predictor. | 2-3 hr | ~$0 |
| 13 | **Annual health report** | Year-in-review email (Jan 1): full-year trends across every domain, biggest wins, areas of concern, Board of Directors annual assessment, goal-setting for next year. The "annual physical" email. | 4-6 hr | ~$0 |

### Tier 3 — Infrastructure & Polish

| # | Item | Description | Effort | 💰 |
|---|------|-------------|--------|----|
| ~~53~~ | ~~**Daily Brief compute refactor**~~ ✅ | Daily Brief compute refactor: `daily-metrics-compute` Lambda at 9:40 AM PT, `SOURCE#computed_metrics` DDB partition, Brief reads pre-computed values with inline fallback. v2.82.0. | ~~4-6 hr~~ | $0 |
| 14 | **⚠️ COST: WAF rate limiting** | Basic rate rule on Lambda Function URL. Protects against abuse/runaway costs. | 1 hr | **⚠️ +$5/mo (25%)** |
| ~~15~~ | ~~**MCP API key rotation**~~ | 90-day Secrets Manager auto-rotation with Lambda rotator function. Security hygiene. | 30 min | ~$0 |
| 16 | **Grip strength tracking** | Monthly manual log via Notion. $15 dynamometer. Strongest all-cause mortality predictor after VO2max (Attia). Trend + percentile vs age norms. | 2 hr | $0 |
| 17 | **Insights GSI** | Add DynamoDB GSI on `status` field if coaching insights partition exceeds 500 items. Future-proofing. | 1 hr | ~$0.25/mo |
| ~~18~~ | ~~**Automated threshold learning**~~ | Replace static anomaly thresholds with personalized baselines computed from rolling 30-day history. Each metric gets its own "normal" range. Reduces false positives. | 3-4 hr | $0 |
| ~~19~~ | ~~**Data export & portability**~~ | ~~One-click full data dump: all DynamoDB items → JSON/CSV in S3. Monthly automated backup beyond PITR. Your data, your ownership.~~ | ~~2-3 hr~~ | ~~$0.10/mo~~ |
| 20 | **MCP tool response compression** | Gzip large tool responses before sending over MCP bridge. Reduces latency for data-heavy tools (food_log, activity search, lab trends). | 1-2 hr | $0 |
| 54 | **LLM provider failover (OpenRouter)** | Add retry-with-fallback pattern to all email Lambdas: try Anthropic first, catch 5xx errors, fall back to OpenRouter (which also carries Claude models, so quality is preserved; GPT-4 as last resort). One shared `llm_client.py` utility, `OPENROUTER_API_KEY` in Secrets Manager. Primary value: pattern study for enterprise AI redundancy — same thinking applies to any critical workflow with a single-vendor AI dependency. | 2-3 hr | ~$0 |

### Tier 4 — Big Features (multi-session)

| # | Item | Description | Effort | 💰 |
|---|------|-------------|--------|----|
| ~~21~~ | ~~**Insight email parser**~~ | SES inbound: reply "track this" to daily brief → auto-save as coaching insight. Zero-friction capture from inbox. | 4-6 hr | ~$0 |
| ~~22~~ | ~~**⚠️ COST: Web dashboard**~~ | **Phase 1+2 complete (v2.39.0).** Daily dashboard + clinical summary + CloudFront + `dash.averagejoematt.com`. | ~~12-20 hr~~ | **~$0.01/mo** |
| ~~23~~ | ~~**Travel & jet lag detection**~~ | 3 MCP tools (log_travel, get_travel_log, get_jet_lag_recovery). Anomaly detector v2.1.0 travel-aware suppression. Daily brief travel banner with Huberman jet lag protocol. | ~~4-6 hr~~ | $0 |
| ~~24~~ | ~~**Blood pressure home monitoring**~~ | 2 MCP tools (BP dashboard, BP correlation). Webhook v1.4.0 BP metrics + S3 individual readings. Daily brief BP tile. Ready when BP cuff syncs to Apple Health. | ~~3-4 hr~~ | $0 |
| ~~25~~ | ~~**Meditation & breathwork tracking**~~ | Apple Health mindful minutes + dedicated app integration. Correlate practice consistency with HRV, stress scores, sleep onset latency, journal mood. Huberman: NSDR and physiological sigh are highest-ROI protocols. | 3-4 hr | $0 |

### Tier 5 — Board of Directors Recommendations (March 2026)

> Proposed by the Board during a full-panel feature review session. Grouped by sponsoring member. Focus: closing the data gap on Pillars 6 (Mind) and 7 (Relationships), and deepening existing physical health intelligence.

| # | Item | Sponsor | Description | Complexity | Effort | 💰 |
|---|------|---------|-------------|------------|--------|----|
| 27 | **Lactate threshold estimation** | Chen | Proxy lactate curve from HR drift during Zone 2 sessions over time. Track cardiac drift slope across repeated steady-state efforts to estimate aerobic threshold shift without lab testing. New MCP tool `get_lactate_estimate`. Requires Strava HR streams + Garmin. | Medium | 3-4 hr (1 session) | $0 |
| 28 | **Exercise variety scoring** | Chen | Movement pattern diversity index. Flag when same 3 activity types repeat for 4+ weeks. Suggest novel movement patterns (swimming, rowing, mobility) to prevent adaptation plateaus and overuse. MCP tool + Daily Brief nudge. | Low | 2-3 hr (1 session) | $0 |
| ~~29~~ | ~~**Meal-level glycemic response database**~~ | Webb | ~~Auto-match MacroFactor meals to CGM glucose curves. Build personal food response ranking — which of YOUR meals spike you, which don't. Postprandial AUC per meal, personal food leaderboard. Extends existing `get_glucose_meal_response` with persistent per-food scoring.~~ | ~~High~~ | ~~6-8 hr (2 sessions)~~ | $0 |
| 30 | **Hydration tracking enhancement** | Webb | Fix incomplete Apple Health water sync (known issue). Add hydration adequacy scoring: bodyweight-adjusted target, deficit alerts, correlation with energy/headaches/exercise performance. Habitify habit bridge for manual logging fallback. | Medium | 3-4 hr (1 session) | $0 |
| 31 | **Light exposure tracking** | Park | Morning sunlight habit via Habitify ("Outdoor light 10+ min within 30 min of waking"). Correlate with sleep onset latency, circadian consistency, and next-night sleep architecture. Huberman's #1 protocol — now measurable. MCP tool `get_light_exposure_correlation`. | Low | 2-3 hr (1 session) | $0 |
| 32 | **Nap detection & scoring** | Park | Detect daytime sleep events from Eight Sleep + Whoop. Score naps (duration, timing, type). Correlate late/long naps with same-night sleep pressure destruction. Daily Brief flag when nap timing threatens nighttime architecture. | Medium | 4-5 hr (1 session) | $0 |
| ~~33~~ | ~~**Biological age estimation**~~ | Okafor | ~~Compute PhenoAge / Levine biological age from Function Health blood panels + DEXA + HRV + CGM. Track delta between biological and chronological age across draws. The single most meaningful longevity metric. MCP tool `get_biological_age` + Monthly Digest section.~~ | ~~High~~ | ~~6-8 hr (2 sessions)~~ | $0 |
| 34 | **Decision fatigue & willpower tracking** | Rodriguez | Cross-reference Todoist task load with Habitify T0 completion rates. Find the task-count threshold above which habit compliance drops. Day-of-week and time-of-day failure patterns. Knowing-doing gap made quantifiable. Requires Todoist enrichment (pending cleanup). | Medium | 4-5 hr (1 session) | $0 |
| ~~35~~ | ~~**Temptation logging**~~ | Rodriguez | ~~Quick-capture MCP tool or Habitify habit for logging resist/succumb moments. Ratio of resisted vs. succumbed temptations over time as a leading indicator of behavioral change. No wearable captures this. MCP tool `log_temptation` + `get_temptation_trend`.~~ | ~~Low~~ | ~~2-3 hr (1 session)~~ | $0 |
| ~~36~~ | ~~**Cold/heat exposure logging & correlation**~~ | Huberman | ~~Log cold showers, sauna, cold plunge (duration, temperature, type). Correlate with same-day State of Mind valence, next-night HRV, journal mood/energy. Dopamine-proxy analysis. MCP tools `log_exposure` + `get_exposure_correlation`.~~ | ~~Low~~ | ~~3-4 hr (1 session)~~ | $0 |
| 37 | **Structured breathwork tracking** | Huberman | Differentiate NSDR, box breathing, physiological sighs, traditional meditation. Log type + duration + timing. Correlate each protocol type independently with HRV, stress, sleep onset. Extends existing meditation data with protocol-level granularity. | Medium | 3-4 hr (1 session) | $0 |
| ~~38~~ | ~~**Continuous metabolic health score**~~ | Attia | ~~Composite metabolic syndrome score from CGM + weight + waist (DEXA) + BP + fasting glucose + triglycerides + HDL. Updates daily for available metrics, quarterly cross-ref with blood panel. Trajectory of composite matters more than any individual marker. MCP tool + dashboard tile.~~ | ~~High~~ | ~~5-6 hr (2 sessions)~~ | $0 |
| 39 | **Exercise efficiency trending** | Attia | Track pace-at-HR or power-at-HR across repeated workout types. Same workout + lower HR over time = improving cardiovascular fitness. Fitness improvement signal independent of subjective effort. Requires Strava HR streams + activity type grouping. | Medium | 3-4 hr (1 session) | $0 |
| ~~40~~ | ~~**Life event tagging**~~ | Voss | ~~Structured log of birthdays, anniversaries, work milestones, social events, conflicts, losses. Creates narrative architecture for Chronicle. Connects data anomalies to actual life context ("HRV crashed the week of Mum's birthday"). MCP tool `log_life_event` + `get_life_events`. DynamoDB `life_events` partition.~~ | ~~Low~~ | ~~2-3 hr (1 session)~~ | $0 |
| ~~41~~ | ~~**Defense mechanism detector**~~ | Conti | ~~Secondary Haiku enrichment pass on journal entries. Tags psychological patterns: intellectualization, avoidance, displacement, isolation of affect, rationalization. `defense_patterns` array per journal entry. Weekly Digest Conti section references patterns. Sensitive but powerful.~~ | ~~High~~ | ~~5-7 hr (2 sessions)~~ | ~~$0.50/mo~~ |
| ~~42~~ | ~~**Contact frequency tracking**~~ | Murthy | ~~Log meaningful interactions with specific people (call, text, in-person, depth rating). Track: interactions/week, diversity of connections, trend over 30/60/90 days. Social connection dashboard. Pillar 7 finally gets real data beyond journal mining. MCP tools `log_interaction` + `get_social_dashboard`.~~ | ~~Medium~~ | ~~4-5 hr (1 session)~~ | $0 |

### Tier 6 — Technical Innovation & Platform Evolution

> Ideas from the AI/tech expert panel and Claude. Push the platform beyond data collection into intelligence, prediction, and novel interaction paradigms. Higher complexity, higher ambition.

| # | Item | Category | Description | Complexity | Effort | 💰 |
|---|------|----------|-------------|------------|--------|----|
| 43 | **Conversational AI coach (voice interface)** | Interaction | Voice-first daily check-in via iOS Shortcut → Lambda Function URL → Anthropic API. 2-minute morning conversation: Claude asks 3 targeted questions based on last night's data + today's training rec, transcribes responses, logs structured data to DynamoDB. Collapses friction between "I should journal" and doing it. | High | 8-12 hr (3 sessions) | ~$1/mo |
| 44 | **Predictive anomaly detection (ML layer)** | Intelligence | Replace threshold-based anomalies with time-series forecasting. Prophet or scikit-learn model trained on personal history predicts tomorrow's metrics. Flag when actuals deviate from *predicted* values given context (training load, sleep, meals). "Your HRV is 15% lower than expected" vs. "Your HRV is low." Weekly retrain Lambda. | Very High | 10-14 hr (3-4 sessions) | ~$0.50/mo |
| 45 | **Causal inference engine** | Intelligence | Bayesian causal graph modeling actual directional relationships between variables. Does exercise cause better sleep, or better sleep cause more exercise? DoWhy or CausalNex library. Monthly Lambda updates personal causal model from longitudinal + intervention (experiment) data. MCP tool `get_causal_graph`. | Very High | 12-16 hr (4-5 sessions) | ~$0.50/mo |
| 46 | **Digital twin / simulation layer** | Intelligence | Personal simulation model trained on YOUR response curves. Answer "what if" questions: "What if I increased Zone 2 to 4 hr/week?" "What if I cut deficit to 1000 kcal?" Projects outcomes using your actual data patterns. Requires 3-6 months of history for meaningful calibration. | Very High | 16-24 hr (5-7 sessions) | ~$1/mo |
| 47 | **Automated protocol optimization** | Intelligence | Quantitative protocol suggestions with expected outcomes. Identifies highest-leverage variable from last 30 days, proposes specific change with confidence interval. "Moving last meal from 8:30 PM to 7:00 PM has 73% probability of improving deep sleep by 8-12 min." Combines causal engine + simulation. Depends on #45 + #46. | Very High | 8-12 hr (3 sessions) | ~$0.50/mo |
| 48 | **Cross-platform semantic search (embeddings)** | Infrastructure | Vector embedding index across journal entries, Chronicle installments, Board commentary, Daily Brief text, insight emails. Semantic search: "Find every time my board mentioned protein timing" or "journal entries where I felt isolated." Anthropic embedding API or local model. Nightly index update Lambda. | High | 8-10 hr (2-3 sessions) | ~$1-2/mo |
| 49 | **Real-time dashboard (WebSocket)** | Infrastructure | API Gateway WebSocket API pushes live updates to dashboard when new data arrives. Whoop syncs at 9:30 AM → dashboard updates immediately without waiting for 10 AM brief. Turns static snapshot into living instrument panel. | High | 8-12 hr (3 sessions) | ~$0.50/mo |
| ~~50~~ | ~~**Adaptive email frequency**~~ | Intelligence | ~~System modulates its own communication cadence based on engagement + state. Great week → brief "keep it up." Rough week → leans in with detail + gentler coaching. Engagement score from email opens, journal entries, habit completion drives frequency. Chronicle shifts weekly/biweekly based on narrative density. | Medium | 5-7 hr (2 sessions) | $0 |
| 51 | **Personal knowledge graph** | Infrastructure | Graph database of relationships between health entities. Supplements → biomarkers → symptoms → journal themes → life events. Traverse: "what downstream effects does magnesium have?" Neo4j free tier or DynamoDB adjacency lists. Monthly rebuild Lambda. MCP tool `query_knowledge_graph`. | Very High | 12-16 hr (4-5 sessions) | ~$0-5/mo |
| 52 | **Open source the framework** | Meta | Abstract platform into configurable framework others can deploy. Extract Matthew-specific configs into setup wizard. Publish: config-driven Lambda templates, single-table DynamoDB schema, MCP tool scaffolding, Board of Directors pattern, Character Sheet engine. README + docs + example configs. The blog is already building audience. | Very High | 20-30 hr (6-8 sessions) | $0 |

---

### 🏛️ Board of Directors — Full Stack Ranking

> The Board convened to stack-rank all 26 new proposals (16 Board + 10 Tech) plus remaining original roadmap items. Evaluation criteria: (1) Does it reduce the gap between knowing and doing? (2) Does it fill a data blind spot? (3) Is the data available or nearly available? (4) Is the effort justified by the insight gained?

**The Chair's opening statement:** *"We have 105 tools and roughly 90 serve Pillars 1-5. Pillars 6 and 7 — the ones that determine whether this transformation sticks — have the thinnest data coverage. The ranking reflects that imbalance."*

| Rank | # | Feature | Champion(s) | Rationale |
|------|---|---------|-------------|-----------|
| 1 | ~~40~~ | ~~**Life event tagging**~~ ✅ | Voss, Conti, The Chair | Low effort, massive unlock. Every board member needs life context to interpret data anomalies. Without this, we're explaining numbers without meaning. 2-3 hours to deploy, benefits every downstream consumer forever. |
| 2 | ~~42~~ | ~~**Contact frequency tracking**~~ ✅ | Murthy, Rodriguez, The Chair | Pillar 7 (Relationships) is weighted 7% in the Character Sheet but has zero structured data input. This is a measurement gap for the pillar most correlated with longevity. Murthy: "You cannot improve what you do not measure, and Matthew has measured everything except the thing that matters most." |
| 3 | 31 | **Light exposure tracking** | Park, Huberman | Zero-cost Habitify habit, 2-3 hours to build correlation tool. Huberman's #1 protocol recommendation is currently unmeasured. Park can correlate it with sleep onset immediately. Highest ROI per hour of build time on this list. |
| 4 | 16 | **Grip strength tracking** | Okafor, Attia, Chen | $15 dynamometer, 2 hours to build. Strongest all-cause mortality predictor after VO2 max. Already on roadmap — the Board is elevating urgency. Buy the dynamometer this week. |
| 5 | ~~35~~ | ~~**Temptation logging**~~ ✅ | Rodriguez, Conti | Captures the moment of choice — the exact point where knowing-doing gap lives. No wearable can see this. Low effort, unique data stream. Rodriguez: "This is the only metric that measures willpower directly." |
| 6 | ~~41~~ | ~~**Defense mechanism detector**~~ ✅ | Conti, Voss, Rodriguez | Higher effort but transformative. Journal enrichment already runs via Haiku — adding a defense-pattern pass is incremental. Conti: "The platform itself is a defense mechanism. Understanding that isn't a criticism — it's the next level of self-awareness." |
| 7 | ~~36~~ | ~~**Cold/heat exposure logging**~~ ✅ | Huberman, Park, Chen | Low effort, fills a protocol gap. Huberman's deliberate cold exposure research is directly testable with existing HRV + sleep data. Just needs the input logging. |
| 8 | ~~33~~ | ~~**Biological age estimation**~~ ✅ | Okafor, Attia, Patrick | The single most meaningful longevity number. You have 7 blood draws + DEXA + HRV + CGM. Computing PhenoAge gives Okafor a real trajectory target. Higher effort but anchors the entire longevity conversation. |
| 9 | 2 | **Google Calendar** | Rodriguez, The Chair | Demand-side data is North Star gap #2. Cognitive load affects every pillar. Rodriguez needs it for decision fatigue analysis (#34). Already on roadmap Tier 1 — Board affirms priority. |
| 10 | 43 | **Conversational AI coach** | Rodriguez, Conti, Park | The most innovative friction-reducer on the list. Morning voice check-in captures subjective data that Matthew won't type. Conti: "The best therapeutic tool is one that meets you where you are. A 2-minute voice conversation is that." |
| 11 | ~~38~~ | ~~**Continuous metabolic health score**~~ ✅ | Attia, Okafor, Patrick | Composite score gives a single number for metabolic trajectory. Attia: "Stop looking at 15 metrics. Give me one number that tells me if you're getting healthier or sicker." Higher effort but high daily utility. |
| 12 | ~~29~~ | ~~**Meal-level glycemic response database**~~ ✅ | Webb, Attia, Patrick | Personal food ranking is the holy grail of CGM data. You already have the pieces (MacroFactor + CGM + glucose_meal_response tool). This connects them permanently. |
| 13 | ~~50~~ | ~~**Adaptive email frequency**~~ ✅ | The Chair, Voss | Medium effort, addresses engagement sustainability. 8 emails/week risks fatigue. Smart modulation prevents the platform from becoming noise. The Chair: "The system should know when to speak and when to listen." |
| 14 | 1 | **Monarch Money** | Rodriguez, Okafor, The Chair | Financial stress is unmeasured. North Star gap #5. Already has setup script. The Board sees financial anxiety as a confound in every other pillar. |
| 15 | 28 | **Exercise variety scoring** | Chen, Park | Low effort, prevents staleness. Chen: "Adaptation is the enemy of progress. Novelty is the cheapest performance enhancer." |
| 16 | 39 | **Exercise efficiency trending** | Chen, Attia | Pace-at-HR over time is the purest fitness signal. Medium effort, very clear insight. |
| 17 | 34 | **Decision fatigue tracking** | Rodriguez, The Chair | Powerful but depends on Todoist cleanup (pending Matthew action). Deferred until Todoist is organized. |
| 18 | 37 | **Structured breathwork tracking** | Huberman, Park | Useful but incremental over existing meditation tracking. Medium priority. |
| 19 | 48 | **Cross-platform semantic search** | Voss, Conti, The Chair | Powerful for long-term narrative mining. Growing corpus makes this more valuable over time. But not urgent at 10 days of data. Revisit at 3 months. |
| 20 | 30 | **Hydration tracking enhancement** | Webb, Chen | Real gap but blocked by Apple Health sync reliability (known issue). Fix the pipe before building analysis. |
| 21 | 44 | **Predictive anomaly detection** | Okafor, Chen, Park | Excellent upgrade but needs 3+ months of data for meaningful training. Premature now. Revisit May. |
| 22 | 27 | **Lactate threshold estimation** | Chen, Attia | Interesting but proxy-heavy and Matthew's training base is still early. More valuable at 6+ months of Zone 2 data. |
| 23 | 32 | **Nap detection & scoring** | Park | Niche use case until Matthew's sleep routine stabilizes. Park: "Let's fix nighttime sleep first." |
| 24 | 13 | **Annual health report** | Okafor, The Chair | High value but not deployable until January 2027. Design spec can wait until Q4. |
| 25 | 49 | **Real-time WebSocket dashboard** | — | Cool but overengineered for a single-user platform with 2 daily refreshes. Current S3 static model works fine. |
| 26 | 45 | **Causal inference engine** | Okafor, Attia | Intellectually exciting, practically premature. Needs 6+ months of data + multiple completed experiments. Revisit September. |
| 27 | 51 | **Personal knowledge graph** | Okafor, Patrick | Same data maturity concern. Powerful at scale, premature now. |
| 28 | 46 | **Digital twin / simulation** | Attia, Chen | The most ambitious item. Requires causal engine (#45) + 6 months data. 2026 H2 at earliest. |
| 29 | 47 | **Automated protocol optimization** | The Chair | Depends on #45 + #46. The capstone feature — but the foundation isn't built yet. |
| 30 | 52 | **Open source the framework** | The Chair, Voss | Voss: "The blog audience would love this." The Chair: "But Matthew hasn't finished building it for himself yet. Ship for one before shipping for many." 2026 H2 or 2027. |

**The Chair's closing verdict:** *"The top 5 — life events, contact tracking, light exposure, grip strength, temptation logging — can all be built in under 2 weeks of sessions and would give us three entirely new data streams for Pillars 6 and 7 plus two protocol-tracking inputs Huberman and Park have been asking for. Do those first. The ML and simulation features (#44-47) are the right vision for H2 2026 once we have 6 months of longitudinal data to train on. The open-source play is a 2027 story."*

---

## Completed (Recent)

Last 5 versions shown. Full history in CHANGELOG.md / CHANGELOG_ARCHIVE.md.

| Version | What | Date |
|---------|------|------|
| v2.77.1 | Housekeeping: State of Mind resolved (iPhone permissions toggle), Phase 4 reward machinery confirmed complete, reward ideation menu generated for Matthew + Brittany. No code deployed. | 2026-03-05 |
| v2.77.0 | Daily Brief monolith extraction: html_builder.py, ai_calls.py, output_writers.py. 4,002 → 1,366 lines (66% reduction). Clean deploy confirmed. | 2026-03-05 |
| v2.76.1 | dropbox-poll fix: stale `SECRET_NAME` env var + key name mismatch from secrets consolidation. Three alarms investigated; two self-cleared. | 2026-03-05 |
| v2.76.0 | Snapshot script pagination + EventBridge keyword fixes. Four stale docs updated (COST_TRACKER, INFRASTRUCTURE, INCIDENT_LOG, USER_GUIDE → v2.75.0). `scoring_engine.py` extracted from daily_brief monolith (4,002→3,589 lines). | 2026-03-05 |
| v2.75.0 | Platform health audit + all P0/P1 fixes + Secrets consolidation (12→6, saves $2.40/mo). Chronicle + anomaly packaging fixed, dashboard-refresh IAM fixed, 5 new alarms, 10 log groups retention, MCP version corrected, weekly_digest hardcoded values fixed. | 2026-03-05 |
| v2.74.0 | Hydration pipeline fix: HAE metric map (`"Water"` added), 500ml threshold, NO DATA signal to AI prompt. Dedicated 9pm water HAE automation. 7-day backfill confirmed. | 2026-03-05 |
| v2.73.0 | Feature #50 Adaptive Email Frequency: adaptive-mode-compute Lambda (29th), tools_adaptive.py (26th module), Daily Brief banners + BoD tone. 121 tools. | 2026-03-05 |
| v2.72.0 | 5 Features: #41 Defense Mechanism Detector, #33 Biological Age, #38 Metabolic Health Score, #29 Food Response Database, #19 Data Export. New module: tools_longevity.py. 28th Lambda: data-export. 116→120 tools. | 2026-03-05 |
| v2.71.0 | Character Sheet Phase 4: rewards + protocol recs in Daily Brief HTML, character section in Weekly Digest (fixed latent NameError) | 2026-03-05 |
| v2.70.1 | State of Mind pipeline fix (deploy filename mismatch + HAE date field), universal `deploy_lambda.sh` helper | 2026-03-05 |
| v2.70.0 | Social & Behavioral Tools: 11 new MCP tools — life events (#40), contact tracking (#42), temptation logging (#35), cold/heat exposure (#36), exercise variety (#28). 4 new DDB partitions, tools_social.py module. 105→116 tools. | 2026-03-04 |
| v2.69.0 | Character Sheet Phase 3: Avatar data pipeline (`_build_avatar_data()` deployed), inline email avatar, P0 IAM fix for character-sheet-compute, 30-day weight fallback | 2026-03-04 |
| v2.68.0 | Board v2.0 (+Conti +Murthy -Walker), INFRASTRUCTURE.md, CloudWatch alarm cleanup, IAM blog fix, Habitify packaging fix | 2026-03-04 |
| v2.67.0 | Chronicle Week 2 "The Empty Journal" (interview format) + Lambda packaging fix + Week 1 blog backfill | 2026-03-04 |
| v2.66.1 | Supplement Bridge: Habitify→supplements auto-bridge (21 supplements, 3 batches), SoM investigation | 2026-03-04 |
| v2.63.0 | The Weekly Plate: Friday evening food magazine email (26th Lambda), Met Market grocery lists, recipe riffs | 2026-03-03 |
| v2.62.0 | Daily Brief QA: dynamic weight context, 7-day training summary, subject date fix, readiness emoji | 2026-03-03 |
| v2.59.0 | Character Sheet Phase 2: standalone compute Lambda (25th), Daily Brief integration (HTML section + BoD context + dashboard/buddy JSON) | 2026-03-02 |
| v2.58.0 | Character Sheet Phase 1: scoring engine, 3 MCP tools (102→105), S3 config, retrocompute backfill, deploy script | 2026-03-02 |
| v2.57.0 | Board Centralization Phase 2: all 5 Lambdas config-driven via board_loader.py + S3 config, hardcoded fallbacks | 2026-03-02 |
| v2.56.0 | Board of Directors Centralization: S3 config (12 members) + 3 MCP tools (99→102) | 2026-03-01 |
| v2.55.1 | P0 bug fixes: dashboard component_details NameError + buddy IAM s3:PutObject | 2026-03-01 |
| v2.55.0 | Sleep SOT Redesign: Whoop primary (duration/stages/score), Eight Sleep retained (bed environment) | 2026-03-01 |
| v2.54.0 | Feature #15: MCP API Key Rotation (90-day auto, rotator Lambda, Bearer cache TTL) | 2026-03-01 |
| v2.53.0 | Buddy Accountability Page: buddy.averagejoematt.com (engagement-based beacon, mobile-first, Tom in Singapore) | 2026-03-01 |
| v2.52.0 | Wednesday Chronicle Blog Launch + Dashboard Auth Fix | 2026-03-01 |
| v2.51.0 | Weekly Nutrition Review Email (Sonnet 4.5, Norton/Patrick/Attia panel) | 2026-02-28 |
| v2.48.0 | P0 expert review fixes (config.py, reserved concurrency, log retention, DLQ purge) + doc sprint (8 stale docs updated) | 2026-02-28 |
| v2.47.2 | Expert review (8 phases), audit framework (snapshot script + review runbook), smoke test template, deploy manifest, habit scores backfill | 2026-02-28 |
| v2.47.1 | P0 ingestion fix (5 Lambdas), freshness checker update, PIR, process improvements | 2026-02-28 |
| v2.47.0 | Habit Intelligence: 65-habit registry, tier-weighted scoring, 3 new MCP tools (94↗97), habit_scores DDB partition | 2026-02-28 |
| v2.46.0 | Gap-aware backfill on all 6 API ingestion Lambdas (LOOKBACK_DAYS=7) | 2026-02-28 |
| v2.44.0 | Remote MCP Connector: Streamable HTTP transport (spec 2025-06-18) — claude.ai + mobile access via Function URL | 2026-02-28 |
| v2.43.0 | Engineering Hardening: MCP monolith split (21 modules), 19 Lambda parameterization, DLQ coverage 20/22, anomaly detector fix | 2026-02-28 |
| v2.42.0 | Infrastructure Hardening: P0-P1 expert review fixes (API key rotation, env var parameterization, runtime standardization) | 2026-02-28 |
| v2.41.0 | Feature #25: State of Mind / How We Feel integration (1 new MCP tool, webhook v1.5.0) | 2026-02-27 |
| v2.40.0 | Features #23 & #24 — Travel Detection (3 tools + anomaly suppression) + Blood Pressure Monitoring (2 tools + webhook v1.4.0) | 2026-02-27 |
| v2.39.0 | Feature #22 Phase 2 — Clinical Summary + CloudFront + custom domain (dash.averagejoematt.com) | 2026-02-27 |
| v2.38.0 | Feature #22 Phase 1 — Web Dashboard (S3 static site, 6 tiles, sparklines, Daily Brief integration) | 2026-02-27 |
| v2.37.0 | Features #12 (social), #18 (anomaly v2), #21 (email parser), #25 (meditation) — 3 new MCP tools, 1 new Lambda, anomaly detector v2.0 | 2026-02-27 |
| v2.36.0 | Features #9 (supplements), #10 (weather), #11 (periodization) — 5 new MCP tools, 2 new DDB sources | 2026-02-26 |
| v2.35.0 | Features #6 (sleep env), #7 (training rec), #8 (HR recovery) — 3 new MCP tools + 2 Lambda enhancements | 2026-02-26 |
| v2.33.0 | MCP hotfix (NameError + get_table), memory 512→1024 MB, cache warmer 6→12 tools | 2026-02-26 |
| v2.32.0 | Fasting glucose validation tool — overnight/deep nadir, lab comparison, bias analysis | 2026-02-26 |
| v2.31.0 | Derived Metrics Phase 1f (ASCVD risk) + Phase 2c (day type analysis), 60→61 tools | 2026-02-26 |
| v2.30.0 | Derived Metrics Phase 1c-1e: CGM optimal %, protein distribution, micronutrient sufficiency | 2026-02-26 |
| v2.29.0 | Derived Metrics Phase 1a-1b: sleep onset consistency, body comp deltas, Board review | 2026-02-26 |

---

## Architecture Notes

- Single DynamoDB table: PK `USER#matthew#SOURCE#<source>`, SK `DATE#YYYY-MM-DD` (+ suffixes for journal, day_grade)
- Source-of-truth domain ownership prevents double-counting across overlapping sources
- MCP server Lambda = API server + nightly cache warmer (EventBridge payload distinguishes)
- 400KB item size limit watch: Strava activities, MacroFactor food_log nested in day items
- No GSI by design — all access by user+source+date
- Cache warmer: 12 tools pre-computed nightly at 9 AM PT; tools check DDB cache before computing
- PITR enabled (35-day rolling recovery)
- Full architecture details: ARCHITECTURE.md
- Full schema details: SCHEMA.md

---

## North Star

The platform coaches Matthew toward the version of himself he wants to be at 36, 46, 56, and 66. Every feature evaluated against: *does this reduce the gap between knowing and doing?*

**Remaining gaps:**
1. ~~Subjective layer~~ — Notion journal Phases 1-4 all live ✔️
2. **No demand-side data** — health inputs tracked but not cognitive/social load → Google Calendar (#2) ~~Social connection (#12)~~ ✔️
3. ~~**Glucose meal response**~~ — deployed v2.26.0 ✔️
4. ~~**Grade trending**~~ — 947 historical grades backfilled ✔️ + Weekly Digest v4.2 live with grade trends ✔️
5. **No financial data** — financial stress is a health lever → Monarch Money (#1)
6. ~~**No "did it work?" loop**~~ — N=1 experiments deployed v2.34.0 ✔️ (Supplement log (#9) enhances this further)
7. ~~**No forward-looking intelligence**~~ — Health trajectory deployed v2.34.0 ✔️ (Training periodization (#11) adds depth)
