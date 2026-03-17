# Joint Board Sprint Review — Life Platform
**Sprint Plan Review & Alignment | March 16, 2026 | v3.7.61**
Health Board × Technical Board of Directors

---

## HEALTH BOARD REVIEW

**Dr. Peter Attia:**
ACWR in Sprint 1 is the right call — at 287 lbs in an aggressive deficit, a training injury is the single event that could derail 6 months of work. But I want more than a Lambda that computes a ratio. The alert must be *actionable*: when ACWR > 1.3, the Daily Brief should say "your training load is in the injury risk zone — reduce this week's volume by 20-30%, here's what that looks like." Computation without prescription is expensive journalism. Also: Deficit Sustainability Tracker belongs in Sprint 2, agreed. That's the second-biggest physical risk after injury.

**Dr. Andrew Huberman:**
I'm pushing back on Circadian Compliance Score (BS-SL2) sitting in Sprint 3. The Unified Sleep Record (BS-08) is Sprint 2, but that record is incomplete intelligence without the behavioral inputs that determined it. Sleep onset relative to circadian phase, last meal timing, screen exposure — these are causal levers, not decorative metrics. I want BS-SL2 moved to Sprint 2 alongside BS-08. They should ship together.

**Dr. Rhonda Patrick:**
Protein Timing & Distribution Score (BS-NU1) — I agree this belongs in Sprint 2. At 190g/day in a deficit, distribution across 4+ feedings is not optional — it's muscle-preservation critical. But I want to flag the model assignment: Sonnet is insufficient for this. Per-meal reasoning across MacroFactor timestamps requires contextual judgment about meal timing, gap analysis, and whether the pattern is changing. This needs Opus.

**James Clear:**
Essential Seven (BS-01) must ship Sprint 1, day 1, week 1. Not day 5. Not "by end of sprint." It is the identity foundation for everything else. If Matthew can't tell me what his 7 non-negotiables are and track them on a visually distinct interface, the 58 other habits are noise. I also want Vice Streak Amplifier (BS-BH1) accelerated to Sprint 1. The No Alcohol and No Marijuana streaks are the two highest-leverage items in the registry — making the cost of breaking them viscerally visible is not a Sprint 2 problem.

**David Goggins:**
Six Sprint 1 items means none of them get the attention they deserve. Cut it to 3: Essential Seven, ACWR, Vice Streak. The rest can wait. I've said it before and I'll say it again: you don't need a Decision Fatigue Detector. You need to make decisions before you're fatigued. The platform should have one mode: the data says you're recovered, do the hard thing anyway.

**Alex Hormozi:**
Website Hero (BS-02) and Email Capture (BS-03) are the only Sprint 1 items that create commercial options. Everything else is internal R&D for an audience of one. If Matthew ships nothing else in the next two weeks but has a compelling hero and an email list growing by 10 people a day, he's in better shape than shipping 6 perfectly engineered features to nobody. The email pipeline should be Sprint 1 priority #1, not priority #3. You cannot recover lost subscribers.

**Layne Norton:**
I'm agreeing with Rhonda on BS-NU1: change the model to Opus. Also — Deficit Sustainability Tracker (BS-12) needs Opus. It's reasoning across HRV, sleep quality, caloric adherence, training load, and habit completion simultaneously. That's a 5-signal cross-domain judgment call. Sonnet will produce generic outputs. Opus will produce the "your deficit is actually unsustainable right now and here's why the math supports that" insight that changes behavior.

**Ava Moreau (Design):**
Before any website feature ships — including the hero — Matthew needs to write one paragraph, 50 words or fewer, answering: "Why should I care about this stranger's health data?" That paragraph determines the hero copy, the email opt-in hook, and every content piece that follows. It is not a technical prerequisite. It is a clarity prerequisite. Website Hero is correctly Sprint 1 but it must start with that writing exercise, not a CDK deploy.

