# Website Review #4 — Pre-Launch Comprehensive Audit

**Date**: March 26, 2026  
**Version**: v3.9.30.1  
**Convened by**: Product Board of Directors  
**Scope**: Full site review with simulated audience testing, throughline analysis, page-by-page priority ranking  
**Purpose**: April 1 launch readiness assessment

---

## PART 1: SIMULATED AUDIENCE EXPERIMENTS

Five audience personas were given the site and asked to navigate freely for 5–10 minutes, then answer structured questions. Results synthesized below.

---

### Persona A: "Tech Twitter" — Senior Engineer, 32, Bay Area

**Entry point**: Homepage (shared by a colleague on Slack)  
**Path**: Homepage → Platform → Intelligence → Cost → back to Homepage → Chronicle  
**Time on site**: 8 minutes

**What clicked immediately:**
- "$13/month" stat — stopped scrolling, re-read it. The cost-to-complexity ratio is the hook.
- Architecture layer diagram on /platform/ is exactly what this audience wants.
- The "non-engineer built this" angle is interesting but needs more proof (show the code? Link the GitHub? Architecture review grades?)

**What confused:**
- Homepage hero section is dense. "Day 1. For real this time." — wait, is this a fitness tracker or a dev blog? Took 15 seconds to understand the dual identity.
- Discovery cards on homepage claim correlation stats (r = -0.38) but the audit flagged these as fabricated. **If a technical audience discovers fake stats, credibility is destroyed instantly.**
- Nav structure has 6 sections with 30+ pages. Overwhelming for a first visit.

**What's missing:**
- GitHub link or code samples. The "For Builders" page should be the HN landing page, not the homepage.
- Architecture review PDFs or a link to the actual review methodology.
- A "How I built this" technical walkthrough — the single most shareable piece for this audience doesn't exist yet.

**Would they share it?** Yes, IF the /builders/ page had substance. Currently would share /platform/ and /cost/ directly.

**Trust score**: 6/10 — impressive technical depth, but the fake discovery cards and unwritten story chapters undermine credibility.

---

### Persona B: "Quantified Self Enthusiast" — Product Manager, 38, Austin

**Entry point**: Homepage (found via QS subreddit link)  
**Path**: Homepage → Live/Pulse → Sleep → Glucose → Explorer → Habits → Character  
**Time on site**: 12 minutes

**What clicked immediately:**
- The Pulse page (/live/) is the standout. Eight glyphs, one glance — this person *gets* dashboard design. The glyph strip interaction pattern (click to isolate) is intuitive.
- Character Sheet concept — "RPG for your health" resonates deeply with this audience. They immediately want one for themselves.
- 19 data sources displayed as a grid on the homepage — this is a credibility signal.

**What confused:**
- Story page is mostly empty. Went there expecting the origin narrative, got placeholder whitespace (even after our fix, chapters 1 and 4 are hidden, and the remaining visible content is thin).
- Homepage "Day 1 vs Today" comparison section shows mostly dashes and loading states for a first-time visitor. If the data hasn't populated, this section actively hurts.
- The difference between /live/ (Pulse), /character/, and /habits/ isn't clear from the nav. Are these three views of the same data?

**What's missing:**
- Comparison to existing tools: "Why not just use Apple Health + Whoop app?" A single paragraph answering this would convert skeptics.
- The Data Explorer page should be the crown jewel for this audience but it needs populated data.
- Historical charts. The QS community lives for trend lines. The sparklines are nice but they want full 90-day views.

**Would they share it?** Yes — the /live/ page and /character/ page specifically. Would post in r/QuantifiedSelf.

**Trust score**: 7/10 — data infrastructure is legit, but empty/placeholder content creates a "demo site" feel.

---

### Persona C: "Someone Like Matthew" — IT Director, 41, Chicago, 260 lbs

**Entry point**: Homepage (friend texted the link)  
**Path**: Homepage → Story → Chronicle → About → back to Homepage → subscribed  
**Time on site**: 6 minutes

