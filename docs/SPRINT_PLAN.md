# Life Platform — Sprint Plan
**Board-Aligned Implementation Roadmap | v3.7.83 | March 20, 2026**
*Derived from Joint Board Summit Record (March 15, 2026) + Board Sprint Review (March 16, 2026) + Architecture Review #17 (March 20, 2026) + Expert Panel Website Strategy Review (March 20, 2026)*

---

## Overview

This document translates the Board Summit recommendations into an ordered, realistic implementation plan for a solo developer at ~12-15 hours/week. Sprints 1-2 are 2 weeks each. Sprints 3-4 are 4 weeks each. A SIMP-1 Phase 2 mini-sprint occurs between Sprint 2 and Sprint 3 (~April 13).

**Effort Scale:** XS <1h | S 1-3h | M 4-6h | L 7-10h | XL 10h+

**Model Assignments:** "None" = pure computation or infrastructure Lambda, no LLM call. Sonnet = structured scoring/display/routing. Opus = multi-signal reasoning, narrative interpretation, clinical/behavioral judgment.

---

## SPRINT 1 — Weeks 1-2 — ✅ COMPLETE (v3.7.55)
**Theme: Foundation + Audience**

| ID | Feature | Effort | Model | Status |
|----|---------|--------|-------|--------|
| BS-01 | Essential Seven Protocol | M | Sonnet | ✅ Done |
| BS-02 | Website Hero Redesign | M | None | ✅ Done |
| BS-03 | Chronicle → Email Pipeline | S | Sonnet | ✅ Done |
| BS-05 | AI Confidence Scoring | M | Sonnet | ✅ Done |
| BS-09 | ACWR Training Load Model | S | None | ✅ Done |

---

## SPRINT 2 — Weeks 3-4 — ✅ COMPLETE (v3.7.63)
**Theme: Intelligence Core + Sleep Foundation**

| ID | Feature | Effort | Model | Status |
|----|---------|--------|-------|--------|
| BS-07 | Website API Layer | M | None | ✅ Done |
| BS-08 | Unified Sleep Record | M | None | ✅ Done |
| BS-SL2 | Circadian Compliance Score | M | Sonnet | ✅ Done |
| BS-BH1 | Vice Streak Amplifier | S | Sonnet | ✅ Done |
| BS-MP3 | Decision Fatigue Detector (Proactive) | S | Sonnet | ✅ Done |
| BS-TR1 | Centenarian Decathlon Progress Tracker | S | None | ✅ Done |
| BS-TR2 | Zone 2 Cardiac Efficiency Trend | S | None | ✅ Done |
| BS-NU1 | Protein Timing & Distribution Score | S | **Opus** | ✅ Done |

---

## MINI-SPRINT: SIMP-1 Phase 2 (~April 13, Week 5)
**Theme: Rationalization — 95 → ≤80 tools**

- Review 30 days of EMF usage telemetry
- Identify tools with <5 calls in 30 days → deprecate or merge
- Target: 95 → ≤80 tools
- Document tool usage in MCP_TOOL_CATALOG.md
- Run full test suite post-rationalization

---

## SPRINT 3 — Weeks 6-9 — ✅ COMPLETE (v3.7.67)
**Theme: Advanced Intelligence + Website Content + Newsletter**

| ID | Feature | Effort | Model | Status |
|----|---------|--------|-------|--------|
| BS-12 | Deficit Sustainability Tracker | M | **Opus** | ✅ Done |
| BS-SL1 | Sleep Environment Optimizer | M | **Opus** | ✅ Done |
| BS-MP1 | Autonomic Balance Score | M | **Opus** | ✅ Done |
| BS-MP2 | Journal Sentiment Trajectory | M | **Opus** | ✅ Done |
| BS-13 | N=1 Experiment Archive (Website) | S | None | ✅ Done |
| BS-T2-5 | Chronicle → Newsletter Delivery Pipeline | M | None | ✅ Done |
| WEB-WCT | Weekly Challenge Ticker | S | None | ✅ Done |
| IC-28 | Training Load Intelligence (IC feature) | S | Sonnet | ✅ Done |
| IC-29 | Metabolic Adaptation Intelligence (IC feature) | M | **Opus** | ✅ Done |

---

## SPRINT 4 — Weeks 10-13 — ✅ COMPLETE (v3.7.68)
**Theme: Website Interactive Features + Architecture**

