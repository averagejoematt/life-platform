# averagejoematt.com — V2 Page Design Briefs
### For Claude Code Execution | March 21, 2026

> **Source**: CEO Manual Audit (March 21, 2026) + Expert Panel Strategy Review + Board Summit #3
> **Purpose**: Page-by-page rebuild specifications. Each brief is self-contained — Claude Code should be able to rebuild any page using only (1) this brief, (2) the global rules below, and (3) the existing tokens.css / base.css / nav.js.
> **Execution model**: One page per session. Read global rules first, then the specific page brief. Deploy after each page.

---

## GLOBAL RULES — Apply to Every Page

These rules override any existing page patterns. Implement them on every page rebuild.

### G1: Zero Hardcoded Metrics

**Rule**: Every number displayed on the site MUST come from `public_stats.json` or an API endpoint. No number may be written as a literal in HTML.

**Pattern**:
```html
<!-- WRONG -->
<span>19 data sources</span>

<!-- RIGHT -->
<span id="stat-data-sources">—</span>
<script>
  fetch('/public_stats.json?t=' + Date.now())
    .then(r => r.json())
    .then(d => {
      document.getElementById('stat-data-sources').textContent = d.platform.data_sources || '19';
    });
</script>
```

**Affected fields**: data_sources, mcp_tools, lambdas, days_on_journey, weight_lbs, hrv_ms, recovery_pct, streak, progress_pct, character score, pillar scores, intelligence feature count, and ANY other quantitative claim.

**Null handling**: If a value is null or undefined, display `"—"` with a tooltip `title="Data unavailable"`. Never show `0.00%` or blank — be explicit.

### G2: Navigation Consistency

All pages use the shared nav structure already shipped in Sprint 8 (5-section dropdowns, hamburger overlay, bottom nav, 5-column footer). The nav is injected via `deploy/deploy_sprint8_nav.py`. Do NOT create custom nav per page.

**Bottom nav links**: Home | Live | Character | Chronicle | Ask
**Hamburger + footer**: 5 sections — The Story, The Data, The Science, The Build, Follow

If a page currently has an old/outdated nav (e.g., journal subpages), re-run the nav patch: `python3 deploy/deploy_sprint8_nav.py`

### G3: Contextual "Reading Path" CTA

Every page ends with a contextual link to the next logical page in the story loop. Place this ABOVE the footer, inside a styled section.

**Pattern**:
```html
<section class="reading-path" style="
  padding: var(--space-10) var(--page-padding);
  border-top: 1px solid var(--border);
  text-align: center;
">
  <span style="font-size:var(--text-2xs);letter-spacing:var(--ls-tag);text-transform:uppercase;color:var(--text-faint);display:block;margin-bottom:var(--space-3)">
    Continue the story
  </span>
  <a href="/[next-page]/" style="
    font-family:var(--font-display);font-size:var(--text-h3);
    color:var(--accent);text-decoration:none;letter-spacing:var(--ls-display);
  ">[CTA text] →</a>
  <p style="font-size:var(--text-xs);color:var(--text-muted);margin-top:var(--space-2)">
    [One-line description of what's on the next page]
  </p>
</section>
```

**The reading path chain**:
| This page | Next page | CTA text |
|-----------|-----------|----------|
| `/` (Home) | `/story/` | Read the origin story |
| `/story/` | `/live/` | See where I am today |
| `/live/` | `/character/` | How the score is computed |
| `/character/` | `/habits/` | The habits that feed the score |
| `/habits/` | `/protocols/` | The protocols behind the habits |
| `/protocols/` | `/experiments/` | What I'm actively testing |
| `/experiments/` | `/discoveries/` | What the data has proven |
| `/discoveries/` | `/intelligence/` | How the AI brain works |
| `/intelligence/` | `/ask/` | Ask the data yourself |
| `/ask/` | `/subscribe/` | Get this in your inbox weekly |
| `/platform/` | `/cost/` | What this costs to run |
| `/cost/` | `/tools/` | Try the tools yourself |
| `/board/` | `/methodology/` | The statistical framework |
| `/sleep/` | `/glucose/` | Another deep-dive: glucose |
| `/glucose/` | `/supplements/` | What I take and why |
| `/supplements/` | `/benchmarks/` | How I measure against targets |
| `/about/` | `/story/` | Read the full story |
| `/accountability/` | `/character/` | The score behind the accountability |
| `/subscribe/` | `/chronicle/` | Read the latest chronicle |
| `/chronicle/` | `/ask/` | Ask the data anything |

### G4: Page Section Identity

Every page should clearly communicate which of the 5 site sections it belongs to. Use this eyebrow label at the top of the first content section:

```html
<div class="eyebrow" style="margin-bottom:var(--space-3)">
  [Section name: The Story | The Data | The Science | The Build | Follow]
</div>
```

### G5: N=1 Disclaimer (Science pages only)

Pages in "The Science" section must include this disclaimer once, near the bottom but above the reading-path CTA:

```html
<div style="
  padding:var(--space-4) var(--space-5);
  border:1px solid var(--border-subtle);
  background:var(--surface);
  font-size:var(--text-xs);color:var(--text-faint);
  font-family:var(--font-mono);line-height:var(--lh-mono);
  max-width:640px;
">
  This is a single-person experiment, not a clinical study. Correlation does not mean causation.
  What works for me may not work for you. I track rigorously but I'm not a doctor.
  Consult a healthcare provider before making health changes.
</div>
```

### G6: Content Filter

Any page displaying habit names, vice data, or temptation data must filter blocked terms. Client-side check:

```javascript
const BLOCKED_VICES = ['No porn', 'No marijuana'];
const BLOCKED_KEYWORDS = ['porn', 'pornography', 'marijuana', 'cannabis', 'weed', 'thc'];
function isBlocked(text) {
  const lower = text.toLowerCase();
  return BLOCKED_KEYWORDS.some(k => lower.includes(k));
}
```

### G7: Design Token Usage

Never hardcode colors, fonts, spacing, or animation values. Always use tokens.css variables:
- Colors: `var(--accent)`, `var(--text)`, `var(--text-muted)`, `var(--surface)`, etc.
- Fonts: `var(--font-display)` for headlines, `var(--font-mono)` for labels/data, `var(--font-serif)` for prose, `var(--font-sans)` for UI
- Spacing: `var(--space-N)` where N = 1,2,3,4,5,6,8,10,12,16,20,24,32
- Journal/Chronicle pages use `var(--accent-journal)` instead of `var(--accent)` for accent color

### G8: Mobile Responsiveness

Every page must include responsive breakpoints. Standard pattern:
```css
@media (max-width: 900px) {
  /* Two-column grids → single column */
  .grid-2col { grid-template-columns: 1fr; }
}
@media (max-width: 480px) {
  /* Reduce padding, font sizes */
  section { padding-left: var(--page-padding-sm); padding-right: var(--page-padding-sm); }
}
```

### G9: Data Fetch Pattern

Standard pattern for loading data from public_stats.json or API:
```javascript
(async function() {
  const setText = (id, val) => { const el = document.getElementById(id); if (el) el.textContent = val; };
  try {
    const r = await fetch('/public_stats.json?t=' + Date.now(), { cache: 'no-store' });
    if (!r.ok) throw new Error('no data');
    const data = await r.json();
    // populate elements...
  } catch(e) {
    // Static fallback already visible with "—" placeholders
  }
})();
```

