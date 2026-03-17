# Life Platform — Sprint Plan
**Board-Aligned Implementation Roadmap | v3.7.69 | March 17, 2026**
*Derived from Joint Board Summit Record (March 15, 2026) + Board Sprint Review (March 16, 2026)*

---

## Overview

This document translates the Board Summit recommendations into an ordered, realistic implementation plan for a solo developer at ~12-15 hours/week. Sprints 1-2 are 2 weeks each. Sprints 3-4 are 4 weeks each. A SIMP-1 Phase 2 mini-sprint occurs between Sprint 2 and Sprint 3 (~April 13).

**Effort Scale:** XS <1h | S 1-3h | M 4-6h | L 7-10h | XL 10h+

**Model Assignments:** "None" = pure computation or infrastructure Lambda, no LLM call. Sonnet = structured scoring/display/routing. Opus = multi-signal reasoning, narrative interpretation, clinical/behavioral judgment.

---

## SPRINT 1 — Weeks 1-2 — ✅ COMPLETE (v3.7.55)
**Theme: Foundation + Audience**
**Capacity: ~20h | Load: ~19h**

| ID | Feature | Effort | Model | Deliverable | Champion |
|----|---------|--------|-------|-------------|----------|
| BS-01 | **Essential Seven Protocol** — Dedicated MCP tool returning only T0 habits (calorie goal, hydrate 3L, morning sunlight, no alcohol, no marijuana, primary exercise, walk 5K) with streak counts + failure analysis. Website homepage component showing only these 7, visually distinct from all other habits. | M (5h) | Sonnet | MCP: `get_essential_seven()` tool. Website: homepage section with streak flames, last-fail date. | Clear |
| BS-02 | **Website Hero Redesign** — Replace current hero with transformation story format. Prerequisites: write the 50-word "why should you care" paragraph first. Live weight counter (302→current→185 goal), one sentence narrative, scroll invitation. Below fold: days on journey + current streak + most recent Chronicle headline. | M (4h) | None (static + S3 fetch) | Updated index.html. New public_stats.json endpoint on site_api. | Moreau |
| BS-03 | **Chronicle → Email Pipeline** — Automate Weekly Chronicle delivery to email subscribers. Subscribe backend is LIVE (v3.7.60). Build: Chronicle Lambda writes formatted HTML email to SES, triggers subscriber list send, posts to /journal. 500-word max per Jordan Kim's format directive. | S (3h) | Sonnet | Lambda: `chronicle-email-sender`. SES template. Triggered post-Chronicle-generation. | Kim / Marcus |
| BS-05 | **AI Confidence Scoring** — 3-level badge (High/Medium/Low) on every AI-generated insight. Prerequisite: write confidence criteria spec per Henning (n, effect size, CI, freshness requirements per insight type). Apply badge to: Daily Brief insights, Weekly Chronicle claims, hypothesis outputs. Display in email + MCP responses. | M (4h) | Sonnet | Spec doc first. `confidence_scorer.py` in shared layer. Badge field `_confidence` on all AI outputs. | Henning |
| BS-09 | **ACWR Training Load Model** — Compute acute:chronic workload ratio daily from Whoop strain + Strava distance/duration + Hevy volume load. Alert >1.3 (injury zone) or <0.8 (detraining zone). Daily Brief receives actionable prescription: specific volume reduction recommendation, not just flag. Write to `SOURCE#computed_metrics | METRIC#acwr`. | S (3h) | None (pure compute) | Lambda: `acwr-compute` (daily 9:30 AM PT). Alarm via SNS. DDB write. Daily Brief integration. | Attia / Jin |

**Sprint 1 Prerequisites (write before implementing):**
- [ ] BS-08 conflict resolution rules doc — which source wins which field in sleep reconciliation (Omar)
- [ ] BS-05 confidence criteria spec — per-insight-type requirements (Henning)
- [ ] BS-02 "why should you care" paragraph — 50 words, written by Matthew, not AI