**What clicked immediately:**
- The quote: "I used to be the protagonist of my own life. Somewhere along the way, I became a spectator." — instant recognition. This person felt *seen*.
- The honest hero narrative about the DoorDash spiral. Not "I got sick" — the real story of checking out.
- The chronicle concept — someone else reading your data and being honest about it. This is the accountability structure this person has been looking for.

**What confused:**
- Story page has a title ("302 pounds. One decision.") and then jumps to Chapter 02 and Chapter 03 (after our fix hiding 01 and 04). There's no opening narrative — the most emotionally important content on the site is missing.
- The prequel banner on the homepage says "everything before April 1 is the testing window" — but what does April 1 mean? There's no explanation of what changes on Day 1 vs. what's been happening.
- Subscribe CTA appears in 4+ places (hero, sticky bar, story page, footer). The repetition is fine but the messaging is identical everywhere — "Real numbers from 19 data sources" doesn't mean anything to someone who just wants to follow the human story.

**What's missing:**
- **The story content.** This is the single biggest gap. The drafts exist in `STORY_DRAFTS_v1.md` — they are powerful, honest, and exactly what this audience needs. But they're not on the site yet.
- A "people like me" signal. Right now the site feels like it's built for an audience of engineers. This person needs to see themselves reflected earlier.
- A simpler entry path. "Read my story" → "Follow along" → "See the data if you're curious." Not "here are 30 pages of technical infrastructure."

**Would they share it?** Would share with 1-2 close friends, *if the story was actually written*. Currently: "interesting concept but there's nothing to read."

**Trust score**: 8/10 for concept, 4/10 for execution — the emotional hook is strong but the content isn't there yet.

---

### Persona D: "Health & Wellness Creator" — Newsletter writer, 28, LA

**Entry point**: /chronicle/ (linked from another newsletter)  
**Path**: Chronicle → Week 00 article → About → Homepage → Subscribe  
**Time on site**: 7 minutes

**What clicked immediately:**
- Elena Voss concept is genuinely novel. "AI journalist with embedded access to biometric data" — this is a content angle that would get attention in media/creator circles.
- The chronicle articles that exist (Before the Numbers, The Empty Journal, The DoorDash Chronicle) are well-written and have a distinct editorial voice.
- The subscribe-from-chronicle flow is clean.

**What confused:**
- Four chronicle articles, but the numbering is confusing: Week 0, Week -4, Week -3, Week -1. Where are Weeks -2 and -5? (We just removed them — but the gap is visible in the numbering.)
- The site has TWO subscribe CTAs with different names: "The Weekly Signal" and "Follow the experiment." Are these different newsletters or the same thing?
- Going from /chronicle/ to the homepage is jarring — suddenly it's a technical dashboard. The content-first reader doesn't care about Lambda counts.