For pages needing dedicated API endpoints, use:
```javascript
const API_BASE = 'https://averagejoematt.com';
const res = await fetch(`${API_BASE}/api/[endpoint]`);
```

### G10: Scroll Reveal Animation

All content sections use the reveal animation class:
```html
<section class="reveal">...</section>
```
Requires `reveal.js` script at bottom of page.

---

## PAGE BRIEFS

---

## 1. HOME (`/`)

**Section**: The Story
**Status**: Live — needs data fixes + content refinements
**File**: `site/index.html`

### CEO Audit Findings
- Marquee: "0.00% to goal" is wrong (should reflect actual weight loss %)
- Marquee: Streak shows a hyphen — should show "0" explicitly if no active streak
- Marquee: "Signal / Human Systems" is confusing — replace or remove
- Marquee: Weight is blank — must pull from most recent weigh-in
- "19 data sources" — is this hardcoded? Must be parameterized
- "Day on Journey" is blank
- "Current streak" blank — show 0, and consider adding "longest streak since started"
- Heart rate graph — is it real data or decorative? If decorative, either wire to real data or remove. A fake graph on a site about radical transparency is a credibility killer.
- "Numbers this month" says +11.8lb gained in 30 days — but since journey started, weight has been lost. Need BOTH: "30-day: +11.8 lbs" AND "Journey total: -14.3 lbs" with clear labels
- Recovery 89 — means nothing without context. Add range label: "89/100 (Good)"

### Design Intent
The homepage is the first 5 seconds. It must answer: Who is this person? What are they doing? Is this real? Every number must be live and correct. The moment dashes become real numbers, the site transforms from a landing page into a living thing.

### Required Changes

**Ticker (marquee)**:
1. All ticker values must populate from `public_stats.json`. Already partially implemented — verify weight, streak, journey % are populating correctly.
2. Replace "SIGNAL / HUMAN SYSTEMS" with the site tagline: `"ONE PERSON. 19 DATA SOURCES. ZERO FILTERS."` (already present as alternate text — remove the Signal/Human Systems variant entirely).
3. Streak: if value is 0, display `"0D STREAK"` not `"—"`. Already handled in current JS — verify the public_stats.json pipeline outputs `tier0_streak: 0` not null.
4. Journey %: if weight_lbs is null in public_stats.json, this cascades. Fix the data pipeline (daily_brief_lambda.py) to always populate weight_lbs from the most recent Withings reading.

**Hero section**:
1. "Days on Journey" stat chip: verify `hero.days_on_journey` or `j.days_in` is populated. Current fallback calculates from Sept 1 2024 — that's the platform start, but journey start for weight should be Feb 22 2026. Verify the correct date is used.
2. "Current Streak" chip: display "Day 0" when no active streak, not blank.
3. "Data Sources" chip: already wired to `p.data_sources` — verify it's populated in public_stats.json.
4. Heart rate canvas: currently driven by `window.updateHeartbeat(raw)` from vitals data. Verify it's receiving real rhr_bpm, recovery_pct, hrv_ms from public_stats.json. If data is null, hide the canvas entirely rather than showing an animation with "— · — · —" in the label.

**"Numbers this month" sparkline section**:
1. Weight sparkline: When showing the delta, show TWO lines:
   - `"▼ 14.3 lbs (journey)"` in accent color
   - `"+11.8 lbs (30d)"` in yellow/warning color
   This addresses Matthew's confusion about seeing weight gain when he's lost weight overall.
2. Recovery sparkline: Add context label after the number. Pattern: `"89% (Good)"` or `"45% (Low)"`. Thresholds: ≥67 = Good (green), 34-66 = Fair (yellow), <34 = Low (red).
3. HRV sparkline: Already shows trend text — good. Verify it's from real data.

**AI Brief section**:
1. The brief_excerpt from public_stats.json should populate. If null, show a fallback message: "No brief generated today. Daily briefs resume when data logging resumes." Do NOT show hardcoded sample text that implies active monitoring when logging has stopped.

**"Day 1 vs Today" comparison card**:
1. The "Today" column must show live data from public_stats.json.
2. Add the 30-day delta line below weight: `id="compare-weight-30d"` already exists — verify it populates.
3. Recovery: show range label. Already partially implemented with `compare-recovery-label` — verify format is `"89/100 (Good)"`.

**Feature discovery cards grid**:
1. Remove duplicate "CHARACTER" card (appears twice — one links to character, the other also links to character with different copy).
2. Verify feat-streak and feat-char-score populate from public_stats.json.

