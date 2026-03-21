# averagejoematt.com — World-Class Website Strategy Review

**Expert Panel Summit · March 20, 2026**
**Site reviewed: https://averagejoematt.com**
**Items integrated: Sprint 7 in SPRINT_PLAN.md (WR-28 through WR-46) + PROJECT_PLAN.md**

---

## Executive Summary

The panel agrees: **averagejoematt.com has a genuinely rare premise — a non-engineer building a 95-tool AI health intelligence platform solo with Claude, documenting a real body transformation with radical transparency — but the site is currently underselling this story by at least 10x.** The homepage is well-designed, the design system is sophisticated (dark biopunk terminal aesthetic, coherent token system, live data ticker), and the technical architecture pages are impressive. But three things are holding the site back from its potential:

1. **The Story page is empty.** The most powerful asset this site has — Matthew's personal narrative — is placeholder text. Every growth expert on this panel says the same thing: no one shares architecture diagrams, they share stories. The /story/ page is the single highest-leverage gap on the entire site.

2. **Subpages are returning 404 to crawlers and link previews.** Despite having 12+ well-built pages locally, several return 404 when fetched server-side (likely a CloudFront default root object / S3 routing issue). This means link sharing, SEO, and social previews are broken for most of the site.

3. **The site communicates "impressive technical project" but not yet "thing I need to follow."** There's no narrative arc pulling visitors forward, no visible evidence of transformation over time, and the real-time data promises ("Live brief excerpts coming soon") are still unfulfilled. The bones are excellent. The flesh needs to come.

The biggest opportunity: **This is one of the best human-AI collaboration case studies that currently exists on the public internet, and almost no one knows about it.** The site has the infrastructure to tell that story — it just hasn't told it yet.

---

## Sprint 7 Items Created (WR-28 through WR-46)

### Tier 0 — Foundations (Pre-Distribution Critical Path)
| ID | Feature |
|----|---------|
| WR-14 | Write /story/ page content (5 chapters) — CRITICAL, Matthew only |
| WR-28 | Fix subpage 404s for crawlers/link previews |
| WR-29 | Populate live data on homepage (fix dashes) |
| WR-30 | Add one real daily brief excerpt to homepage |
| WR-15 | Before/during photos on /story/ — Matthew only |
| WR-31 | "Start here" flow for new visitors |
| WR-32 | Newsletter sample/archive page |

### Tier 1 — Retention + AI Showcase
| ID | Feature |
|----|---------|
| WR-33 | Visual transformation comparison cards (shareable) |
| WR-34 | Data flow animation on /platform/ |
| WR-35 | Running cost ticker on /platform/ |
| WR-36 | Public architecture review artifact |
| WR-37 | Scoring algorithm transparency on /character/ |
| WR-38 | "Discoveries" section — featured correlations |
| WR-39 | "Current Protocols" page/section |
| WR-40 | Response safety filter for /ask/ endpoint |

### Tier 2 — Growth Plays
| ID | Feature |
|----|---------|
| WR-41 | LinkedIn/Twitter build-in-public campaign |
| WR-42 | Hacker News / Product Hunt launch event |
| WR-43 | Animated heartbeat/biometric signature |
| WR-44 | "Tool of the week" feature on /platform/ |
| WR-45 | Media kit + speaking page |
| WR-46 | Data export / open data page |

---

## The One Bet

**Write the /story/ page.** Full panel unanimous. Everything else follows from that.

---

*Full 10-section analysis below. See SPRINT_PLAN.md for implementation details.*

---

## Section 1: First Impressions & Positioning (0–5 Seconds)

### What the site communicates immediately

The homepage opens with "SIGNAL / HUMAN SYSTEMS" as the brand header, a live data ticker (weight, HRV, recovery, streak, journey progress), and a progress bar showing 302 → 287.7 → 185.

**What works:**
- The ticker immediately communicates "this is live, this is real, this is data-driven." That's distinctive.
- The progress bar (302 → 287.7 → 185) instantly communicates the transformation journey.
- The copy is strong — "Every failure included" is a trust signal.
- The two-path CTA ("Follow the Journey" / "See the Platform") correctly identifies the dual audience.

**What doesn't work:**
- "SIGNAL / HUMAN SYSTEMS" is opaque. Optimizes for cool over clarity.
- "AMJ" as the nav brand is equally cryptic.
- The live data ticker shows dashes ("—") for streak and some metrics — broken promises in the first 5 seconds.
- "Days on Journey" and "Current Streak" counters show "—" — the most emotionally resonant numbers, and they're empty.

### Panel tension: Tobias van Schneider vs. Julie Zhuo

**Resolution:** Keep the aesthetic. Add a one-line subtitle under "SIGNAL / HUMAN SYSTEMS": *"Matthew Walker's AI-powered body transformation — live data from 19 sources"*. The brand can be evocative; the subtitle must be literal.

---

## Section 2: Design & Visual Identity

### Current aesthetic grade: A- (Jony Ive), B+ (overall panel)

**What's excellent:**
- The design token system (`tokens.css`) is genuinely professional — better than most production startup sites.
- The dark biopunk terminal aesthetic is cohesive and distinctive.
- Grid-based layouts with 1px gap separators create a clean, data-dashboard feel.
- The SVG radar chart on /character/ with animated fill gamifies the data presentation.