**Sprint 1 Definition of Done:**
- All 5 features deployed and passing smoke tests
- `post_cdk_reconcile_smoke.sh` run after any CDK deploy
- Each new Lambda has alarm + DLQ + integration test entry
- Chronicle email sends to at least 1 test subscriber

---

## SPRINT 2 — Weeks 3-4 — ✅ COMPLETE (v3.7.63)
**Theme: Intelligence Core + Sleep Foundation**
**Capacity: ~25h | Load: ~27h (tight — de-prioritize BS-TR2 if needed)**

| ID | Feature | Effort | Model | Deliverable | Champion |
|----|---------|--------|-------|-------------|----------|
| BS-07 | **Website API Layer** — Extend existing `site_api` Lambda with new public endpoints: `/weight_progress` (daily weights last 180 days), `/character_stats` (current Character Sheet scores), `/habit_streaks` (T0 habit streaks), `/experiments` (experiment list + status). CloudFront cache TTL: 1h for stats, 24h for character. Rate-limited. No private health data. | M (4h) | None (infra) | site_api Lambda updated. 4 new routes. CloudFront cache config. | Marcus |
| BS-08 | **Unified Sleep Record** — Reconcile Whoop (staging/HRV), Eight Sleep (temperature/env), Apple Health (duration) into one canonical DDB record per night. Conflict rules: Whoop wins for staging + HRV, Eight Sleep wins for environment, Apple Health wins for total duration. Source-of-truth rules documented (Sprint 1 prereq). Nightly Lambda post-midnight. | M (5h) | None (infra) | Lambda: `sleep-reconciler` (runs 7 AM PT). DDB partition: `SOURCE#sleep_unified`. Conflict resolution spec implemented. | Omar / Huberman |
| BS-SL2 | **Circadian Compliance Score** — Pre-sleep behavioral score from: morning light exposure (journal entry check), last meal timing (MacroFactor timestamp), screen-free wind-down (journal), sleep onset vs. inferred circadian phase. Output: score 0-100 + "tonight you're set up for good/mediocre/poor sleep" — BEFORE the night happens. Write to DDB daily. Surface in Evening Nudge. | M (4h) | Sonnet | Lambda: daily at 7 PM PT. DDB: `SOURCE#circadian | DATE#`. Evening nudge integration. | Huberman |
| BS-BH1 | **Vice Streak Amplifier** — Dedicated MCP tool `get_vice_streaks()` with: current streak length, longest streak, compounding value calculation (day 30 worth 3x day 3), streak risk rating. Website homepage: prominent vice streak counter with "Day N" display, color progression (green→gold as streak grows), visible last-break date. | S (2h) | Sonnet | MCP tool. Website component. Compounding formula: value = streak^1.5 / 10. | Goggins |
| BS-MP3 | **Decision Fatigue Detector (Proactive)** — Elevate existing MCP tool to proactive alert. Extend `daily-insight-compute` Lambda: when active + overdue Todoist tasks > personal threshold (default 15) AND T0 habit completion < 60% this week → inject alert into Daily Brief: "Your decision load is elevated. Consider canceling or delegating X tasks today to protect your evening habits." No new Lambda. | S (2h) | Sonnet | `daily_insight_compute_lambda.py` updated. Config: `DECISION_FATIGUE_THRESHOLD=15`. | Clear |
| BS-TR1 | **Centenarian Decathlon Progress Tracker** — Elevate `get_centenarian_benchmarks` from one-off query to scheduled weekly write. Every Sunday after Hevy sync, map each Hevy session + Strava activity to the relevant benchmark. Write progress snapshot to DDB. Weekly Chronicle receives "progress toward your 90-year-old self" section. | S (2h) | None (compute) | Add to Sunday `weekly-correlation-compute` pipeline. DDB: `SOURCE#centenarian_progress`. | Attia |
| BS-TR2 | **Zone 2 Cardiac Efficiency Trend** — Track pace-at-heart-rate over time for repeated Zone 2 workout types (walking/hiking at 120-135 bpm). Compute weekly: for each Zone 2 session, calculate pace/speed at median HR. Store trend. Surface in Weekly Chronicle as aerobic fitness proxy. | S (2h) | None (compute) | Extend `weekly-correlation-compute`. DDB: `SOURCE#zone2_efficiency`. MCP tool update. | Patrick |
| BS-NU1 | **Protein Timing & Distribution Score** — Score each day: did protein arrive in 4+ feedings of 30g+ each, or was it front/back-loaded? Use MacroFactor per-meal data where available, infer from meal timestamps otherwise. Score 0-100. Flag days with >60g in a single feeding and <20g in any window. | S (2h) | **Opus** | Lambda: extend `daily-metrics-compute`. DDB: `SOURCE#protein_timing | DATE#`. | Norton / Patrick |