| ID | Feature | Effort | Model | Status |
|----|---------|--------|-------|--------|
| BS-11 | Transformation Timeline (Website) | L | None | ✅ Done |
| WEB-CE | Correlation Explorer (Website) | M | None | ✅ Done |
| BS-BM2 | Genome-Informed Risk Dashboard | L | **Opus** (one-time) | ✅ Done |
| BS-14 | Multi-User Data Isolation Design | L | **Opus** | ✅ Done |

---

## SPRINT 5 — Weeks 14-15 — ✅ COMPLETE (buildable)
**Theme: Website + Distribution + Behavior Change**
**Source: Board Summit #2 (2026-03-17) + Website Strategy Review (2026-03-18)**

| ID | Feature | Effort | Model | Deliverable | Status |
|----|---------|--------|-------|-------------|--------|
| S2-T1-1 | **MCP `Key` Import Bug Fix** | XS (15m) | None | One-line fix + MCP redeploy | ✅ Done (v3.7.72) |
| S2-T1-6 | **`/story` Page structure** | S | None (static) | `site/story/index.html` | ✅ Structure done (v3.7.75). **Content pending (Matthew).** |
| S2-T1-7 | **`/about` Page** | XS (1h) | None (static) | `site/about/index.html` | ✅ Done (v3.7.72) |
| S2-T1-8 | **Email CTA on All Pages** | S (2h) | None (frontend) | Footer component on all pages | ✅ Done (v3.7.72) |
| S2-T1-9 | **Adaptive Deficit Ceiling** | M (3h) | Sonnet | Daily Brief integration | ✅ Done (v3.7.72) |
| S2-T1-10 | **Weekly Habit Review Automation** | M (3h) | Sonnet | Sunday-aware logic in daily-brief | ✅ Done (v3.7.72) |
| DEPLOY | **Sprint 4 Pending Deploy** | S (15m) | None (ops) | site-api, S3 sync, CloudFront | ✅ Done (v3.7.72) |
| WR-24 | **Subscriber gate on /ask/** | S | None | 3 anon / 20 sub q/hr, in-memory rate limit | ✅ Done (v3.7.80/82) |
| S2-T2-2 | **"What Would My Board Say?" /board/** | L | Haiku 4.5 | /board/ + /api/board_ask, 6 personas | ✅ Done (v3.7.80) |
| v3.7.81 | **Nav + footer standardised (all 12 pages)** | S | None | `deploy/update_nav.py` | ✅ Done (v3.7.81) |
| v3.7.82 | **In-memory rate limiting fix** | S | None | Stopped AccessDeniedException alarms | ✅ Done (v3.7.82) |
| DIST-1 | **First Distribution Event** | S (content) | None | HN post or Twitter thread | ⬜ Gated on /story prose |
| WR-11 | **Trend arrays in public_stats.json** | S | None | daily_brief_lambda.py updated | ✅ Done (v3.7.76) |
| WR-12 | **AI brief excerpt in public_stats.json** | S | None | daily_brief_lambda.py updated | ✅ Done (v3.7.76) |
| WR-13 | **/api/ask backend** | S | Haiku 4.5 | site_api_lambda.py updated | ✅ Done (v3.7.76) |
| WR-14 | **Write /story page content (5 chapters)** | L (Matthew) | None | Personal prose in 5 placeholders | ⬜ **CRITICAL — distribution gate** |
| WR-15 | **Before/during photos on /story** | S (Matthew) | None | Side-by-side with date stamps | ⬜ |
| WR-16 | **Dual-path navigation** | S | None | Two CTAs below hero | ✅ Done (v3.7.76) |
| WR-19 | **Press page / media hook on /about** | XS | None | 3-sentence pitch + contact | ✅ Done (v3.7.76) |

**Sprint 5 Definition of Done:**
- ✅ MCP `Key` bug fixed and MCP Lambda redeployed
- ✅ `/story` structure and `/about` pages live on averagejoematt.com
- ✅ Email capture CTA visible on every page
- ✅ Website review quick wins deployed (10 items)
- ✅ /api/ask backend live (v3.7.76)
- ✅ Trend arrays + brief excerpt flowing to public_stats.json (v3.7.76)
- ✅ Adaptive deficit ceiling wired into Daily Brief (v3.7.72)
- ✅ Weekly habit review generating on Sundays (v3.7.72)
- ✅ Nav + footer standardised across all 12 pages (v3.7.81) — /story/ in primary nav
- ✅ In-memory rate limiting on /ask/ + /board/ — stopped AccessDeniedException alarms (v3.7.82)
- ⬜ /story prose written by Matthew
- ⬜ Before/during photos added
- ⬜ At least one external distribution event published
- ⬜ Privacy policy visible on /subscribe page (Yael requirement)