**What needs work:**
- **No imagery anywhere.** Zero photos of Matthew, no before/after, no lifestyle imagery. The single biggest design gap.
- **The homepage hero section has no visual focal point.** It's a wall of text with a progress bar.
- **The "Live signals" section shows empty data ("—").** Trust-killer.
- **Mobile:** Grid-heavy layouts compress poorly on small screens.

### Design references

| Reference | What to take from it |
|-----------|---------------------|
| levels.com | Health data + human storytelling + clear positioning |
| Whoop member stories | Data made personal — real people, real numbers, real narrative |
| Linear.app | Dark-mode with exceptional typography, motion, info density |
| Raycast.com | Technical tool that feels premium and approachable |
| Strava Year in Sport | Personal data made shareable and emotionally resonant |

### The one memorable design element

A live, animated "heartbeat" visualization — HRV/recovery as an organic, breathing graphic. A visual signature that communicates "this system is alive" before anyone reads a word. (WR-43)

---

## Section 3: Content Strategy & Storytelling

**The story hasn't been written yet.** The /story/ page has 5 chapters, 4 are placeholders. This is the panel's unanimous #1 finding.

The site tells the *what* but not the *why*. The homepage hints at vulnerability but never delivers.

**Elena Voss / AI narrator:** Panel split. Keep Elena for weekly journal (distinctive format), but Matthew must write /story/ himself. The story page is where trust is built.

**Dual audience:** Build the health journey path first. The AI/tech audience will find /platform/ on their own.

---

## Section 4: Page & Feature Gap Analysis

See Sprint 7 items above. Key gaps identified:
1. /story/ prose (P0)
2. Visual transformation timeline (P0 — exists at /live/ but data needs wiring)
3. Live daily snapshot fix (P0)
4. Newsletter sample (P1)
5. Before/After comparison cards (P1)
6. Data export / open data (P2)

---

## Section 5: Retention & Engagement Mechanics

The "reason to return" loop doesn't exist yet. The retention equation: *Something changes → I want to see the change → I come back.* Infrastructure exists; public surfaces don't reliably show it.

**What would make someone share this:**
1. Share card with today's stats (WR-33)
2. The /story/ page once written (WR-14)
3. The /ask/ page working (already live)
4. The $10/month cost story

**What would make a journalist reach out:** "Non-engineer builds a personal AI operating system using Claude that most enterprise companies don't have, for $10/month."

---

## Section 6: AI Showcase Strategy

Everything is *described*, not *demonstrated*. To make it visceral:
1. The /ask/ page working (already live — biggest demo)
2. A sample daily brief on the homepage (WR-30)
3. A before/after of a real data-driven decision (WR-38)
4. The architecture review as a public artifact (WR-36)

**The hook:** *"What if you could build an AI operating system for your body — not with an engineering degree, not with a startup budget, but with Claude and $10/month?"*

---

## Section 7: Commercialization Pathways

**Panel consensus:** Don't monetize yet. Build the free newsletter audience first. The path: free newsletter → paid newsletter ($10/mo) → course/guide ($99) → community ($29/mo).

The minimum viable commercial experiment: consistent Weekly Signal delivery + LinkedIn/Twitter build-in-public content. Everything follows from 500+ engaged subscribers.

Most credible paths ranked:
1. Newsletter + premium tier (HIGH)
2. "Build Your Own" guide/course (HIGH)
3. Speaking / advisory (MEDIUM)
4. Community membership (MEDIUM-LOW now, HIGH later)
5. Open-source the platform (STRATEGIC)

---

## Section 8: Technical Board Review

**Not surfaced that should be:** Data flow visualization (Priya), $10/month cost story (Marcus), correlation discoveries (Omar), live tool output (Anika).

**Minimal-lift features:** Live stats API → homepage widgets (endpoints exist), public_stats.json population, /ask/ endpoint (already deployed).

**Security (Yael):** /ask/ needs response content filtering for sensitive categories. Rate limiting is good. API endpoints need server-side rate limits (not just client-side).

**FinOps (Dana):** 10K monthly visitors would add ~$6–16/month. Total stays under $30. /ask/ is the main cost driver (Claude API calls). Non-issue until 100K+ visitors.

---

## Section 9: Health Content Credibility

**Attia:** Publish the scoring algorithm. Every data claim should specify time window, sample size, confounders.

**Huberman:** Add protocol documentation — what Matthew is actually doing and whether data shows it works. (WR-39)

**Patrick:** Genomic data and lab draws are credibility signals. Frame SNPs as "predisposition" not "destiny."

**N=1 framing:** *"The value isn't that my results apply to you — it's that the methodology and honesty might inspire your own experiment."* Turn the limitation into a feature.

---

## Section 10: The 30/60/90 Day Roadmap

Fully integrated into Sprint 7 in SPRINT_PLAN.md. See that document for implementation details, effort estimates, and dependencies.

**30 Days (Sprint 7 Tier 0):** /story/ prose, fix 404s, live data, brief excerpt, photos, start-here flow, newsletter sample
**60 Days (Sprint 7 Tier 1):** Comparison cards, data flow animation, cost ticker, public review, scoring transparency, discoveries, protocols, /ask/ filter
**90 Days (Sprint 7 Tier 2):** HN launch, build-in-public campaign, heartbeat viz, tool-of-week, media kit, open data