**Sprint 2 Gate: SIMP-1 Phase 2 (~April 13)**
Before Sprint 3 begins, run EMF telemetry review. Target: ≤80 tools. Dedicate 3-5h session. No new MCP tools added in Sprint 2 without Phase 2 approval.

---

## MINI-SPRINT: SIMP-1 Phase 2 (~April 13, Week 5)
**Theme: Rationalization**
**Capacity: ~5h | Load: ~5h**

- Review 30 days of EMF usage telemetry
- Identify tools with <5 calls in 30 days → deprecate or merge
- Target: 89 → ≤80 tools
- Document tool usage in MCP_TOOL_CATALOG.md
- Run full test suite post-rationalization

---

## SPRINT 3 — Weeks 6-9 — ✅ COMPLETE (v3.7.67)
**Theme: Advanced Intelligence + Website Content + Newsletter**
**Capacity: ~45h | Load: ~40h**

| ID | Feature | Effort | Model | Deliverable | Champion |
|----|---------|--------|-------|-------------|----------|
| BS-12 | **Deficit Sustainability Tracker** — Multi-signal early warning for unsustainable caloric deficit. When HRV drops >15% from 7-day baseline AND sleep quality degrades AND ≥2 T0 habits failed this week → inject into Daily Brief: "Your deficit may be too aggressive this week. Here's what the data suggests." Proactive prescription, not retrospective report. | M (5h) | **Opus** | Lambda: extend `daily-insight-compute`. Config: `DEFICIT_ALERT_THRESHOLDS`. | Norton / Attia |
| BS-SL1 | **Sleep Environment Optimizer** — Cross-reference Eight Sleep bed temperature profiles against Whoop deep sleep % and REM %. Compute personal optimal temperature curve by: season, training load day, pre-bed behaviors. Output: nightly recommendation in Evening Nudge. Requires BS-08 live. | M (5h) | **Opus** | Lambda: weekly compute + daily fetch. DDB: `SOURCE#sleep_optimizer`. Evening Nudge integration. | Attia |
| BS-MP1 | **Autonomic Balance Score** — Synthesize HRV trend (7-day), resting heart rate, respiratory rate (Whoop), sleep quality into single "nervous system state" score. Map to 4-quadrant model: flow / stress / recovery / burnout. Contextualize all other daily metrics against this quadrant in Daily Brief. | M (4h) | **Opus** | Lambda: extend `daily-metrics-compute`. DDB: `SOURCE#autonomic_state | DATE#`. | Huberman |
| BS-MP2 | **Journal Sentiment Trajectory** — Structured sentiment extraction on every journal entry: energy level, mood valence, stress mentions, gratitude signals, social references. Rolling 7-day averages. Divergence detection: sentiment declining while HRV + sleep fine → psychosocial signal. Surface in Weekly Chronicle. | M (4h) | **Opus** | Extend `journal_analysis_lambda.py`. DDB: `SOURCE#journal_sentiment | DATE#`. Chronicle integration. | Huberman |
| BS-13 | **N=1 Experiment Archive (Website)** — Public `/experiments` page. Each completed experiment: hypothesis, protocol, duration, data visualization, result, interpretation, what I'd do differently. Static S3 content initially, API-driven when API layer live. | S (3h) | None (static) | `/experiments` page. Template for experiment case studies. S3 content structure. | Patrick / Kim |
| BS-T2-5 | **Chronicle → Newsletter Delivery Pipeline** — Full automation: Chronicle generation → HTML email formatting → subscriber list delivery → web publication to /journal. SES template with header, data viz embed, one-click unsubscribe (CAN-SPAM). | M (4h) | None (infra) | Extend Lambda: `chronicle-email-sender`. Full SES template. Unsubscribe Lambda. | Elena |
| WEB-WCT | **Weekly Challenge Ticker** — Small persistent element on every page showing current week's focus challenge (e.g., "Week 4: 4+ protein feedings daily — 5/7 days"). Each past challenge links to its outcome data. Injected from site_api `/current_challenge` endpoint. | S (2h) | None (infra) | site_api endpoint. Website component (all pages). | Kim |
| IC-28 | **Training Load Intelligence (IC feature)** — Wire ACWR data (Sprint 1) into Daily Brief. When ACWR elevated, contextualize training metrics with prescriptive guidance. Cross-reference with historical injury-risk periods. | S (3h) | Sonnet | `daily_insight_compute_lambda.py` update. ACWR context injection. | Jin |
| IC-29 | **Metabolic Adaptation Intelligence (IC feature)** — TDEE tracking vs. MacroFactor adaptive estimate. When actual weight loss rate diverges from predicted, flag metabolic adaptation. Surface as: "Your effective TDEE may have dropped X calories from baseline." | M (4h) | **Opus** | Lambda: extend weekly compute. DDB: `SOURCE#metabolic_adaptation`. | Norton |