**Jordan Kim (Growth):**
Email capture is day 1 of Sprint 1. Not "also Sprint 1." Every day without a list is audience you'll never recover. The subscribe backend is live (v3.7.60) — the Chronicle→email pipeline is the missing piece. Ship it. Also: EMAIL-P2 (monthly Data Drop) and EMAIL-P3 (community) are time-gated but need to be planned NOW. Move them from abstract "Month 3/6" to concrete dates: EMAIL-P2 = June 16, EMAIL-P3 = September 16. Put it in the calendar.

---

## TECHNICAL BOARD REVIEW

**Priya Nakamura (Architecture):**
Sprint ordering is structurally sound. Critical dependency chain is honored: BS-03 → BS-T2-5 (newsletter pipeline can't ship before subscribers exist). One flag: SIMP-1 Phase 2 is ~April 13, which falls between Sprint 2 and Sprint 3. Don't add new MCP tools during Sprint 2 without checking them against the rationalization pass. Add a mini-sprint (3-5h) for SIMP-1 Phase 2 between Sprint 2 and Sprint 3. Also: BS-04 (Pre-Computed Composite Scores) is confirmed done (ADR-025) — remove from Sprint 1 scope entirely.

**Marcus Webb (Serverless):**
BS-07 (Website API Layer) in Sprint 2: correct, but clarify scope. This is extending the existing `site_api` Lambda with new endpoints — not a new Lambda. Use the existing function URL. Add CloudFront caching with TTL per endpoint. Real-Time Streaming Pipeline (BS-T3-5) correctly deferred — Whoop and CGM both have polling-based APIs, and EventBridge adds latency and cost without solving the fundamental constraint.

**Yael Cohen (Security):**
Multi-User Data Isolation Design (BS-14) in Sprint 4 — design-doc-only is approved. But: every DynamoDB write pattern added in Sprints 1-4 must be reviewed against the isolation design before that design is finalized. Write the isolation design spec FIRST in Sprint 4, then review Sprint 1-3 data patterns against it. Also: BS-05 (AI Confidence Scoring) should move to Sprint 1. Before any AI output goes live to external email subscribers, it needs confidence indicators. This is liability protection.

**Jin Park (SRE):**
Every new Lambda added in these sprints must ship with: (1) CloudWatch alarm, (2) DLQ wiring, (3) smoke test integration, (4) layer version pinning. Sprint 1 adds the ACWR Lambda. Sprint 2 adds sleep reconciliation + circadian score. Before Sprint 3 begins, run `post_cdk_reconcile_smoke.sh`. SIMP-1 Phase 2 timing needs a dedicated slot — don't let it get squeezed between sprints.

**Elena Reyes (Code Quality):**
BS-01 (Essential Seven Protocol) scope: (a) MCP tool returning only T0 habits with streak data — YES. (b) Website component on homepage — YES. (c) New Lambda — NO. This is an MCP enhancement + website display, not a Lambda. Similarly, BS-BH1 (Vice Streak Amplifier) = MCP tool upgrade + website component, not a new Lambda. Clarifying this cuts estimated effort from M to S for both.

**Omar Khalil (Data):**
Unified Sleep Record (BS-08) is the highest-risk item architecturally. Three sources with conflicting schemas, different time granularities, and APIs that can change independently. Strongly recommend: Sprint 1 = write conflict resolution rules doc (which source wins which field, how to handle gaps). Sprint 2 = implement. Do not implement before rules are documented. This is a design-first item.

**Anika Patel (AI/LLM):**
Model assignments review: BS-12 (Deficit Sustainability) → Opus confirmed. BS-MP1 (Autonomic Balance Score) → Opus, not Sonnet. The 4-quadrant interpretation requires contextual judgment about whether "high-energy/negative" is stress vs. productive intensity — that's nuanced and needs Opus. BS-MP2 (Journal Sentiment) → Opus correct. BS-05 (AI Confidence Scoring) → Sonnet correct; this is structured pattern matching on metadata fields.

**Henning Brandt (Statistics):**
Three hard requirements before any of this ships:

1. **BS-09 (ACWR):** This is arithmetic — 7-day/28-day rolling averages. No LLM needed. Pure computation Lambda. Remove the model designation entirely.

2. **BS-05 (AI Confidence Scoring):** Before implementation, write a specification document defining confidence criteria per insight type. Minimum required fields: sample size (n), effect size threshold, p-value or CI requirement, data freshness cutoff. Without this spec, "confidence scoring" is aesthetic labeling, not statistical rigor.

3. **BS-BM1 (Biomarker Trajectory):** Stays out of all sprints until Matthew has ≥10 blood draws. 7 data points with 95% CIs is not a trend — it's a hypothesis. Flag and hold.

**Sarah Chen (Product):**
Sprint 1 has 6 items. Too many for a solo developer. Goggins is right about the spirit; Hormozi is right about the priority. My compromise: Sprint 1 = 5 items — BS-01, BS-02, BS-03, BS-09, BS-05 (move from Sprint 2, per Yael). Cut BS-BH1 and BS-MP3 to Sprint 2. The website hero and email must ship together in the same week — a hero without a subscribe button is theater; a subscribe button without a story is spam.

**Raj Srinivasan (CTO):**
The bottleneck is distribution. Sprint 1 ships one thing a stranger can encounter, find compelling, and subscribe to. That means BS-02 (hero) + BS-03 (email) are the critical path. Everything else in Sprint 1 is acceleration or insurance. I support Sarah's 5-item Sprint 1. The API layer (BS-07) in Sprint 2 is the highest-leverage technical investment — it unblocks 5 downstream items.

**Viktor Sorokin (Adversarial):**
Sprint 4 is listed at ~45h of work for a solo part-time developer. Unrealistic. Cut it by 40%. Specific removals: WEB-NET (N=1 Experiment Template Tool) — requires a backend for session + download functionality. It's an L, not an M, and not Sprint 4 material. IC-30 (Sleep Environment Intelligence) — move to backlog until BS-SL1 has been running 4+ weeks and producing meaningful output. Also: "Vice Streak Amplifier" must be defined as a specific deliverable before capacity is assigned. If it's 3 lines in the existing MCP tool + a website counter, that's an S. If it involves a new Lambda with compounding value computation, that's different.

**Dana Torres (FinOps):**
Opus vs Sonnet at current N=1 volume: essentially zero cost difference. Approve all Opus assignments. At productization (User #2+), every daily-run Opus call multiplies linearly. For daily-run Lambdas assigned Opus (BS-12, BS-MP1, BS-MP2, BS-NU1): add a TODO comment to each — "Add Sonnet fast-path + Opus deep-analysis mode switchable by config before multi-user launch." This is not a Sprint requirement; it's a pre-commercialization requirement.

---

## BOARD ALIGNMENT — FINAL RECOMMENDATION

After full review, the joint boards align on the following adjustments:

### Sprint 1 — Final (5 items, ~19h)
- ✅ **Add BS-05** (AI Confidence Scoring, Sprint 2→1) — per Yael: must precede AI output to external subscribers
- ✅ **Remove BS-BH1** → Sprint 2
- ✅ **Remove BS-MP3** → Sprint 2
- ✅ **Add Sprint 1 prerequisites:** BS-08 conflict resolution doc (Omar) + BS-05 confidence criteria spec (Henning) + BS-02 "why care" paragraph (Moreau)
- ✅ **Remove LLM designation from BS-09** — pure computation Lambda

**Final Sprint 1:** BS-01, BS-02, BS-03, BS-05, BS-09

### Sprint 2 — Final (8 items, ~27h)
- ✅ **Add BS-SL2** (Circadian Compliance Score, Sprint 3→2) — per Huberman: ships with BS-08
- ✅ **Add BS-BH1** (from Sprint 1)
- ✅ **Add BS-MP3** (from Sprint 1)
- ✅ **Change BS-NU1 model to Opus** — per Norton + Patrick
- ✅ **Remove BS-12** → Sprint 3 (data needs to mature first)

**Final Sprint 2:** BS-07, BS-08, BS-SL2, BS-BH1, BS-MP3, BS-TR1, BS-TR2, BS-NU1

### Mini-Sprint: SIMP-1 Phase 2 (~April 13)
- EMF telemetry review → 89→≤80 tools. 3-5h. No new tools in Sprint 2 without Phase 2 approval.

### Sprint 3 — Final (9 items, ~38h)
- ✅ **Add BS-12** (from Sprint 2)
- ✅ **Confirm BS-MP1 model as Opus** (Anika + Huberman)
- ✅ **Add IC-29** (Metabolic Adaptation Intelligence, supports BS-12)

**Final Sprint 3:** BS-12, BS-SL1, BS-MP1, BS-MP2, BS-13, BS-T2-5, WEB-WCT, IC-28, IC-29

### Sprint 4 — Final (4 items, ~27h)
- ✅ **Remove WEB-NET** → Backlog (Viktor: complexity underestimated)
- ✅ **Remove IC-30** → Backlog (wait for BS-SL1 to mature 4+ weeks)

**Final Sprint 4:** BS-11, WEB-CE, BS-BM2, BS-14

### Backlog Additions (8 items newly added from PDF gaps)
- BS-T2-7: Experiment Results Auto-Analysis
- BS-T3-5: Real-Time Streaming Pipeline (~Sep 2026)
- BS-T3-6: Cost-Optimized Multi-Tenant DynamoDB
- WEB-NET: N=1 Experiment Template Tool (moved from Sprint 4)
- EMAIL-P2: Data Drop Monthly Exclusive (June 16, 2026)
- EMAIL-P3: Discord/Circle Community Launch (Sep 16, 2026)
- IC-27: Habit Cascade Intelligence (data-gated ~May 2026)
- IC-30: Sleep Environment Intelligence (after BS-SL1 runs 4+ weeks)

### Final Model Assignments

| Item | Model | Rationale |
|------|-------|-----------|
| BS-09 (ACWR) | None (pure compute) | Arithmetic only, no LLM needed |
| BS-TR1, BS-TR2 | None (pure compute) | Deterministic computation |
| BS-07 (API Layer) | None (infra) | Lambda routing, no AI |
| BS-08 (Sleep Record) | None (infra) | Data reconciliation, deterministic |
| BS-05 (AI Confidence) | Sonnet | Structured metadata pattern matching |
| BS-SL2 (Circadian Score) | Sonnet | Rule-based behavioral scoring |
| BS-BH1 (Vice Streaks) | Sonnet | Computation + display |
| BS-MP3 (Decision Fatigue) | Sonnet | Threshold + alert logic |
| BS-12 (Deficit Sustainability) | **Opus** | 5-signal cross-domain reasoning |
| BS-MP1 (Autonomic Balance) | **Opus** | 4-quadrant contextual interpretation |
| BS-MP2 (Journal Sentiment) | **Opus** | Narrative text + divergence detection |
| BS-SL1 (Sleep Env Optimizer) | **Opus** | Personalized temp optimization |
| BS-NU1 (Protein Timing) | **Opus** | Per-meal reasoning across timestamps |
| BS-BM2 (Genome Dashboard) | **Opus** | SNP-to-intervention clinical mapping (one-time) |
| BS-14 (Multi-User Design) | **Opus** | Complex architecture reasoning |
| IC-28, IC-29 | Sonnet / Opus | As specified in SPRINT_PLAN.md |

### Confidence Level: HIGH
All 22 board members aligned. No blocking dissents. Viktor's workload concerns addressed by Sprint 4 scope reduction. Goggins dissent noted but overruled by full board: measurement and hard work are not mutually exclusive.