**"Why I'm doing this in public" about section**:
1. "19 data sources" in the prose: keep as static text here (it's narrative, not a live metric), but ensure the count in the sources grid matches.
2. "Read the journal" link → update to "Read the chronicle" and point to `/chronicle/`.

**Subscribe CTA section**:
1. The subscribe form must actually send confirmation emails. This is a backend fix (subscriber Lambda in us-east-1). The frontend should show appropriate states: "Subscribing..." → "Check your inbox to confirm." → or error message.

### Reading Path CTA
> Continue the story → `/story/` → "Read the origin story"

---

## 2. STORY (`/story/`)

**Section**: The Story
**Status**: Live — structure exists, content pending (Matthew to write)
**File**: `site/story/index.html`

### CEO Audit Findings
- Data points are blank (e.g., weight)
- "95 intelligence tools" — is this hardcoded? Parameterize.

### Design Intent
This is the emotional entry point. The origin story page. It should make a stranger care about Matthew as a human before showing them any data. Lead with vulnerability, not metrics.

### Required Changes

1. **All metrics must be dynamic**: Replace any hardcoded numbers (95 tools, weight, etc.) with spans populated from public_stats.json using the G1 pattern.
2. **Weight display**: If current weight is shown, pull from `public_stats.json → vitals.weight_lbs`. Show "—" if null rather than blank.
3. **Platform stats**: Intelligence tools count should come from `public_stats.json → platform.mcp_tools`.
4. **Content**: The page structure exists with 5 chapter sections. Matthew will write the prose. The design brief for Claude Code is: ensure the template supports long-form prose with proper typography (`var(--font-serif)` for body text, `var(--lh-body)` line height, `max-width: var(--prose-width)` for readability).

### Reading Path CTA
> See where I am today → `/live/` → "Live metrics updated daily"

---

## 3. LIVE (`/live/`)

**Section**: The Data
**Status**: Live — very basic, weight only
**File**: `site/live/index.html`

### CEO Audit Findings
- "This page is very light where I expect it should be the most impressive... It only shows weight, but what about habits, exercise types, all of the other things we are logging, state of mind, journal."
- "We are boasting how intelligent this system is and then on the live view it's a very basic graph about weight."

### Design Intent
This is THE differentiating page. The live dashboard. It should be a multi-metric, visually rich view of the entire experiment — not just a weight graph. Think mission control for a human body. This page absorbs content from the defunct `/progress/` and `/results/` pages.

### Required Changes — Full Rebuild

**Layout**: Full-width dashboard grid. 3 columns on desktop, 2 on tablet, 1 on mobile.

**Section 1: Weight Timeline** (existing, enhance)
- Keep the interactive weight chart with life events overlay
- Add: journey total delta prominently displayed
- Add: 30-day trend indicator with direction arrow

**Section 2: Vital Signs Grid** (NEW)
- 4 metric cards in a row: Weight, HRV, Recovery, RHR
- Each card: current value (large), 30-day sparkline, trend arrow, contextual label
- Data source: `/api/vitals` or `public_stats.json`

**Section 3: Body Composition** (NEW — when DEXA data exists)
- If DEXA data available: body fat %, lean mass, bone density
- If not yet: hide this section entirely (don't show empty)

**Section 4: Sleep Snapshot** (NEW)
- Last night's sleep: duration, efficiency, REM/Deep/Light breakdown as stacked bar
- 7-day sleep trend sparkline
- Data source: `public_stats.json → vitals` or `/api/vitals`

**Section 5: Habit Adherence** (NEW)
- Mini heatmap: last 7 days × Tier 0 habits (compact view)
- T0 streak counter
- Overall adherence % for the week
- Data source: `/api/habit_streaks` or new `/api/habits` endpoint

**Section 6: Training Load** (NEW)
- This week's exercise: type, duration, strain score
- Zone 2 minutes: actual vs 150-min target, displayed as a progress ring
- Data source: `public_stats.json → training` or Whoop data

**Section 7: State of Mind** (NEW)
- Latest mood/state from journal or state_of_mind logging
- If no recent data: "No state logged recently" placeholder
- Simple 1-5 scale visualization or emoji-based

**Section 8: Character Score Summary** (NEW)
- Current overall score + level
- Mini radar chart of 7 pillars (simplified)
- Link to full `/character/` page

**Section 9: "Since Journey Start" comparison**
- Replaces the separate `/progress/` page
- Day 1 baseline vs today for all major metrics
- Clear visual improvement indicators (green up arrows, red down arrows)

**API endpoints needed**: 
- Existing: `/api/vitals`, `/api/weight_progress`, `/api/timeline`, `/api/character`, `/api/habit_streaks`
- New (if not yet available): `/api/habits` for compact heatmap data

### Reading Path CTA
> How the score is computed → `/character/` → "7 pillars. One score. Real data."

---

## 4. JOURNAL → CHRONICLE (`/journal/` → `/chronicle/`)

**Section**: Follow
**Status**: Live — needs rename, nav fix, workflow repair
**File**: `site/journal/index.html` → rename to `site/chronicle/index.html`

### CEO Audit Findings
- Top menu shows wrong date unlike other pages
- Navigation color is yellow — looks out of place vs other pages
- Journal mechanism is broken — missed this week's Wednesday chronicle
- Individual blog posts have old/outdated menu
- "Journal" implies personal notes — this is actually investigative journalism by an AI narrator. Rebrand to "Chronicle" or "The Measured Life"
- Request: create an entry for this week — an interview about why Matthew failed and needs to restart after 2 weeks of sick days
- Request: add preview/approval flow — drafts go to Matthew first before publishing

### Design Intent
This page is Elena Voss's investigative series — "The Measured Life." It's not a personal journal. It's an AI journalist documenting a human experiment. The tone should be editorial, curious, unflinching. The amber accent color is actually correct for this section — it differentiates the chronicle content from the data-green of the rest of the site.

### Required Changes

1. **Rename**: `/journal/` → `/chronicle/`. Set up redirect: `/journal/` → `/chronicle/` (301). Update all internal links, nav references, bottom nav, footer, hamburger. Update sitemap.xml.

2. **Fix nav on all chronicle pages**: Run `python3 deploy/deploy_sprint8_nav.py` to re-patch all journal post HTML files. Verify all `/journal/posts/week-XX/` pages get the current nav. Update these to `/chronicle/posts/week-XX/` paths.

3. **Date display in header**: The nav date element `#nav-date` should show today's date consistently. If the chronicle pages have a separate date element, sync it with the global nav date pattern.

4. **Amber accent**: Keep it. The amber differentiates chronicle content from data pages. But ensure it's using `var(--accent-journal)` consistently, not random hex values.

5. **Page structure**:
   - Hero: "The Measured Life" title, Elena Voss byline, "An AI journalist documents one man's experiment with radical self-measurement"
   - Latest entry: featured card with headline, date, opening paragraph
   - Archive: chronological list of all entries with thesis lines
   - Subscribe CTA: "Get the chronicle in your inbox every Wednesday"

6. **Backend fixes** (not Claude Code, but document for the platform session):
   - Debug Wednesday auto-publish Lambda — why did it miss this week?
   - Implement preview/approval flow: chronicle draft → email to Matthew → approve → publish
   - Write this week's entry: the restart interview (Matthew provides direction, Elena Voss narrates)

### Reading Path CTA
> Ask the data yourself → `/ask/` → "What questions do you have about this experiment?"

---

## 5. PLATFORM (`/platform/`)

**Section**: The Build
**Status**: Live — trying to do too many things
**File**: `site/platform/index.html`

### CEO Audit Findings
- "This page seems to be trying to do a few different things"
- Journey, weight, the 'why' seems out of place — covered elsewhere
- Should focus on: architecture, what it's built on, intelligence layer, tool structure, costs
- "Should it have a higher level architecture diagram that makes it look cool?"
- "What would a CIO/CTO read on this page for it to be impressed?"

### Design Intent
This is the tech showcase. The page most likely to go viral on Hacker News or tech Twitter. Strip ALL human-journey content (that belongs on `/story/` and `/live/`). Focus exclusively on: what this system is, how it's built, and why it's technically interesting.

### Required Changes — Content Restructure

**Remove**: Any weight references, journey narrative, "why I'm doing this" content. That's `/story/`.

**Keep/Enhance these sections in this order**:

1. **Hero**: "THE PLATFORM" — one-liner: "A personal health intelligence system. [X] Lambdas. [Y] AI tools. [Z] data sources. ~$[N]/month on AWS."
   - All numbers from public_stats.json

2. **Architecture Diagram** (NEW — highest priority):
   - High-level system diagram showing: Data Sources → Ingestion (Lambda webhooks) → DynamoDB (single table) → Compute Pipeline (scheduled Lambdas) → Intelligence Layer (MCP tools + Claude) → Outputs (emails, website, buddy page)
   - Use SVG. Make it interactive: hover on a component to see what it does.
   - This is the centerpiece visual. Should look like a CTO-level system design.

3. **Data Flow**: How data moves from 19 sources through the system. Show the pipeline stages.

4. **Intelligence Layer**: What IC features exist, what they detect. Link to `/intelligence/` for deep dive.

5. **Tool Structure**: MCP tool count, module breakdown. High-level, not a full catalog.

6. **Cost Breakdown**: Monthly cost summary. Link to `/cost/` for details.

7. **Tech Stack**: AWS services used, with counts. DynamoDB, Lambda, S3, CloudFront, EventBridge, SES, Secrets Manager, KMS.

**Target persona**: An engineering manager or CTO evaluating "what can one person build with Claude?" This page is the proof.

### Reading Path CTA
> What this costs to run → `/cost/` → "~$13/month for a personal health AI"

---

## 6. START (`/start/`) → REMOVE

**Section**: N/A — being removed
**Status**: Live — redundant

### CEO Audit Findings
- "Is this essentially a sitemap?"
- Content is repetitive ("ONE PERSON 19 DATA") — visitor has likely seen this already
- Not tracing the user journey

### Required Changes
1. **Remove page**: Delete `site/start/index.html`
2. **Redirect**: Add redirect from `/start/` → `/` (home page)
3. **Update sitemap.xml**: Remove `/start/` entry
4. **Update any internal links** pointing to `/start/`

---

## 7. SUBSCRIBE (`/subscribe/`)

**Section**: Follow
**Status**: Live — confirmation email broken
**File**: `site/subscribe/index.html`

### CEO Audit Findings
- "When I submit an email to subscribe, I do not receive a confirmation in my inbox"

### Design Intent
Email is the retention backbone. This page must work flawlessly. A broken subscribe form on a site about data integrity is deeply ironic.

### Required Changes

1. **Fix the subscriber Lambda** (backend): Debug `life-platform-subscriber` Lambda in us-east-1. Trace the flow: form POST → Lambda → SES → inbox. Identify where it breaks.

2. **Frontend form states**:
   - Default: email input + "Subscribe" button
   - Submitting: "Subscribing..." (button disabled)
   - Success: "✓ Check your inbox to confirm your subscription."
   - Error: "[specific error message]" in yellow
   - Already subscribed: "You're already subscribed! Check your inbox for the latest issue."

3. **Value proposition**: The page should sell the newsletter.
   - What you get: "Every Wednesday: the real weight, one chart, one AI insight, one honest reflection"
   - How long: "A 3-minute read"
   - Social proof: subscriber count (once meaningful — hide until >50)
   - Sample: Link to `/chronicle/sample/` — "See a sample issue"

### Reading Path CTA
> Read the latest chronicle → `/chronicle/` → "Elena Voss's latest investigation"

---

## 8. ASK (`/ask/`)

**Section**: Follow
**Status**: Live — UX issues
**File**: `site/ask/index.html`

### CEO Audit Findings
- "When I ask a question the flow to hit back is awkward — I can't go back and return to the start of the ask page"
- "It says subscribe for more, but we don't offer that yet — remove it"

### Design Intent
The interactive AI showcase. A visitor types a question and gets an answer from Matthew's actual data. The UX must be smooth — ask a question, get an answer, easily ask another.

### Required Changes

1. **Back navigation**: After receiving an answer, show a prominent "Ask another question" button that resets the form. Don't rely solely on browser back.
   ```html
   <button onclick="resetAskForm()" class="btn btn--ghost" style="margin-top:var(--space-4)">
     ← Ask another question
   </button>
   ```

2. **Remove "subscribe for more"**: Strip any CTA that references subscription features not yet functional. If the subscribe flow is fixed (see brief #7), can add back later.

3. **Suggested questions**: Show 3-4 pre-written questions as clickable chips above the input field:
   - "How did Matt sleep last week?"
   - "What's his HRV trend?"
   - "Is the caloric deficit working?"
   - "What habit has the biggest impact?"

4. **Rate limit display**: Show remaining questions: "3 questions remaining (resets hourly)" for anonymous visitors.

### Reading Path CTA
> Get this in your inbox weekly → `/subscribe/` → "The Weekly Signal — every Wednesday"

---

## 9. CHARACTER (`/character/`)

**Section**: The Data
**Status**: Live — needs narrative intro + scoring fix
**File**: `site/character/index.html`

### CEO Audit Findings
- "I feel some intro section actually misses here — this could be a real cool unique story"
- "Show my avatar and the journey it goes on"
- "Craft some achievement badges"
- "Its not just lose weight, gain levels — its considering my journal text, looking at my happiness"
- "How does the user realize this RPG gamification is not about just the metrics, its about the science of happiness and fulfillment?"
- "Everything seems in lockstep for scores — I don't think everything improved in unison"
- "Very little data on relationships or mind — rethink how we compute this game"

### Design Intent
The Character Sheet is one of the most original features of the platform. But it needs framing. A visitor should understand within 10 seconds that this isn't a weight tracker — it's a holistic experiment measuring whether data-driven self-improvement actually makes someone happier and more fulfilled. The RPG metaphor makes it tangible.

### Required Changes

**Section 1: Introduction** (NEW — add above the radar chart)
```
THE CHARACTER SHEET

This isn't a weight tracker. It's an experiment: can you quantify whether
someone is actually becoming a better version of themselves?

Seven pillars. Each measured from real data — not self-reported feelings.
Sleep quality from Whoop and Eight Sleep. Nutritional discipline from
MacroFactor. Mental wellbeing from journal sentiment analysis. Movement
from Garmin and Strava. Metabolic health from CGM and labs.

The score updates daily. Some days it goes down. That's the point —
every failure is data.
```

**Section 2: Avatar** (NEW — below intro, above radar chart)
- Display a simple character avatar that reflects current state
- Phase 1: static illustration/icon that changes based on overall tier (1-5)
- Phase 2 (future): composable SVG with pillar-specific visual elements
- For now, use a simple gamer-style icon with mood state: happy (score >70), neutral (40-70), struggling (<40)
- Avatar should be visually prominent — this is the character's face

**Section 3: Radar Chart** (existing — enhance)
- The 7-pillar radar chart stays
- Fix: scoring lockstep issue. If pillars are all moving identically, the issue is in the compute pipeline (character_sheet module). Flag for backend review: each pillar should have independent data sources and independent scoring curves.
- Show individual pillar scores with breakdown: "Sleep: 72/100 (Tier 3) — driven by 7.4h avg duration, 85% efficiency, 22% deep sleep"

**Section 4: Achievement Badges** (NEW — absorbs `/achievements/` page)
- Badge wall: earned badges with dates, pending badges greyed out
- Categories: Streak badges, Tier badges, Vice badges, Experiment badges, Data badges, Milestone badges
- Apply content filter (G6) — exclude badges related to blocked vices
- Data source: new `/api/achievements` endpoint or compute client-side from character data

**Section 5: Scoring Methodology** (existing — keep)
- How each pillar is scored, what data feeds it
- Transparency about limitations: "Relationships and Mind pillars have limited data sources — scores here are less confident"

### Reading Path CTA
> The habits that feed the score → `/habits/` → "65 habits. Daily tracking. See the heatmap."

---

## 10. PRIVACY (`/privacy/`)

**Section**: Follow (footer link)
**Status**: Live — wrong email
**File**: `site/privacy/index.html`

### CEO Audit Findings
- "My email is wrong — unless you can set up matt@averagejoematt.com in AWS and have it forward to awsdev@mattsusername.com"

### Required Changes

**Option A** (preferred): Set up `matt@averagejoematt.com` as an email address via AWS SES or Route53 + email forwarding, then update the privacy page to use it.

**Option B** (quick fix): Update the email on the privacy page to Matthew's correct contact email.

This is a 1-line HTML change once the correct email is determined. No design changes needed.

---

## 11. TOOLS (`/tools/`)

**Section**: The Build
**Status**: Live — functional, could expand
**File**: `site/tools/index.html`

### CEO Audit Findings
- "I do sort of like this, I wonder what else we can use here"

### Design Intent
Interactive tools that let visitors engage with the platform's capabilities. This is the "try it yourself" page.

### Required Changes

1. **Keep existing tools** — they work.
2. **Add 2-3 new interactive tools** (Phase 2):
   - **Sleep Score Calculator**: Enter your sleep duration, bedtime, wake time → get a simplified score using the platform's methodology
   - **Habit Streak Calculator**: Enter a habit you want to build → see how compound streaks build value over time (mirrors the vice streak compounding math)
   - **Centenarian Benchmark Check**: Enter your lifts → see where you stand vs. Attia's framework (could also live on `/benchmarks/`)
3. **Each tool** should: show a brief explanation of the methodology, accept user input, display results, and link to the relevant platform page for the full version.

### Reading Path CTA
> See the full architecture → `/platform/` → "How all these tools connect"

---

## 12. COST (`/cost/`)

**Section**: The Build
**Status**: Live — accuracy uncertain
**File**: `site/cost/index.html`

### CEO Audit Findings
- "How accurate is this vs. static hardcoded information?"
- "This seems like it would be a sub-category under the technical/architecture side"

### Design Intent
Cost transparency is part of the "building in public" ethos. This page should show real, current costs — not a snapshot that goes stale. Position it clearly as a sub-page of the platform/tech section.

### Required Changes

1. **Verify data accuracy**: Audit every cost figure on the page. Is it pulled from a data source, or hardcoded? If hardcoded, add these to the parameterization sweep.
2. **Ideal implementation**: A monthly Lambda that reads AWS Cost Explorer API and writes cost breakdown to `public_stats.json → costs`. The page then renders from this data.
3. **Fallback**: If dynamic costs are too complex now, at minimum add a "Last verified: [date]" timestamp so visitors know when the data was checked.
4. **Section identity**: Add eyebrow label "The Build" to clearly position this in the tech section.

### Reading Path CTA
> Try the tools yourself → `/tools/` → "Interactive platform tools"

---

## 13. BOARD (`/board/`)

**Section**: The Build
**Status**: Live — needs persona updates
**File**: `site/board/index.html`

### CEO Audit Findings
- "Replace Andrew Huberman and Peter Attia with equivalent people that have less public scandal"
  - Huberman: infidelity reports
  - Attia: Epstein ties
  - "Similar moulds for their strengths"
  - Keep their science perspectives in internal prompts — just remove names/likenesses from public display
- "Should we also have the other boards (technical board, web board)?"
- "For my future use it would be good to say 'web board' or 'technical board' and you have all the personas there"

### Design Intent
The advisory board concept is clever and adds intellectual credibility. The public page should show the Personal Board (health/longevity experts). The Technical Board and Web Board are internal tools — consider showing them as expandable sections for tech-curious visitors, but they're not the primary content.

### Required Changes

1. **Replace personas in S3 config** (`s3://matthew-life-platform/config/board_of_directors.json`):
   - Andrew Huberman → **Dr. Andy Galpin** (exercise physiology, protocols focus, clean reputation)
   - Peter Attia → **Dr. Layne Norton** (longevity/nutrition, evidence-based, statistical rigor)
   - Keep Huberman and Attia perspectives in INTERNAL system prompts — just remove from public-facing surfaces

2. **Board page structure**:
   - Primary: Personal Board of Directors (health/longevity experts) — full cards with name, photo, expertise, "what they'd say about my experiment"
   - Secondary (expandable section): Technical Board — names and specialties only, collapsed by default
   - Tertiary (expandable section): Web Board — names and specialties, collapsed by default

3. **Interactive element**: Keep the `/api/board_ask` integration — visitors can ask a board member a question.

### Reading Path CTA
> The statistical framework → `/methodology/` → "How we maintain scientific rigor in an N=1 experiment"

---

## 14. METHODOLOGY (`/methodology/`)

**Section**: The Build
**Status**: Live — static content, fine
**File**: `site/methodology/index.html`

### CEO Audit Findings
- "Curious if this would be in some parent category similar to cost and architecture"

### Required Changes

1. **Section identity**: Add eyebrow "The Build" — position this clearly as part of the tech/science methodology section.
2. **Content is fine** — static explanation of N=1 methodology, correlation frameworks, statistical limitations.
3. **Link to explorer**: Ensure prominent link to `/explorer/` for the live correlation data.
4. No major rebuild needed — primarily a nav/section categorization update.

### Reading Path CTA
> See the live correlations → `/explorer/` → "23 metric pairs. Weekly Pearson analysis."

---

## 15. PROTOCOLS (`/protocols/`)

**Section**: The Science
**Status**: Live — needs expansion
**File**: `site/protocols/index.html`

### CEO Audit Findings
- "Expand with a separate page dedicated to habits, showing vices (excluding content-filtered ones), tier 0, 1, 2, 3, streak data"
- "A similar setup for supplements — why am I taking vitamin D?"
- "Link to discoveries when we have enough data for an N=1 conclusion"
- **"HOW DO WE THREAD THE NEEDLE OF THIS ENTIRE EXPERIMENT SO IT ALL TIES TOGETHER TO THE USER"**

### Design Intent
Protocols are the "what I do and why" page. Not just a list — each protocol should explain the rationale, link to the evidence, connect to the relevant experiment or discovery, and show compliance data. The throughline: every protocol exists because of a hypothesis, and every hypothesis is testable with data.

### Required Changes

1. **Structure by category**: Organize protocols into clear groups:
   - Morning Stack (habits, supplements, routines)
   - Training (Zone 2 target, strength protocol, recovery)
   - Nutrition (macro targets, meal timing, fasting windows)
   - Sleep (bedtime protocol, environment setup, Eight Sleep settings)
   - Mental/Recovery (journaling, state of mind logging, social connection)

2. **Per-protocol card**:
   ```
   [Protocol Name]
   What: Brief description
   Why: Scientific rationale (1-2 sentences)
   Compliance: [X]% adherence this month (from habit data)
   Connected experiment: [link to /experiments/ if one exists]
   Connected discovery: [link to /discoveries/ if data has proven something]
   ```

3. **Supplement sub-section**: Each supplement with: name, dose, timing, genome rationale (if applicable from SNP data), evidence confidence level (genome-justified / well-sourced / N=1 experiment), and link to the deep-dive at `/supplements/`.

4. **Throughline links**: Every protocol should link to at least one other page (experiment testing it, discovery confirming/denying it, habit tracking it).

5. **Content filter**: Apply G6 to exclude blocked vices from any habit displays.

### Reading Path CTA
> What I'm actively testing → `/experiments/` → "N=1 experiments with real data"

---

## 16. EXPERIMENTS (`/experiments/`)

**Section**: The Science
**Status**: Live — needs active use
**File**: `site/experiments/index.html`

### CEO Audit Findings
- "We need to start thinking how I actually use these so people can see what I am actively experimenting on"
- "Not so much for content but actually as a point for me and the platform and for you to monitor and give feedback on"
- Future idea: upvote/downvote system (needs auth — defer)

### Design Intent
The experiments page is the scientific soul of the project. When properly used, it shows the platform's rigor: hypothesis → protocol → data → conclusion. Even with few experiments, the structure demonstrates the methodology.

### Required Changes

1. **Active experiments**: Prominently display any currently-running experiments at the top with status: "IN PROGRESS — Day X of Y"

2. **Experiment card structure**:
   ```
   [Experiment Title]
   Status: Active / Completed / Inconclusive
   Hypothesis: "If I do X, then Y will change by Z"
   Protocol: What I'm doing differently
   Duration: Start date → End date (or "ongoing")
   Key metric: The primary measurement
   Result: [if completed] What happened + data
   ```

3. **Empty state**: If no experiments are running, show: "No active experiments right now. [X] completed experiments below. Next experiment starts when data logging resumes."

4. **Link to discoveries**: Completed experiments with confirmed results should link to `/discoveries/`.

5. **Future placeholder**: Add a note about planned interactivity: "Future: community voting on experiment results. Coming soon."

### Reading Path CTA
> What the data has proven → `/discoveries/` → "Confirmed findings from N=1 experiments"

---

## 17. SLEEP (`/sleep/`)

**Section**: The Science
**Status**: Live — thin on narrative and data
**File**: `site/sleep/index.html`

### CEO Audit Findings
- "Lacks narrative or data or purpose"
- "Is it just to show data that is in other spots?"
- "What would Dr. Matthew Walker (sleep scientist) think a dedicated sleep page should show?"
- "Should it show trend lines, bed times?"
- "Where is our throughline?"

### Design Intent
A deep-dive into sleep optimization. Think of it as a research report on one person's sleep, written with the rigor of a sleep lab. Not just numbers — context, trends, experiments, what the data means, and what changed as a result.

### Required Changes — Full Rebuild

**Section 1: The Sleep Thesis**
- Opening narrative: Why sleep is the keystone of this experiment. One paragraph connecting sleep to recovery, HRV, training capacity, mood, and cognitive performance.

**Section 2: Last Night's Sleep** (live data)
- Duration, efficiency, REM%, Deep%, Light%
- Eight Sleep bed temperature settings
- Sleep onset time, wake time
- Whoop sleep score
- Data: `/api/vitals` or `public_stats.json`

**Section 3: 30-Day Sleep Trends** (charts)
- Line chart: sleep duration over 30 days
- Line chart: sleep efficiency over 30 days
- Stacked area: sleep architecture (REM/Deep/Light) over 30 days
- Bar chart: bedtime distribution (histogram)
- Data: new `/api/sleep_environment` endpoint or existing trends in public_stats.json

**Section 4: Eight Sleep × Whoop Cross-Reference** (the discovery)
- What bed temperature settings produce the best sleep architecture
- Show the actual correlation: "Bed temp at -2° = +18 min deep sleep vs. baseline"
- This is the signature discovery — make it visual with before/after comparison

**Section 5: Sleep Protocols**
- Current protocol: bedtime target, pre-sleep routine, temperature settings
- Compliance data: how often hitting targets
- Link to `/protocols/` for full protocol list

**Section 6: Connected Experiments**
- Any sleep-related N=1 experiments, running or completed
- Link to `/experiments/`

### Reading Path CTA
> Another deep-dive: glucose → `/glucose/` → "30 days of CGM data"

---

## 18. GLUCOSE (`/glucose/`)

**Section**: The Science
**Status**: Live — thin on narrative and data
**File**: `site/glucose/index.html`

### CEO Audit Findings
- Same feedback as sleep: "low on narrative, data, and what a user would actually extrapolate"
- "What matters, why, what other data should we be overlaying, what experiments tie to this"
- "Where is our throughline?"

### Design Intent
A CGM deep-dive showing what continuous glucose monitoring reveals about metabolic health. Not just numbers — food-level insights, pattern discovery, and the "so what" of glucose data for a non-diabetic.

### Required Changes — Full Rebuild

**Section 1: Why Track Glucose?**
- Brief narrative on CGM for non-diabetics: metabolic flexibility, energy stability, food response variability
- Frame: "Most people have no idea how their body handles a bowl of rice vs. a steak. I do."

**Section 2: Today's Glucose** (live data)
- Current glucose reading (if CGM active)
- Time-in-range gauge: target >90% of day in 70-140 mg/dL
- Glycemic variability: standard deviation (target <20)
- Data: `/api/glucose` or new endpoint

**Section 3: Best & Worst Foods** (the discovery)
- Ranked list of foods by postprandial glucose response
- Letter grades (A-F) using Levels-style scoring
- "Chicken + rice = A. Pizza = D. But here's the weird one..."
- Data: `/api/glucose_meal_response`

**Section 4: 30-Day Trends**
- Average glucose, time-in-range %, variability trend
- Overlay with nutrition data if available

**Section 5: Connected Experiments & Protocols**
- Any glucose-related experiments
- Current nutrition protocol that affects glucose

### Reading Path CTA
> What I take and why → `/supplements/` → "The full supplement stack with evidence links"

---

## 19. SUPPLEMENTS (`/supplements/`)

**Section**: The Science
**Status**: Live — missing many logged supplements
**File**: `site/supplements/index.html`

### CEO Audit Findings
- "Missing a lot of the supplements I have been logging"
- "Missing the why"
- "Would be better if when you hit a dropdown you had links to scientific journals"
- "Show where I am just testing it out as N+1 vs which are more confidently sourced"

### Design Intent
A complete, transparent supplement protocol. Every supplement with: what, why, dose, evidence level, genome rationale (if applicable), cost, and links to scientific literature. The visitor should be able to assess the evidence quality themselves.

### Required Changes — Full Rebuild

**Data source**: `/api/supplements` endpoint (new — pulls from supplement_log + genome data)

**Per-supplement card** (expandable):
```
[Supplement Name]
├── Dose: [amount] [frequency]
├── Timing: [when taken]
├── Adherence: [X]% this month
├── Evidence Level: [GENOME-JUSTIFIED | WELL-SOURCED | N=1 EXPERIMENT | EXPLORATORY]
│   └── Badge color: green / blue / yellow / grey
├── Genome Rationale: [if applicable] "FADS2 rs1535: poor ALA→EPA conversion"
├── Scientific Summary: [2-3 sentences on what the evidence says]
├── Links: [expandable list of journal article links]
├── Monthly Cost: $[X]
└── Connected Experiment: [link if testing this supplement]
```

**Evidence level badges** (from CEO audit):
- 🟢 **Genome-justified**: SNP data supports specific need
- 🔵 **Well-sourced**: Strong scientific consensus
- 🟡 **N=1 experiment**: Testing personally with data
- ⚪ **Exploratory**: Limited evidence, trying it out

**Total stack cost**: Sum displayed at bottom: "Total monthly supplement cost: $[X]"

**Content filter**: Apply G6 to any supplement that might trigger blocked terms.

### Reading Path CTA
> How I measure against targets → `/benchmarks/` → "Centenarian decathlon benchmarks"

---

## 20. BENCHMARKS (`/benchmarks/`)

**Section**: The Science
**Status**: Live — needs interactivity + personal records
**File**: `site/benchmarks/index.html`

### CEO Audit Findings
- "Wonder if it shows compared to Matt"
- "Wonder if this talks about personal records — run, cycle, lifting, calories, macros"
- "Record of achievements — when did I last beat them?"
- "Label as 'Not possible' for things I can't currently do, but unlock when achieved"
- "Best hike, best bench, fastest mile, longest run, best bench press"

### Design Intent
Two sections: (1) Centenarian decathlon — where Matthew stands vs. Attia's framework for functional fitness at 85, and (2) Personal records — Matthew's all-time bests across categories, with current status.

### Required Changes

**Section 1: Centenarian Decathlon** (existing concept — enhance)
- 4 lift gauges: deadlift, squat, bench, overhead press
- Current % of target for each
- **Interactive**: Visitors enter THEIR numbers and see their own score
- Framework explanation: "Peter Attia's framework: to be functional at 85, you need to be THIS strong at 40"

**Section 2: Personal Records** (NEW)
- Category grid: Running, Cycling, Strength, Nutrition
- Per category: all-time best, date achieved, current capability
- Status badges:
  - 🟢 **Active**: Can currently do this
  - 🟡 **Regressed**: Could do this before, currently can't (e.g., "Fastest mile: 8:32 — Status: NOT POSSIBLE yet")
  - 🔴 **Not Yet**: Never achieved
- When a record is beaten: "🏆 BENCHMARK UNLOCKED — [date]"

**Section 3: Goal Benchmarks**
- Target benchmarks Matthew is working toward
- Progress bars showing how close

### Reading Path CTA
> The full story → `/story/` → "Why all of this started"

---

## 21. PROGRESS (`/progress/`) → MERGE INTO `/live/`

**Section**: N/A — being merged
**Status**: Live — overlaps with live and results

### CEO Audit Findings
- "Very weight focused — what about am I happier? Relationship? Fulfillment?"
- "Not just about weight otherwise I could be on a weight watching forum"
- "How would a user get a sense if they open this page today vs 3 months from now?"

### Required Changes
1. Content from this page merges into the expanded `/live/` dashboard (see brief #3)
2. Redirect `/progress/` → `/live/`
3. The multi-metric, holistic progress view belongs on `/live/` — not a separate page

---

## 22. RESULTS (`/results/`) → MERGE INTO `/live/`

**Section**: N/A — being merged
**Status**: Live — overlaps with progress

### CEO Audit Findings
- "Similar feedback to the progress page"
- "How do we present beyond just weight?"

### Required Changes
1. Merge empirical results content into `/live/`
2. Redirect `/results/` → `/live/`

---

## 23. DISCOVERIES (`/discoveries/`)

**Section**: The Science
**Status**: Live — may be empty
**File**: `site/discoveries/index.html`

### CEO Audit Findings
- "When will this auto-populate?"
- "If empty right now, maybe have placeholder: 'We have X days of data trained, this page unlocks in Y more days'"

### Design Intent
Confirmed findings from the data. This page should feel like a research publication — each discovery with the data behind it.

### Required Changes

1. **Empty state** (critical):
   ```html
   <div class="discovery-empty" style="text-align:center;padding:var(--space-16) var(--page-padding);">
     <div style="font-size:48px;margin-bottom:var(--space-4)">🔬</div>
     <h3 style="font-family:var(--font-display);color:var(--text);">DISCOVERIES LOADING</h3>
     <p style="color:var(--text-muted);max-width:420px;margin:var(--space-4) auto;">
       <span id="disc-days">X</span> days of data collected.
       The platform needs at least 30 days of consistent data to confirm
       statistically significant patterns. Check back soon.
     </p>
     <a href="/experiments/" class="btn btn--ghost">See active experiments →</a>
   </div>
   ```

2. **When discoveries exist**: Show as research cards:
   ```
   [Discovery Title]
   Finding: What the data showed
   Strength: r = [value], p = [value], n = [sample size]
   Confidence: [HIGH | MODERATE | PRELIMINARY]
   Source experiment: [link]
   Impact: How this changed behavior
   ```

3. **Auto-populate**: Wire to `/api/correlations` for confirmed (p < 0.05) correlation pairs. The homepage already shows 3 featured discoveries — this page shows all of them.

### Reading Path CTA
> How the AI brain works → `/intelligence/` → "14+ intelligence features finding patterns in the noise"

---

## 24. ACHIEVEMENTS (`/achievements/`) → MERGE INTO `/character/`

**Section**: N/A — being merged
**Status**: Live — overlaps with character

### CEO Audit Findings
- "Let's think through the category and story to see if we need all of these pages"
- "Inconsistent but overlapping" with progress, results, benchmarks, discoveries

### Required Changes
1. Achievement badges and milestone content merge into `/character/` (see brief #9, Section 4)
2. Redirect `/achievements/` → `/character/`

---

## 25. HABITS (`/habits/`)

**Section**: The Data
**Status**: New page needed (data ready via MCP tools)
**File**: `site/habits/index.html` (create new)

### CEO Audit Findings
- "I do like the heatmap and mixing up visuals"
- "This is really a huge part of my platform in data and so I would like this blown up much more, even for my own use"

### Design Intent
The habit observatory. This is where the daily inputs are visible — the 65 habits that feed the character score. The GitHub-contribution-style heatmap is the signature visual. This page should be as useful to Matthew as it is to visitors.

### Required Changes — New Page Build

**Data**: `/api/habits` endpoint (new) or `/api/habit_streaks` (existing)

**Section 1: Hero**
- "65 HABITS. DAILY." with current T0 streak and overall adherence %

**Section 2: GitHub-style Heatmap**
- 52 weeks × 7 days. Color intensity = number of habits completed that day.
- Color scale: empty (grey) → light green → full green
- Hover: show date + "14/18 habits completed"
- This is the most shareable visual on the entire site.

**Section 3: Tier Breakdown**
- Tier 0 (Non-negotiable): list habits, current streak, adherence %
- Tier 1 (High priority): same
- Tier 2 (Important): same
- Tier 3 (Nice to have): same
- Each tier visually distinct (border color or background shade)

**Section 4: Streak Records**
- Current active streak (per tier and overall)
- Longest streak ever (with date range)
- "What is a streak?": Definition — consecutive days where all Tier 0 habits completed

**Section 5: Group Adherence**
- Bar chart: 9 habit groups (Data, Discipline, Growth, Hygiene, Nutrition, Performance, Recovery, Supplements, Wellbeing)
- Each bar showing % adherence this month

**Content filter**: MUST apply G6 to exclude blocked habits/vices from all displays.

### Reading Path CTA
> The protocols behind the habits → `/protocols/` → "What I do daily and why"

---

## 26. ABOUT (`/about/`)

**Section**: The Story
**Status**: Live — needs content refocus
**File**: `site/about/index.html`

### CEO Audit Findings
- "Remove the weight reference as a widget — think the throughline of each page"
- "Maybe this is more about me as a human and less about data"
- "It starts talking about the build — that's on the other page about tooling/architecture"

### Design Intent
This is the "who is Matthew" page. Human, not data. Professional context, personal motivation, what drives the experiment beyond the numbers. No data widgets, no architecture talk — that's what `/platform/` and `/live/` are for.

### Required Changes

1. **Remove**: Weight widget, any data visualization, any architecture/build content
2. **Keep**: Professional bio (Senior Director at SaaS company in Seattle), personal motivation, the "why" at a human level
3. **Add**:
   - A photo of Matthew (when available)
   - Professional context: "My day job is leading teams at a SaaS company. This experiment is also a learning lab for how we adopt AI tools enterprise-wide."
   - Talk topics: If Matthew wants to speak at conferences, list 3-4 talk themes
   - Media kit: Brief bio for podcast hosts / journalists
   - Contact: Correct email address (same fix as privacy page)

4. **Tone**: First person, warm, vulnerable. This is the page that makes someone think "I like this person" before they dive into data.

### Reading Path CTA
> Read the full story → `/story/` → "How this experiment started"

---

## 27. INTELLIGENCE (`/intelligence/`)

**Section**: The Build
**Status**: Live — may need dynamic content
**File**: `site/intelligence/index.html`

### CEO Audit Findings
- "How dynamic is this — as we add intelligence features, is it getting updated?"

### Design Intent
Showcase of the AI brain. Each intelligence feature should be explained with a real example of it working. Not just a list — proof that the AI catches things a human would miss.

### Required Changes

1. **Dynamic content**: Wire the intelligence feature list to a data source. Either:
   - `/api/intelligence` endpoint (new) returning feature list + recent detections
   - Or `public_stats.json → intelligence` section with feature count + last detection timestamps

2. **Per-feature card**:
   ```
   [IC Feature Name]
   What it does: [1-sentence description]
   Real example: [A specific instance where this feature detected something]
   Last triggered: [date] (or "Monitoring — no detection needed")
   ```

3. **Feature count**: Dynamic from public_stats.json, not hardcoded.

4. **Visual**: Consider a system diagram showing how IC features connect to data sources and to each other.

### Reading Path CTA
> Ask the data yourself → `/ask/` → "What questions do you have?"

---

## 28. ACCOUNTABILITY (`/accountability/`)

**Section**: The Data
**Status**: Live — purpose unclear
**File**: `site/accountability/index.html`

### CEO Audit Findings
- "I don't know what this page is meant to be, and who it is intended for"
- "Maybe it's for the reader to keep me accountable?"
- "The last 2 weeks I've been logging sick days — this page could show I have flatlined, show the gamer icon sad, it could be more fun and interactive"
- "AI can't solve everything, maybe this is how this page materializes"

### Design Intent
This is the "how is Matt doing TODAY" page. An honest, real-time snapshot. When Matthew is crushing it — show it. When he's fallen off the wagon — show that too. This page is the emotional thermometer of the experiment. It should make the experiment feel alive and honest.

### Required Changes — Full Rethink

**Section 1: Current State Banner**
- Dynamic mood/state indicator based on recent data:
  - 🟢 **On track**: Active streaks, logging daily, metrics improving
  - 🟡 **Slipping**: Missed days, declining metrics, breaking streaks
  - 🔴 **Off the wagon**: No data for X days, streaks broken, sick days logged
- Character avatar reflecting current state (ties to `/character/` avatar)

**Section 2: The Honesty Dashboard**
- Days since last habit log
- Days since last weigh-in
- Current T0 streak (or "Streak broken X days ago")
- Active sick days (if any)
- Character score trend: up/flat/down arrow with last 7 days

**Section 3: The Accountability Contract**
- Matthew's stated commitments (from protocols)
- Live compliance data next to each:
  - "Hit protein target: 0 of last 14 days" (honest when failing)
  - "Log weight daily: 3 of last 14 days"
  - "Zone 2 training: 0 min of 150 min target this week"

**Section 4: Reader Interaction** (future — placeholder for now)
- "Think Matt needs a nudge? Send encouragement." → simple feedback form or link to `/ask/` with a prompt
- This could evolve into a community accountability feature

**Data needs**: Aggregate from habits, vitals, character score, sick days — mostly available in `public_stats.json`

### Reading Path CTA
> The score behind the accountability → `/character/` → "How the system quantifies all of this"

---

## PAGES NOT IN AUDIT BUT IN NAV

### `/explorer/` — Correlation Explorer
No audit feedback. Keep as-is. It's functional and unique.

### `/biology/` — Genome Risk Dashboard
No audit feedback. Currently noindex. Keep as-is until Matthew decides to make it public.

### `/data/` — Open Data Page
Consider moving under `/platform/` as a sub-section. Low priority.

---

## DEPLOY CHECKLIST (Per Page Rebuild)

After rebuilding any page:

1. ✅ Verify all numbers are dynamic (G1)
2. ✅ Verify nav is current (G2) — run nav patch if needed
3. ✅ Add reading path CTA (G3)
4. ✅ Add section eyebrow (G4)
5. ✅ Add N=1 disclaimer if Science section (G5)
6. ✅ Apply content filter if showing habits/vices (G6)
7. ✅ All styling uses tokens.css (G7)
8. ✅ Test mobile breakpoints (G8)
9. ✅ Data fetch pattern correct (G9)
10. ✅ Scroll reveal on sections (G10)
11. ✅ S3 sync: `aws s3 sync site/ s3://matthew-life-platform/site/ --delete`
12. ✅ CloudFront invalidate: `aws cloudfront create-invalidation --distribution-id E3S424OXQZ8NBE --paths "/*"`
13. ✅ Update sitemap.xml if page added/removed/renamed
14. ✅ Git tag: `git tag site-vX.Y.Z`

---

## EXECUTION ORDER

Recommended sequence for Claude Code sessions:

**Sprint 9 (Phase 0 — Fix broken things)**:
1. Fix public_stats.json data pipeline (weight null, streak, journey %)
2. Homepage data fixes (ticker, hero, sparklines, comparison card)
3. Fix subscribe Lambda
4. Fix /ask/ back-nav + remove "subscribe for more"
5. Fix privacy email
6. Verify bottom nav works
7. Verify all journal posts have current nav

**Sprint 10 (Phase 1 — IA restructure)**:
8. Rename /journal/ → /chronicle/ with redirects
9. Merge /progress/ + /results/ → redirect to /live/
10. Merge /achievements/ → redirect to /character/
11. Remove /start/ → redirect to /
12. Add reading path CTAs to all existing pages
13. Update sitemap.xml

**Sprint 11-13 (Phase 2 — Page rebuilds, one per session)**:
14. `/live/` — full dashboard rebuild
15. `/habits/` — new page build
16. `/character/` — add intro, avatar, badges, fix scoring
17. `/accountability/` — full rethink
18. `/platform/` — strip non-tech, add architecture diagram
19. `/supplements/` — full rebuild with evidence levels
20. `/sleep/` — full rebuild with narrative
21. `/glucose/` — full rebuild with meal grades
22. `/benchmarks/` — add interactivity + personal records
23. `/board/` — persona replacements + board structure
24. `/about/` — strip data, add human content
25. `/intelligence/` — wire to dynamic data
26. `/discoveries/` — add empty state + auto-populate

**Sprint 14 (Phase 3 — Chronicle engine)**:
27. Fix Wednesday auto-publish Lambda
28. Implement preview/approval flow
29. Write restart interview entry

---

*This document is the single source of truth for page-level design decisions. Read the global rules once, then reference the specific page brief for each rebuild session. Every page should pass the Throughline Test: Can a visitor answer "Where am I in the story?" and "How does this connect to the bigger picture?"*