**Sprint 3 Definition of Done:**
- All features deployed + smoke tested
- Newsletter delivery tested end-to-end to real subscribers
- SIMP-1 Phase 2 complete before Sprint 3 begins

---

## SPRINT 4 — Weeks 10-13 — ✅ COMPLETE (v3.7.68)
**Theme: Website Interactive Features + Architecture**
**Capacity: ~40h | Load: ~27h (intentionally lean — slack for R17 prep)**

| ID | Feature | Effort | Model | Deliverable | Champion |
|----|---------|--------|-------|-------------|----------|
| BS-11 | **Transformation Timeline (Website)** — Scrollable interactive timeline from day 1 to today. Each data point clickable: weight measurements, key workouts, habit milestones, experiment starts/ends, Chronicle entries. Zoom from macro arc (302→185) to individual weeks. Requires BS-07 API layer (Sprint 2). | L (8h) | None (frontend) | `/live` or `/` page feature. JavaScript timeline component. API calls to site_api. | Moreau / Kim |
| WEB-CE | **Correlation Explorer (Website)** — Public, simplified cross-source correlation engine. Visitors select two variables, see actual Pearson correlation from Matthew's data, sample size, p-value. Educational tooltips. Demonstrates platform intelligence publicly. Requires BS-07 API layer. | M (5h) | None (frontend) | Website tool on `/live` or `/tools`. Pre-computed correlations from DDB. | Kim |
| BS-BM2 | **Genome-Informed Risk Dashboard** — Static but personalized page mapping Matthew's 110 SNPs to: what each means, what literature says, which metrics are most relevant to monitor. Static S3 content, updated quarterly. No compute Lambda needed — one-time Opus generation. | L (6h) | **Opus** (one-time) | `/character` or `/biology` page section. One-time Opus call from genome data. S3 static output. | Patrick |
| BS-14 | **Multi-User Data Isolation Design** — Design doc ONLY. Do not build. Schema migration path: DDB partition key prefix per user, S3 prefix-based access, Lambda shared compute / isolated data. Review all Sprint 1-3 DDB patterns against this design. Flag incompatible patterns for remediation before Sprint 5. | L (8h) | **Opus** | `docs/design/MULTI_USER_ISOLATION.md`. ADR entry. Schema migration script (not deployed). | Yael / Omar |