---

## SPRINT 6 — R17 Hardening Sprint (~2 weeks)
**Theme: Public Endpoint Security + Pre-DIST-1 Readiness**
**Source: Architecture Review #17 (2026-03-20) + Board Deliberation**
**Cost impact: +$7.40/month (WAF $7 + API key secret $0.40) — Matthew approved**

#### Tier 0 — Before DIST-1 (Critical Path)

| ID | Feature | Effort | Model | Deliverable | Status |
|----|---------|--------|-------|-------------|--------|
| R17-01 | WAF WebACL + rate-based rules on amj CloudFront | M | None (CDK) | CDK: WAF WebACL in LifePlatformWeb stack. 100 req/5min/IP on /api/ask, 50/5min on /api/board_ask | ⬜ |
| R17-02 | Privacy policy + AI disclaimer page | S | None (content) | `site/privacy/index.html` + footer/subscribe links | ⬜ |
| R17-03 | CloudWatch dashboard for site-api | S | None (CDK/CLI) | Dashboard: invocations, errors, p50/p95 latency, duration. Alarms: error >5%, p95 >5s, invocations >1000/hr | ⬜ |
| R17-04 | Separate Anthropic API key for site-api | S | None (ops) | New secret `life-platform/site-api-ai-key`, update site_api env var | ⬜ |
| R17-05 | External uptime monitor | XS | None (manual) | UptimeRobot free tier on /api/vitals | ⬜ Matthew only |
| R17-06 | PITR restore drill | S | None (ops) | Execute script, document in `docs/reviews/PITR_DRILL_2026-03.md` | ⬜ Matthew only |
| R17-07 | Remove google_calendar from config.py SOURCES | XS | None | One-line edit in `mcp/config.py` | ⬜ |
| R17-08 | Verify + fix MCP Lambda memory docs | XS | None (ops) | Check live config, update ARCHITECTURE.md | ⬜ |

#### Tier 1 — 60-Day Items (Post-DIST-1)

| ID | Feature | Effort | Model | Deliverable | Status |
|----|---------|--------|-------|-------------|--------|
| R17-09 | Move site-api Lambda to us-west-2 | M | None (CDK) | CDK: Lambda in LifePlatformOperational, update CF origin | ⬜ |
| R17-10 | SIMP-1 Phase 2 (95→≤80 tools) | L | **Opus** | EMF telemetry review, tool deprecation, registry cleanup | ⬜ |
| R17-11 | Site-api model strings to env vars | S | None | Update site_api_lambda.py to read AI_MODEL_HAIKU from env | ⬜ |
| R17-12 | Site-api observability alarms | S | None (CDK) | 3 alarms: error rate, p95 latency, invocation spike | ⬜ |
| R17-13 | IC-4/IC-5 activation | M | Sonnet | CDK EventBridge rules + deploy (data gate ~Apr 18) | ⬜ |
| R17-14 | ADR-025 cleanup (composite_scores) | S | None | Remove dead code, update SCHEMA.md | ⬜ |

#### Tier 2 — 90-Day Items

| ID | Feature | Effort | Model | Deliverable | Status |
|----|---------|--------|-------|-------------|--------|
| R17-15 | CSP headers via CloudFront response headers policy | S | None (CDK) | CDK: response headers policy on amj distribution | ⬜ |
| R17-16 | Anthropic API graceful degradation | M | None | Timeout + fallback in ai_calls.py; each email Lambda handles `ai_unavailable` | ⬜ |
| R17-17 | DynamoDB TTL policy for non-critical partitions | S | None | TTL on anomaly records >365d, cached tools | ⬜ |
| R17-18 | CORS explicit headers on site-api | S | None | Add Access-Control-Allow-Origin to all responses | ⬜ |