**What's missing:**
- A content calendar or "what to expect" explainer. If I subscribe, what do I get? When? How often?
- Social sharing on chronicle articles — Open Graph cards should show the article title and a pull quote, not the generic site image.
- Elena Voss needs her own byline page. The "About the reporter" card on /chronicle/ links to /about/ (Matthew's bio), not an Elena bio.

**Would they share it?** Would reference the Elena concept in their own newsletter. The chronicle articles are shareable but need better OG cards.

**Trust score**: 7/10 — the editorial product is compelling; the site wrapping around it doesn't match the quality.

---

### Persona E: "Skeptical Lurker" — Software Manager, 45, Remote

**Entry point**: Homepage (saw a comment thread about it)  
**Path**: Homepage → scrolled → left after 90 seconds  
**Why they left**: "I couldn't figure out what this was in the first 10 seconds."

**Post-exit debrief:**
- The hero section tries to do too much. Weight counter + progress bar + stat chips + prequel banner + Elena one-liner + "Start here" CTA + subscribe form + dual-path CTAs + heartbeat animation + chronicle teaser. That's **11 distinct elements** above the fold (or just below). A skeptic needs ONE clear message.
- "Day 1. For real this time." — For real *what* time? This presumes context the visitor doesn't have.
- The ticker at the top (WEIGHT 287.7 LBS · HRV 54 MS · RECOVERY 75%) means nothing to someone who doesn't already know what this site is.
- The design aesthetic — dark mode, monospace, terminal-inspired — signals "developer tool" not "health journey." This filters out the mainstream audience before they even read a word.

**What would have kept them:**
- A single, clear sentence: "I'm tracking my weight loss with 19 data sources and publishing everything. Here's what the data shows this week."
- A featured chronicle article visible without scrolling.
- Less UI density. More whitespace. Fewer numbers.

**Trust score**: 3/10 — bounced before forming an opinion on content quality.

---

## PART 2: PRODUCT BOARD SYNTHESIS

Each board member weighs in on the aggregated findings.

---

### Mara Chen (UX Lead)

**Core finding**: The site suffers from **information density without hierarchy**. Every page presents all available data simultaneously, which works for power users (Persona B) but actively repels casual visitors (Persona C, E). The homepage alone has 11 interactive elements above the fold. The nav has 30+ destinations organized into 6 dropdowns.

**Recommendation**: Implement a **two-track entry model**. Track 1 is the story: Homepage → Story → Chronicle → Subscribe. Track 2 is the data: Homepage → Live → Explorer → Platform. Right now both tracks collide on every page. The homepage should have ONE primary CTA (probably "Read my story" or the latest chronicle) with the data track accessible but secondary.

**Priority item**: The Story page is the most important page on the site and it's essentially empty. Fix this before April 1 or remove it from primary navigation.

---

### James Okafor (CTO)

**Core finding**: The technical infrastructure is impressive and the live data pipeline works. The site-api Lambda, CloudFront caching, and public_stats.json pattern are solid. However, **the site makes multiple API calls per page load** (public_stats.json + /api/pulse + /api/character_stats + /api/habit_streaks + /api/correlations + /api/journey_timeline + /api/journey_waveform). For a first visit, several of these fail or return empty, creating a jarring "loading... loading... —" experience.

**Recommendation**: Pre-render a complete "snapshot" into public_stats.json during the daily brief pipeline so the site makes ONE fetch on page load. API calls should only happen for genuinely real-time data (like the Pulse page). The homepage should work perfectly with zero API calls beyond the static JSON.

**Priority item**: Reduce homepage API calls from 7+ to 1. The current pattern burns CloudFront cache misses and creates inconsistent load states.

---

### Sofia Herrera (CMO)

**Core finding**: The site has **two audiences that need two different front doors**: (1) the human-interest audience who cares about Matthew's story, vulnerability, and the "average joe builds AI" narrative, and (2) the technical audience who cares about the architecture, cost, and build-it-yourself potential. Right now both audiences land on the same homepage and neither gets what they need in the first 5 seconds.

**Recommendation**: The April 1 launch should lead with the story. The technical audience can find what they need through the nav. The homepage hero should be: (1) The quote. (2) One sentence about what this is. (3) "Read the story" CTA. (4) Latest chronicle card. The weight counter, progress bar, stat chips, and prequel banner can all move below the fold or to dedicated pages.

**Priority item**: Fake discovery cards on the homepage MUST be removed or replaced before any public sharing. One HN commenter noticing fabricated correlation stats would kill the project's credibility permanently.

---

### Dr. Lena Johansson (Longevity Science)

**Core finding**: The statistical framing is appropriate where it exists (FDR correction mentioned, N=1 caveats, "correlations not causation" disclaimers). However, **the fabricated discovery cards on the homepage are a scientific integrity violation**. Specific r-values and p-values attributed to data that doesn't exist is not "placeholder" — it's fabrication. This must be addressed as a pre-launch blocker.

**Recommendation**: Remove all fabricated statistics. Replace with either (a) real findings from the correlation engine when they exist, or (b) narrative discovery cards from the interview (supplements → sleep, CGM → anxiety, platform → didn't prevent relapse) — which are honest observations even if not statistically validated.

**Priority item**: Homepage discovery cards. Non-negotiable pre-launch fix.

---

### Raj Mehta (Product Strategist)

**Core finding**: The product has a **throughline problem**. The throughline should be: "One person, publicly tracked, with AI — watch what happens." Every page should connect to this through one click. Currently, many pages feel like standalone dashboards that happen to share a nav bar. The /sleep/ page doesn't connect to the /story/ page. The /platform/ page doesn't connect to the /chronicle/. There's no narrative tissue between the data and the human.

**Recommendation**: Every data page should have a "What this means for the journey" callout — one sentence connecting the metric back to the transformation story. And every narrative page (chronicle, story) should have a "See the data behind this" link. The throughline is the connective tissue, and right now it's missing.

**Priority item**: Add throughline connectors to the 5 most-visited pages: Homepage, Story, Chronicle, Live, Platform.

---

### Tyrell Washington (Design)

**Core finding**: The design system is strong — tokens, monospace typography, grid-based layouts, dark mode with green accents — this is a distinctive aesthetic. But it's **optimized for one audience** (developers) and it alienates everyone else. The terminal-inspired design says "this is a technical tool" before the visitor reads a single word.

**Recommendation**: For April 1, don't change the design system — but **add warmth to story pages**. The chronicle articles should use the serif font prominently. The story page should feel like editorial journalism, not a dashboard. The technical pages can keep the terminal aesthetic. The story pages should break from it.

**Priority item**: Story page typography and spacing when the chapter content is implemented. The placeholder-hidden state we just shipped is better than showing empty prompts, but the page needs actual content designed with editorial care.

---

### Jordan Kim (Growth)

**Core finding**: The site has **no clear subscriber funnel**. There are 4+ subscribe CTAs but they're all identical messaging ("Real numbers from 19 data sources"). There's no sample newsletter issue. There's no "what you'll get" explainer. The sticky subscribe bar is aggressive for a site with 4 chronicle articles. The subscriber proposition needs to be specific: "Every Wednesday, Elena Voss writes about what happened in my data this week. Here's a sample."

**Recommendation**: Create a /chronicle/sample/ page (referenced in the CTA but doesn't exist yet). Differentiate subscribe CTAs by context — the chronicle page CTA should emphasize the writing, the homepage CTA should emphasize the experiment, the data pages should emphasize the insights.

**Priority item**: /chronicle/sample/ page before April 1 launch. Without a sample issue, the subscribe conversion rate will be near zero.

---

### Ava Moreau (Content Strategy)

**Core finding**: The content engine has promising pieces — Elena's voice is distinct, the chronicle articles are well-written, the interview material is raw and powerful. But **the content isn't on the site**. The story drafts sit in a markdown file. The homepage discovery cards are fake. The story page has no content. The chronicle page has only 4 articles (now, after removing 2). The content problem is the #1 barrier to launch, ahead of any design or technical issue.

**Recommendation**: Implement the story chapter drafts as the single highest-priority task. Even imperfect prose on the site is infinitely better than hidden placeholder blocks. The chapters don't need to be perfect — they need to be there. Matthew can redline after they're live.

**Priority item**: Get STORY_DRAFTS_v1.md content into /story/index.html. This is the unlock for the entire site.

---

## PART 3: PAGE-BY-PAGE PRIORITY RANKING

Ranked by urgency for April 1 readiness. Score is 1-10 (10 = needs most work).

| Rank | Page | Score | Primary Issue | Board Lead |
|------|------|-------|---------------|------------|
| 1 | **/story/** | 10 | Chapters 1, 4, 5 missing. Chapters 2, 3 have placeholder blocks hidden. Most important emotional content not on site. | Ava + Mara |
| 2 | **Homepage** | 9 | Hero too dense (11 elements). Fake discovery cards (integrity risk). Multiple conflicting CTAs. No clear entry path for casual visitors. | Sofia + Lena |
| 3 | **/chronicle/** | 6 | Only 4 articles. Week numbering has gaps (removed -2 and -5). No sample issue page. No Elena bio. | Ava + Jordan |
| 4 | **/subscribe/** | 6 | No sample issue. No "what you'll get." Subscribe page should be the conversion page, not just a form. | Jordan |
| 5 | **/about/** | 5 | Content is solid but "production code" line still needs the rewording from the audit. Press section is premature (no press yet). Speaking section is premature. | Sofia |
| 6 | **/live/** (Pulse) | 4 | Strong page when data is populated. Empty states need better fallbacks. Should be promoted as a flagship page. | Mara + James |
| 7 | **/character/** | 4 | Concept is excellent. Needs the story connection ("this score tracks my transformation"). | Raj |
| 8 | **/discoveries/** | 5 | Timeline data is now cleaner (seed experiments removed). But the page depends on data that hasn't accumulated yet. Needs a "discoveries populate as the experiment runs" honest state. | Lena + Raj |
| 9 | **/platform/** | 3 | Strongest page for technical audience. Minor: Lambda/tool counts should auto-update from public_stats.json. | James |
| 10 | **/builders/** | 7 | This is the HN landing page and it's not built yet. Needs content for technical audience specifically. | James + Jordan |
| 11 | **/experiments/** | 5 | All seed experiments just abandoned. Page will show empty state. Needs "experiments begin April 1" messaging. | Lena |
| 12 | **Data pages** (/sleep/, /glucose/, /nutrition/, /training/) | 4 | Good structure, dependent on data accumulation. Low priority for April 1 — they work when data exists. | James |
| 13 | **/cost/** | 3 | Clean, effective, complete. Minor updates only. | Dana (tech board) |
| 14 | **/methodology/** | 4 | Needs personal voice per the Tier 3 content audit. | Lena + Ava |
| 15 | **/weekly/** | 5 | Weekly Snapshot page — needs content after first week of real data. | Ava |

---

## PART 4: PRE-LAUNCH BLOCKERS (must fix before April 1)

1. **Story page content** — Implement STORY_DRAFTS_v1.md chapters into HTML. This is the site's emotional core.
2. **Homepage discovery cards** — Remove fake correlation stats. Replace with narrative insight cards from interview OR honest "coming soon" treatment.
3. **Chronicle numbering** — Re-number remaining articles to eliminate gaps, or add a note explaining the prequel numbering.
4. **Subscribe sample** — Create /chronicle/sample/ page so visitors know what they're subscribing to.
5. **About page** — Fix "production code" wording per audit.
6. **Homepage hero simplification** — Reduce from 11 elements to 4-5. Lead with the human story, not the technical stats.

---

## PART 5: NOTES FOR BROADER BOARDS

### For the Personal Board
- The story drafts reveal deep patterns around coping, grief, and the cycle of weight loss/regain. The Personal Board should review whether the "What the Data Has Shown" chapter (Ch4) appropriately frames the platform's failure to intervene during the DoorDash spiral. This is the most honest and most powerful section — and also the most vulnerable.
- Privacy guardrails from the Elena Prequel Brief should be cross-checked against the published chapter content.

### For the Technical Board
- James Okafor's finding about 7+ API calls per homepage load should be reviewed as an architecture item. The pre-render-to-JSON pattern could be extended.
- The /builders/ page (HN audience landing) needs technical content — architecture diagrams, cost breakdown, "how to build your own" guide. This may require new site-api endpoints or static asset generation.
- The experiments page will need a fresh state after all 4 seed experiments were abandoned. Consider adding an "experiments begin Day 1" placeholder.
- CI/CD pipeline (R13 #1, now closed) means site deploys are automated — but CloudFront invalidation timing for HTML changes should be verified.

---

## PART 6: SESSION PLAN

Given the scope of findings, recommended session breakdown:

| Session | Focus | Deliverable |
|---------|-------|-------------|
| **This session** | This review document | ✅ Done |
| **Next session** | Story page content implementation | Chapters 1-5 live in HTML |
| **Session +2** | Homepage redesign (hero simplification + discovery card fix) | Cleaned homepage |
| **Session +3** | Chronicle polish (sample page, numbering, Elena bio) | Chronicle launch-ready |
| **Session +4** | Subscribe funnel + /builders/ page | Growth infrastructure |
| **Session +5** | Full board review (all 3 boards) | Launch readiness verdict |

---

*Review conducted by the Product Board of Directors: Mara Chen, James Okafor, Sofia Herrera, Dr. Lena Johansson, Raj Mehta, Tyrell Washington, Jordan Kim, Ava Moreau.*

*Next review: Post-launch Week 1 (target: April 8, 2026)*