**Sprint 4 Notes:**
- Remaining capacity (~8-10h) → R17 Architecture Review prep
- Run `python3 deploy/generate_review_bundle.py` before R17
- R17 target: ~June 2026 (post Sprint 4)

---

## SPRINT 5 — Weeks 14-15 (Board Summit #2)
**Theme: Website + Distribution + Behavior Change**
**Capacity: ~15h | Load: ~12h**
**Source: Board Summit #2 (2026-03-17) — post-sprint review. Full record: `docs/reviews/BOARD_SUMMIT_2_2026-03-17.md`**

| ID | Feature | Effort | Model | Deliverable | Champion |
|----|---------|--------|-------|-------------|----------|
| S2-T1-1 | **MCP `Key` Import Bug Fix** — Add `from boto3.dynamodb.conditions import Key` to `tools_lifestyle.py`. Blocking `list_experiments`, `create_experiment`, `end_experiment` and others. | XS (15m) | None | One-line fix + MCP redeploy | Elena |
| S2-T1-6 | **`/story` Page** — Deep origin narrative. Where he started, what he built, why it matters. The emotional entry point that makes a stranger care enough to subscribe. Manual content by Matthew. | S (content) | None (static) | `site/story/index.html`. S3 deploy. | Moreau |
| S2-T1-7 | **`/about` Page** — Brief bio, professional context (IT leadership → solo builder), links, contact. Quick page. | XS (1h) | None (static) | `site/about/index.html`. S3 deploy. | Moreau |
| S2-T1-8 | **Email CTA on All Pages** — Consistent footer subscribe component across all 7+ site pages. Amber accent, one-line value prop, single email field. Links to `/subscribe`. | S (2h) | None (frontend) | Footer component. All pages updated. S3 deploy + invalidation. | Kim |
| S2-T1-9 | **Adaptive Deficit Ceiling** — Wire BS-12 Deficit Sustainability flags into Daily Brief with specific calorie increase recommendations. When 3+ channels degrade concurrently: "Increase by 200 kcal for 5 days, then reassess." Move from observation to prescription. | M (3h) | Sonnet | `daily_insight_compute_lambda.py` + `ai_calls.py` update. Redeploy daily-brief. | Norton / Attia |
| S2-T1-10 | **Weekly Habit Review Automation** — Every Sunday, auto-generate structured review in Daily Brief: T0 completion rates, patterns preceding misses, T1 candidates for promotion/retirement, vice streak status. | M (3h) | Sonnet | `daily_insight_compute_lambda.py` + `ai_calls.py` update. Sunday-aware logic. | Clear |
| DEPLOY | **Sprint 4 Pending Deploy** — Run `deploy/deploy_sprint4.sh`. site-api Lambda, S3 page sync, CloudFront invalidation. | S (15m) | None (ops) | 3 new API endpoints live. 3 new pages live. | Jin |
| DIST-1 | **First Distribution Event** — HN post, Twitter thread, or build log. Title suggestion: "I built a personal health AI with 19 data sources, 95 tools, and a $13/month bill." | S (content) | None | External audience discovery. Non-negotiable. | Kim / Raj |

**Sprint 5 Prerequisites:**
- Matthew writes `/story` page content (manual — this cannot be delegated to AI)
- Matthew writes `/about` page content (brief bio, can be assisted)
- Sprint 4 deploy completed before any Sprint 5 work begins

**Sprint 5 Definition of Done:**
- MCP `Key` bug fixed and MCP Lambda redeployed
- `/story` and `/about` pages live on averagejoematt.com
- Email capture CTA visible on every page
- Adaptive deficit ceiling wired into Daily Brief
- Weekly habit review generating on Sundays
- At least one external distribution event published
- Privacy policy visible on /subscribe page (Yael requirement)