**Sprint 6 Board Decisions (R17 session, 2026-03-20):**
1. Rate limiting → WAF rate-based rules (not DDB counters — preserves site-api read-only IAM)
2. WAF config → WebACL + 2 rate rules, no managed rule set (Raj: don't gold-plate)
3. Cross-region → Move site-api to us-west-2 (60-day, $0)
4. API key isolation → Separate secret (+$0.40/mo)
5. Uptime monitoring → UptimeRobot free tier
6. Circuit breaker → Graceful degradation in ai_calls.py (no new deps)

---

## SPRINT 7 — World-Class Website Sprint (~4 weeks, April/May 2026)
**Theme: Storytelling + Live Data + Distribution Readiness**
**Source: Expert Panel Website Strategy Review (2026-03-20) — 30+ expert personas across design, product, growth, health tech, AI, and commercialization**
**Prerequisite: Sprint 6 Tier 0 complete (WAF, privacy, dashboard)**

> The panel's unanimous finding: the site has world-class infrastructure but undersells the story by 10x.
> Three foundations must be solid before any growth play: (1) /story/ prose, (2) live data working, (3) subpage routing fixed.
> Sprint 7 is sequenced: Tier 0 unblocks distribution, Tier 1 builds retention, Tier 2 enables growth.

#### Tier 0 — Foundations (Pre-Distribution Critical Path)

| ID | Feature | Effort | Source | Deliverable | Status |
|----|---------|--------|--------|-------------|--------|
| WR-14 | **Write /story/ page content (5 chapters)** | L (Matthew) | Panel §1,§3 — unanimous #1 finding | 1,500–2,000 words of Matthew's own prose across 5 chapter placeholders. This is the emotional anchor for the entire site. | ⬜ **CRITICAL — Matthew only** |
| WR-28 | **Fix subpage 404s for crawlers/link previews** | S (30min) | Panel §1 — all subpages return 404 to server-side fetches | CloudFront custom error response or S3 routing rules for subdirectory index.html files. Currently /story/, /platform/, /live/, /journal/ all 404 when fetched without JS. Breaks SEO, social previews, link sharing. | ✅ CDK updated (needs deploy) |
| WR-29 | **Populate live data on homepage (fix dashes)** | S (1-2h) | Panel §1,§2 — "broken live data promises are worse than no promises" | Wire `/api/vitals` + `/api/journey` into homepage JS. Fallback to `public_stats.json`. Add "as of [timestamp]" to prevent stale data looking broken. Fix ticker dashes for streak/journey. | ✅ Fixed double-path `/site/public_stats.json` bug |
| WR-30 | **Add one real daily brief excerpt to homepage** | S (1h) | Panel §6 — "the homepage promises brief excerpts — deliver" | Replace "Live brief excerpts coming soon" placeholder in "What Claude sees" section with a real (redacted if needed) daily brief excerpt. Static is fine; proves the AI capability viscerally. | ✅ Done |
| WR-15 | **Before/during photos on /story/** | S (Matthew) | Panel §2 — "zero human imagery is the biggest design gap" | At minimum one authentic photo of Matthew on /story/ or homepage. The site has no human anchor — it feels like a dashboard, not a story about a person. | ⬜ **Matthew only** |
| WR-31 | **"Start here" flow for new visitors** | XS (30min) | Panel §3 — first-time visitors don't know where to go | Add a prominent "New here? Start with the story →" CTA on homepage. Simple routing signal for first-time visitors. | ✅ Done |
| WR-32 | **Newsletter sample/archive page** | S (1-2h) | Panel §5 — "no one subscribes to an email they can't preview" | Render a recent Weekly Signal email as a public page at `/journal/weekly-signal-sample/` or similar. Link from every subscribe CTA. | ✅ Done (`/journal/sample/`) |

#### Tier 1 — Retention + AI Showcase (Post-Distribution)

| ID | Feature | Effort | Source | Deliverable | Status |
|----|---------|--------|--------|-------------|--------|
| WR-33 | **Visual transformation comparison cards** | M (3-4h) | Panel §4,§5 — "the most shareable format in health/fitness" | Auto-generated single-image comparison cards: "Day 1 vs. Today" showing weight, HRV, recovery, body comp deltas. Formatted for Twitter/LinkedIn sharing. Could be a dedicated `/timeline/` enhancement or standalone component. | ✅ Done (homepage) |
| WR-34 | **Data flow animation on /platform/** | M (3-4h) | Panel §8 — Priya: "the architecture diagram doesn't show the flow" | Interactive or animated diagram showing data moving: Whoop → DynamoDB → Claude → daily brief. Makes the architecture tangible to non-technical visitors. | ✅ Done |
| WR-35 | **Running cost ticker on /platform/** | S (1-2h) | Panel §8 — Marcus: "the $10/month story is buried" | Live or monthly-updated cost display on /platform/ showing real AWS billing breakdown. The cost story is one of the most compelling parts of the platform. | ✅ Done |
| WR-36 | **Public architecture review artifact** | M (2-3h) | Panel §6,§8 — "publishing a real AI architecture review would be a first on the public internet" | Redact sensitive findings from R16 or R17, format as public page at `/platform/reviews/` or similar. Show 12-persona voting, grade progression, findings. Fascinating to technical audiences. | ✅ Done (`/platform/reviews/`) |
| WR-37 | **Scoring algorithm transparency on /character/** | S (1-2h) | Panel §9 — Attia: "if raw scores are weighted non-transparently, sophisticated audiences will question them" | Publish the Character Sheet scoring methodology: what inputs feed each pillar, how raw scores are computed, what "Level 2" means. Link from /character/ page. | ✅ Done |
| WR-38 | **"Discoveries" section — featured correlations** | M (3-4h) | Panel §8 — Omar: "the correlation matrix is genuinely novel but invisible from the homepage" | A homepage or /live/ section featuring the 3-5 most interesting correlations from the weekly Pearson matrix. e.g., "HRV drops 15% when training >4 days in a row (r=-0.42, p=0.03)." Proof-of-concept storytelling. | ✅ Done (homepage) |
| WR-39 | **"Current Protocols" page or section** | M (3-4h) | Panel §9 — Huberman: "the QS audience wants actionable protocols, not just scores" | What specific protocols is Matthew following? Morning routines, sleep hygiene, Zone 2 targets, supplement stack, nutrition approach. And whether the data shows they're working. | ✅ Done (`/protocols/`) |
| WR-40 | **Response safety filter for /ask/ endpoint** | S (1-2h) | Panel §8 — Yael: "the /ask/ page could expose sensitive health data if queries aren't filtered" | Implement response category filter in site_api_lambda.py that blocks certain query categories (mental health specifics, financial data, PII). Already rate-limited; this adds content filtering. | ✅ Done (needs deploy) |

#### Tier 2 — Growth Plays (60-90 Day Horizon)

| ID | Feature | Effort | Source | Deliverable | Status |
|----|---------|--------|--------|-------------|--------|
| WR-41 | **LinkedIn/Twitter build-in-public campaign** | S/week (ongoing) | Panel §5,§7 — Sahil: "the distribution IS the product at this stage" | Matthew posts 2x/week: one stat + one insight + one honest reflection. Hooks: $10/month cost story, non-engineer story, weekly weigh-in. Links back to site. Target: 8 weeks sustained. | ⬜ **Matthew only** |
| WR-42 | **Hacker News / Product Hunt launch event** | S (content) | Panel §10 — "when story is written, live data works, and /ask/ is functional, the site is ready for launch" | "Show HN: I'm a non-engineer who built a 95-tool AI health platform with Claude for $10/month. Ask my data anything." Time for Tuesday morning. Gated on: WR-14 + WR-28 + WR-29 + WR-30 complete. | ⬜ Gated on Tier 0 |
| WR-43 | **Animated heartbeat/biometric signature** | M (4-6h) | Panel §2 — "the one design element that would make this site instantly memorable" | A live or daily-updated visual pulse on homepage showing HRV/recovery as an organic, breathing graphic. Not a chart — a visual signature that communicates "this system is alive" before anyone reads a word. | ⬜ |
| WR-44 | **"Tool of the week" feature on /platform/** | S (1-2h) | Panel §8 — Anika: "the 95-tool list is impressive but static" | Weekly-rotating highlight showing one MCP tool's actual output. e.g., "This week: `get_glucose_meal_response` — here's what it returned for yesterday's dinner." | ✅ Done |
| WR-45 | **Media kit + speaking page** | S (1-2h) | Panel §7 — "needs to exist before anyone reaches out" | Expand /about/ with: professional bio, talk topics, previous appearances (if any), headshot, contact for media inquiries. | ⬜ |
| WR-46 | **Data export / open data page** | M (3-4h) | Panel §4 — "for the QS community: downloadable datasets or methodology docs" | Weekly aggregated anonymized data CSV, correlation methodology docs, Character Sheet scoring algorithm. At /data/ or /explorer/export/. | ⬜ |

**Sprint 7 Definition of Done:**
- ⬜ /story/ prose written by Matthew (WR-14) — **distribution gate**
- ✅ All subpages accessible to crawlers and social link previews (WR-28) — CDK updated, needs deploy
- ✅ Homepage shows live data, not dashes (WR-29) — fixed double-path bug
- ✅ Daily brief excerpt visible on homepage (WR-30) — real excerpt replaces placeholder
- ⬜ At least one photo of Matthew on the site (WR-15)
- ✅ Newsletter sample viewable before subscribing (WR-32) — `/journal/sample/`
- ⬜ DIST-1 (HN or Twitter launch) executed with Tier 0 complete
- ✅ /ask/ has response content filtering (WR-40) — needs Lambda deploy
- ⬜ Build-in-public posting cadence established (WR-41)

---

## BACKLOG — Website Review 60/90-Day Items

| ID | Feature | Source | Status | Notes |
|----|---------|--------|--------|-------|
| WR-17 | Dynamic social cards (Lambda@Edge) | Review §10 | ⚠️ Partial | Function URL 403 TBD |
| WR-18 | "Build Your Own" guide/course MVP | Review §7 | ⬜ | Gated on /story + 10 weeks data |
| WR-20 | Video: daily brief screen recording | Review §3 | ⬜ | Matthew only |
| WR-21 | Self-host fonts | Review §2 | ✅ Done (v3.7.76) | |
| WR-22 | Scroll entrance animations | Review §2 | ✅ Done (v3.7.76) | |
| WR-23 | Genome /biology noindex | Review §8 | ✅ Done (v3.7.76) | |
| WR-25 | Newsletter "The Weekly Signal" launch — first issue | Review §5, §7 | ⬜ | Gated on /story + 3+ subscribers |
| WR-26 | Paid behind-the-platform tier ($5/month) | Review §7 | ⬜ | Gated on >200 free subscribers |
| WR-27 | CGM glucose response visualizations | Review §9 | ⬜ | High-interest for metabolic health crowd |

---

## BACKLOG — Data-Gated

| ID | Feature | Gate | Target |
|----|---------|------|--------|
| BS-06 | Habit Cascade Detector | 60+ days consistent Habitify data | ~May 2026 |
| IC-27 | Habit Cascade Intelligence IC feature | Same as BS-06 | ~May 2026 |
| BS-T2-7 | Experiment Results Auto-Analysis | 5+ complete experiments | ~May 2026 |
| BS-10 | Meal-Level CGM Response Scorer | CGM data maturity | ~June 2026 |
| IC-30 | Sleep Environment Intelligence | BS-SL1 running 4+ weeks | ~August 2026 |
| BS-BM3 | DEXA-Anchored Body Composition Model | DEXA scan #2 | After next DEXA |
| BS-T2-6 | Decision Journal Analytics | 50+ logged decisions | ~July 2026 |
| BS-BM1 | Biomarker Trajectory Alert System | ≥10 blood draws (currently 7) | ~2028+ |
| IC-31 | Biomarker Trajectory Intelligence | Same as BS-BM1 | ~2028+ |

---

## BACKLOG — Time-Gated

| ID | Feature | Gate | Target |
|----|---------|------|--------|
| EMAIL-P2 | Data Drop Monthly Exclusive | Month 3 of email list | June 16, 2026 |
| EMAIL-P3 | Discord/Circle Community Launch | Month 6 of email list | September 16, 2026 |
| BS-T3-5 | Real-Time Streaming Pipeline | 180+ day horizon | ~September 2026 |
| BS-T3-6 | Cost-Optimized Multi-Tenant DynamoDB | User count >10 | TBD post-commercialization |

---

## BACKLOG — Later (Lower Priority)

| ID | Feature | Notes |
|----|---------|-------|
| BS-15 | Board of Directors Interactive Tool (website) | Lead magnet; after audience established |
| WEB-NET | N=1 Experiment Template Tool | Requires backend for session + download; underestimated; defer |
| BS-T3-1 | Authentication & User Accounts | Commercialization prerequisite |
| BS-T3-2 | Data Source Abstraction Layer | Multi-user prerequisite |
| BS-T3-3 | AI Coaching Personalization Framework | Multi-user prerequisite |
| BS-T3-4 | Compliance & Data Governance | Commercialization prerequisite |

---

## COMPLETE FEATURE INVENTORY — All 48 Board Summit Features

All Sprint 1–4 features shipped (30 items). Sprint 5 complete (buildable). Remaining: /story prose + DIST-1.

| Sprint | Status | Items |
|--------|--------|-------|
| Sprint 1 | ✅ Complete | BS-01, BS-02, BS-03, BS-05, BS-09 |
| Sprint 2 | ✅ Complete | BS-07, BS-08, BS-SL2, BS-BH1, BS-MP3, BS-TR1, BS-TR2, BS-NU1 |
| SIMP-1 Ph2 | ⏳ ~Apr 13 | 95 → ≤80 tools |
| Sprint 3 | ✅ Complete | BS-12, BS-SL1, BS-MP1, BS-MP2, BS-13, BS-T2-5, WEB-WCT, IC-28, IC-29 |
| Sprint 4 | ✅ Complete | BS-11, WEB-CE, BS-BM2, BS-14 |
| Sprint 5 | ✅ Buildable | All technical items done. /story prose + DIST-1 pending (Matthew). |
| Sprint 6 | ⬜ Active | R17 Hardening: WAF, privacy, dashboard, PITR, cleanup (18 items) |
| Sprint 7 | ⬜ Planned | World-Class Website: storytelling, live data, distribution (19 items, WR-14 through WR-46) |

---

## Sprint Timeline Summary

```
Week 1-2:    SPRINT 1 ✅ COMPLETE — Foundation + Audience
Week 3-4:    SPRINT 2 ✅ COMPLETE — Intelligence Core + Sleep
Week 5:      MINI-SPRINT — SIMP-1 Phase 2 Rationalization (~April 13)
Week 6-9:    SPRINT 3 ✅ COMPLETE — Advanced Intelligence + Content
Week 10-13:  SPRINT 4 ✅ COMPLETE — Website Interactive + Architecture
Week 14-15:  SPRINT 5 ✅ COMPLETE (buildable) — Website + Distribution
             S2-T1-9 deficit ceiling ✅ | S2-T1-10 weekly habit review ✅
             WR-24 subscriber gate ✅ | S2-T2-2 /board/ page ✅
             v3.7.81: nav/footer standardised all 12 pages ✅
             v3.7.82: in-memory rate limiting fix ✅
             REMAINING: /story prose | photos | DIST-1

NOW:         SPRINT 6 — R17 Hardening Sprint (~2 weeks, March/April 2026)
  Tier 0:    WAF + privacy + dashboard + PITR drill + cleanup (pre-DIST-1)
  Tier 1:    Site-api migration + SIMP-1 Ph2 + IC-4/IC-5 (60 days)
  Tier 2:    CSP + graceful degradation + TTL + CORS (90 days)

NEXT:        SPRINT 7 — World-Class Website (~4 weeks, April/May 2026)
  Tier 0:    /story/ prose + 404 fix + live data + brief excerpt + photos + newsletter sample
  Tier 1:    Comparison cards + data flow anim + cost ticker + public review + protocols + /ask/ filter
  Tier 2:    HN launch + build-in-public + heartbeat viz + tool-of-week + media kit + open data

~April 2026: R17 Tier 0 complete → Sprint 7 Tier 0 begins
~May 2026:   Sprint 7 Tier 0 done → DIST-1 (HN launch) → Sprint 7 Tier 1
~May 2026:   WR-25 Newsletter launch (post /story) | BS-06/IC-27 (data) | SIMP-1 Phase 2
~June 2026:  Sprint 7 Tier 2 + EMAIL-P2 Data Drop #1 | R18 Architecture Review
~Aug 2026:   IC-30 (after BS-SL1 matures)
~Sep 2026:   EMAIL-P3 Community launch | BS-T3-5 Streaming

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
*Architecture Review #17: `docs/reviews/REVIEW_2026-03-20_v17.md` — Sprint 6 derived from R17 findings + board decisions*
*Champions listed are advisory — Matthew Walker is the implementer*