---

## BACKLOG — Data-Gated

| ID | Feature | Model | Gate | Target |
|----|---------|-------|------|--------|
| BS-06 | Habit Cascade Detector — conditional probability matrix P(fail Y \| fail X within 48h) | Opus | 60+ days consistent Habitify data | ~May 2026 |
| IC-27 | Habit Cascade Intelligence IC feature | Opus | Same as BS-06 | ~May 2026 |
| BS-10 | Meal-Level CGM Response Scorer — personal food response database from CGM + MacroFactor timestamps | Opus | CGM data maturity (5+ repeats per meal type) | ~June 2026 |
| BS-BM3 | DEXA-Anchored Body Composition Model — Bayesian daily estimate between scans | Opus | DEXA scan #2 | After next DEXA |
| BS-T2-3 | DEXA-Anchored Composition Model (Tier 2) | Opus | Same as BS-BM3 | After next DEXA |
| BS-BM1 | Biomarker Trajectory Alert System — slope + 95% CI per biomarker | Opus | ≥10 blood draws (currently 7) | ~2028+ |
| BS-T2-2 | Biomarker Trajectory Engine (Tier 2) | Opus | Same as BS-BM1 | ~2028+ |
| BS-T2-6 | Decision Journal Analytics — calibration score, regret analysis | Opus | 50+ logged decisions with outcomes | ~July 2026 |
| BS-T2-7 | Experiment Results Auto-Analysis — auto before/during/after on experiment end | Opus | 5+ complete experiments | ~May 2026 |
| IC-31 | Biomarker Trajectory Intelligence IC feature | Opus | Same as BS-BM1 | ~2028+ |
| IC-30 | Sleep Environment Intelligence IC feature | Opus | BS-SL1 running 4+ weeks | ~August 2026 |

---

## BACKLOG — Time-Gated

| ID | Feature | Gate | Target |
|----|---------|------|--------|
| EMAIL-P2 | Data Drop Monthly Exclusive — full data export from one domain, email-exclusive | Month 3 of email list | **June 16, 2026** |
| EMAIL-P3 | Discord/Circle Community Launch — invite-only from email list | Month 6 of email list | **September 16, 2026** |
| BS-T3-5 | Real-Time Streaming Pipeline — EventBridge + SQS for CGM/Whoop webhooks | 180+ day horizon | ~September 2026 |
| BS-T3-6 | Cost-Optimized Multi-Tenant DynamoDB — GSI optimization, provisioned capacity | User count >10 | TBD post-commercialization |

---

## BACKLOG — Later (Lower Priority)

| ID | Feature | Model | Notes |
|----|---------|-------|-------|
| BS-15 | Board of Directors Interactive Tool (website) — "Build your own health advisory board" | Sonnet | Lead magnet; after audience established |
| WEB-NET | N=1 Experiment Template Tool — interactive experiment designer with download | Sonnet | Requires backend for session + download; underestimated; defer |
| BS-T3-1 | Authentication & User Accounts (Cognito/Auth0) | None | Commercialization prerequisite |
| BS-T3-2 | Data Source Abstraction Layer | None | Multi-user prerequisite |
| BS-T3-3 | AI Coaching Personalization Framework | Opus | Multi-user prerequisite |
| BS-T3-4 | Compliance & Data Governance (HIPAA/GDPR) | None | Commercialization prerequisite |

---

## COMPLETE FEATURE INVENTORY — All 48 Board Summit Features

| ID | Feature | Effort | Model | Assignment |
|----|---------|--------|-------|-----------|
| BS-01 | Essential Seven Protocol | M | Sonnet | **Sprint 1** |
| BS-02 | Website Hero Redesign | M | None | **Sprint 1** |
| BS-03 | Chronicle → Email Pipeline | S | Sonnet | **Sprint 1** |
| BS-04 | Pre-Computed Composite Scores | — | None | ✅ Done (ADR-025) |
| BS-05 | AI Confidence Scoring | M | Sonnet | **Sprint 1** |
| BS-06 | Habit Cascade Detector | M | Opus | Backlog (60+ days data) |
| BS-07 | Website API Layer | M | None | **Sprint 2** |
| BS-08 | Unified Sleep Record | M | None | **Sprint 2** |
| BS-09 | ACWR Training Load Model | S | None | **Sprint 1** |
| BS-10 | Meal-Level CGM Response Scorer | L | Opus | Backlog (CGM maturity) |
| BS-11 | Transformation Timeline (Website) | L | None | **Sprint 4** |
| BS-12 | Deficit Sustainability Tracker | M | Opus | **Sprint 3** |
| BS-13 | N=1 Experiment Archive (Website) | S | None | **Sprint 3** |
| BS-14 | Multi-User Data Isolation Design | L | Opus | **Sprint 4** |
| BS-15 | Board of Directors Interactive Tool | L | Sonnet | Backlog (Later) |
| BS-SL1 | Sleep Environment Optimizer | M | Opus | **Sprint 3** |
| BS-SL2 | Circadian Compliance Score | M | Sonnet | **Sprint 2** |
| BS-NU1 | Protein Timing & Distribution Score | S | **Opus** | **Sprint 2** |
| BS-TR1 | Centenarian Decathlon Progress Tracker | S | None | **Sprint 2** |
| BS-TR2 | Zone 2 Cardiac Efficiency Trend | S | None | **Sprint 2** |
| BS-BH1 | Vice Streak Amplifier | S | Sonnet | **Sprint 2** |
| BS-BM1 | Biomarker Trajectory Alert System | M | Opus | Backlog (needs 10+ draws, ~2028) |
| BS-BM2 | Genome-Informed Risk Dashboard | L | Opus | **Sprint 4** |
| BS-BM3 | DEXA-Anchored Body Composition Model | L | Opus | Backlog (needs DEXA #2) |
| BS-MP1 | Autonomic Balance Score | M | **Opus** | **Sprint 3** |
| BS-MP2 | Journal Sentiment Trajectory | M | Opus | **Sprint 3** |
| BS-MP3 | Decision Fatigue Detector (proactive) | S | Sonnet | **Sprint 2** |
| BS-T2-1 / BS-14 | Multi-User Data Isolation Architecture | L | Opus | **Sprint 4** |
| BS-T2-2 | Biomarker Trajectory Engine | M | Opus | Backlog (data-gated) |
| BS-T2-3 | DEXA-Anchored Composition Model | L | Opus | Backlog (needs DEXA #2) |
| BS-T2-5 | Chronicle → Newsletter Delivery Pipeline | M | None | **Sprint 3** |
| BS-T2-6 | Decision Journal Analytics | M | Opus | Backlog (50+ decisions) |
| **BS-T2-7** | **Experiment Results Auto-Analysis** | M | Opus | Backlog (5+ experiments) |
| BS-T3-1 | Authentication & User Accounts | L | None | Backlog (commercialization) |
| BS-T3-2 | Data Source Abstraction Layer | XL | None | Backlog (multi-user) |
| BS-T3-3 | AI Coaching Personalization Framework | XL | Opus | Backlog (multi-user) |
| BS-T3-4 | Compliance & Data Governance | XL | None | Backlog (commercialization) |
| **BS-T3-5** | **Real-Time Streaming Pipeline** | L | None | Backlog (~Sep 2026) |
| **BS-T3-6** | **Cost-Optimized Multi-Tenant DynamoDB** | L | None | Backlog (>10 users) |
| **WEB-CE** | **Correlation Explorer (Website)** | M | None | **Sprint 4** |
| **WEB-NET** | **N=1 Experiment Template Tool** | L | Sonnet | Backlog (underestimated) |
| **WEB-WCT** | **Weekly Challenge Ticker** | S | None | **Sprint 3** |
| **EMAIL-P2** | **Data Drop Monthly Exclusive** | S | None | Backlog (June 16, 2026) |
| **EMAIL-P3** | **Discord/Circle Community Launch** | S | None | Backlog (Sep 16, 2026) |
| IC-27 | Habit Cascade Intelligence | M | Opus | Backlog (data-gated) |
| IC-28 | Training Load Intelligence | S | Sonnet | **Sprint 3** |
| IC-29 | Metabolic Adaptation Intelligence | M | Opus | **Sprint 3** |
| IC-30 | Sleep Environment Intelligence | M | Opus | Backlog (after BS-SL1 4+ weeks) |
| IC-31 | Biomarker Trajectory Intelligence | M | Opus | Backlog (~2028+) |

*Items in **bold** were missing from the original PROJECT_PLAN and added in v3.7.61.*

---

## Sprint Timeline Summary

```
Week 1-2:    SPRINT 1 ✅ COMPLETE — Foundation + Audience
             BS-01 Essential Seven | BS-02 Website Hero | BS-03 Chronicle Email
             BS-05 AI Confidence Scoring | BS-09 ACWR Training Load

Week 3-4:    SPRINT 2 ✅ COMPLETE — Intelligence Core + Sleep
             BS-07 Website API | BS-08 Unified Sleep Record | BS-SL2 Circadian Score
             BS-BH1 Vice Streaks | BS-MP3 Decision Fatigue | BS-TR1 Centenarian
             BS-TR2 Zone 2 Trend | BS-NU1 Protein Timing

Week 5:      MINI-SPRINT — SIMP-1 Phase 2 Rationalization (~April 13)
             95 → ≤80 MCP tools. EMF telemetry review.

Week 6-9:    SPRINT 3 ✅ COMPLETE — Advanced Intelligence + Content
             BS-12 Deficit Tracker | BS-SL1 Sleep Optimizer | BS-MP1 Autonomic Balance
             BS-MP2 Journal Sentiment | BS-13 Experiment Archive | BS-T2-5 Newsletter
             WEB-WCT Weekly Ticker | IC-28 Training IC | IC-29 Metabolic IC

Week 10-13:  SPRINT 4 ✅ COMPLETE — Website Interactive + Architecture
             BS-11 Transformation Timeline | WEB-CE Correlation Explorer
             BS-BM2 Genome Dashboard | BS-14 Multi-User Design Doc

Week 14-15:  SPRINT 5 — Website + Distribution (Board Summit #2)
             S2-T1-1 Key bug fix | /story page | /about page | Email CTAs
             Adaptive Deficit Ceiling | Weekly Habit Review | First Distribution Event

~June 2026:  EMAIL-P2 Data Drop #1 | R17 Architecture Review
~Aug 2026:   IC-30 Sleep Environment IC (after BS-SL1 matures)
~Sep 2026:   EMAIL-P3 Community launch

Backlog activations (data-gated):
~May 2026:   BS-06 Habit Cascade (60+ days Habitify)
~May 2026:   BS-T2-7 Experiment Auto-Analysis (5+ experiments)
~June 2026:  BS-10 Meal-Level CGM Scorer
Post-DEXA:   BS-BM3, BS-T2-3 DEXA Body Composition
~July 2026:  BS-T2-6 Decision Journal Analytics (50+ decisions)
~2028+:      BS-BM1, BS-T2-2, IC-31 (need 10+ blood draws)
```

---

*Board Summit #1: March 16, 2026 | Board Summit #2: March 17, 2026 | 16 board members (Health + Technical)*
*Summit #1 record: `docs/reviews/BOARD_SUMMIT_2026-03-16.md` | Summit #2 record: `docs/reviews/BOARD_SUMMIT_2_2026-03-17.md`*
*Board Sprint Review full record: `docs/reviews/BOARD_SPRINT_REVIEW_2026-03-16.md`*
*Champions listed are advisory — Matthew Walker is the implementer*
