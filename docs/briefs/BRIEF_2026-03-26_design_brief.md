# Product Board Design Brief: April 1st Launch Readiness
## averagejoematt.com — Visual & Experience Overhaul Proposal

> **Date**: March 26, 2026
> **Prepared by**: Product Board of Directors
> **External consultations**: Product design (Figma/Notion design systems), product marketing (DTC health brands), storytelling (documentary/longform producers), visual artists (data visualization, editorial illustration), game designers (progression systems, retention loops)
> **Deadline**: April 1, 2026 (Day 1 launch)

---

## Executive Summary

The Product Board spent the past week auditing every page, interviewing external specialists, and stress-testing the site with fresh eyes. The verdict: **the underlying architecture is exceptional, but the visual execution is stuck between two identities** — a developer's terminal aesthetic and a human transformation story. The biopunk data terminal aesthetic was the right instinct for an MVP. For a public launch with narrative ambitions, it needs to evolve.

This brief proposes a unified design direction, site-wide styling upgrades, navigation restructure, and targeted page-by-page enhancements — all scoped to what can ship by April 1st with a Phase 2 polish sprint following.

**The one-line brief**: *Make it feel like a Bloomberg Terminal had a baby with a Patagonia documentary.*

---

## Part 1: The Diagnosis (What We Found)

### What's Working
- **The token system is gold.** CSS custom properties, spacing scale, z-index — this is more disciplined than most startups. Any visual changes can cascade from `tokens.css` without touching individual pages.
- **Dark mode is genuinely good.** The green-on-black signal aesthetic is distinctive and memorable. People remember this site.
- **Self-hosted fonts + no Google dependency** — privacy-forward, performance-forward. Keep this.
- **The observatory pattern** (shared CSS for data pages) was smart extraction. It should become the foundation, not just a utility.
- **Mobile nav + bottom nav** — the hamburger overlay, grouped footer, and bottom tab bar are solid bones.

### What's Not Working

**1. Typography feels "coded" not "crafted"**
- `Space Mono` at `14px` base with `1.75` line-height is legible but fatiguing for long-form reading. Every page reads like a terminal session, including the story page that should feel intimate.
- `Bebas Neue` for display headings is punchy but one-note. There's no typographic range — the site can't whisper. Every heading screams.
- No `Inter` usage despite it being declared in tokens. The `--font-sans` variable exists but almost nothing uses it.
- Body text letter-spacing is too uniform. Mono fonts at small sizes with tight tracking create a wall of text.

**2. Color palette is too narrow**
- Two colors: signal green and journal amber. Everything else is grayscale. This works for a dashboard; it flattens a documentary.
- Light mode green (`#006c4a`) passes WCAG AA but feels clinical. The warm undertone of the dark mode gets lost.
- No secondary accent for call-to-action differentiation. The subscribe button, the "live" pulse, the active challenge — all the same green. Nothing stands out because everything stands out.
- Status colors (yellow, red) exist in tokens but are barely used. The emotional range of data — a bad night's sleep SHOULD feel different from a PR at the gym — gets no visual support.

**3. Light mode is an afterthought**
- Surfaces are washed out. `#f4f7f5` background with `#eaf0ec` surface cards = almost no contrast between layers.
- The green accent in light mode (`#006c4a`) is accessible but dull. It doesn't carry the energy of the dark mode `#00e5a0`.
- Border visibility improved (the `0.22` opacity fix was good) but cards still feel ghostly against the background.
- No warm accent in light mode — everything skews cool/clinical.

**4. No visual hierarchy between page types**
- The homepage, a deep-dive data page, and the story page all use the same visual density. A first-time visitor hitting `/sleep/` gets the same layout rhythm as someone returning to check their glucose. There's no "lean back" vs "lean forward" mode.
- Data pages, narrative pages, and showcase pages should FEEL different before you read a word.

**5. Interactivity is shallow**
- Hover states exist (color transitions) but there are no micro-interactions that reward exploration.
- No scroll-triggered animations beyond the basic `reveal` class (opacity + translateY). Pages don't breathe.
- Charts are static images or API-rendered. No interactive elements that make someone go "wait, I can DO something here?"
- The experiment counter on the homepage is the best interactive moment on the site — and it's just a number.

**6. Navigation doesn't tell a story**
- Top nav has dropdowns with flat link lists. No visual cues about where you are in the site's narrative arc.
- The footer is comprehensive but dense. Six columns of monospace links in 10px type.
- No breadcrumbs. No "you are here" beyond an `.active` class on a nav link.
- The reading path component (`GAM-02`) exists in CSS but isn't used consistently. This is the most important retention mechanism and it's dormant.

---

## Part 2: The Design Direction

### Visual Identity: "Signal Doctrine"

**Tagline**: *Clean data. Human story. Unflinching honesty.*

The site should feel like a field dispatch from someone who takes their own transformation as seriously as a research lab takes clinical trials — but who also bleeds, fails, and writes about it. The aesthetic is precision crossed with vulnerability.

**Reference points** (for mood, not imitation):
- **Bloomberg Terminal**: Information density done right. Green-on-black. Trust through data.
- **Patagonia's "The Fisherman's Son"**: Documentary storytelling where the subject IS the product.
- **Strava's Year in Sport**: Data made emotional. Your stats, but they make you FEEL something.
- **The Pudding**: Data journalism that uses interactivity as a storytelling device.
- **Figma's design system docs**: Clean, scannable, but never boring. Great use of whitespace-to-density ratio.

### The Two Modes

Every page on the site falls into one of two modes. The mode determines typography, density, and pacing.

| Mode | Purpose | Typography | Density | Example pages |
|------|---------|------------|---------|---------------|
| **SIGNAL** | Data, dashboards, real-time | Mono-forward, tight, scannable | High — cards, grids, numbers | `/live/`, `/character/`, `/habits/`, `/glucose/`, `/sleep/`, `/challenges/`, `/experiments/` |
| **STORY** | Narrative, reflection, identity | Serif-forward, generous, breathable | Low — long lines, whitespace, pull quotes | `/story/`, `/about/`, `/chronicle/`, `/discoveries/`, homepage hero |

Pages can MIX modes (the homepage does: story hero → signal data section). But within a section, commit to one.

---

## Part 3: Site-Wide Styling Proposals

### 3A. Typography Overhaul

**Current stack**: Bebas Neue (display) / Space Mono (body/UI) / Lora (serif, underused) / Inter (sans, unused)

**Proposed stack**:

| Role | Current | Proposed | Rationale |
|------|---------|----------|-----------|
| Display/Hero | Bebas Neue | **Bebas Neue** (keep) | Distinctive, recognizable, punchy. It's part of the brand now. |
| UI/Data labels | Space Mono 12px | **Space Mono 12px** (keep) | Perfect for data labels, ticker, nav. This IS the signal aesthetic. |
| Body (Signal pages) | Space Mono 14px | **Inter 15px** | Mono body text is fatiguing. Inter at 15px is clean, scannable, and already in the stack. Switch `--font-sans` from fallback to primary body font on data pages. |
| Body (Story pages) | Space Mono 14px | **Lora 17px** | Lora is beautiful and already self-hosted. Story pages deserve a serif with proper line-height (1.8). Pull quotes in Lora italic are gorgeous. |
| Code/Values | Space Mono | **Space Mono** (keep) | Numbers, percentages, and technical values stay mono. It's the right tool. |
| Section labels | Space Mono 11px uppercase | **Space Mono 10px, 0.2em tracking** (keep, tighten) | The eyebrow pattern is solid. Slight tightening at 10px gives more polish. |

**Implementation**: Add two new body classes to `base.css`:

```css
.body-signal { font-family: var(--font-sans); font-size: 15px; line-height: 1.65; }
.body-story  { font-family: var(--font-serif); font-size: 17px; line-height: 1.85; }
```

Each page's `<body>` gets the appropriate class. Data values and labels keep `font-family: var(--font-mono)` via component classes.

**New token additions**:
```css
--text-body-signal: 15px;
--text-body-story:  17px;
--lh-signal:        1.65;
--lh-story:         1.85;
```

### 3B. Color System Expansion

**Keep the core**: Signal green (`#00e5a0`) and journal amber (`#c8843a`) remain the primary and secondary accents. They're recognizable.

**Add a tertiary accent for CTAs**:
```css
/* CTA accent — warm coral for subscribe, follow, try-this buttons */
--c-coral-500:      #ff6b6b;
--c-coral-400:      #ee5a5a;
--c-coral-300:      #cc4444;
--c-coral-100:      rgba(255, 107, 107, 0.12);
--c-coral-050:      rgba(255, 107, 107, 0.06);
```

**Why coral?** It's warm, urgent, and stands out against both green and amber. The "Subscribe" button should NOT be the same green as "Day 57" in the nav. Coral says "do this now" — green says "this is data."

**Add pillar-specific accent colors** (for Character Score pages and cross-references):
```css
/* Seven pillar colors — used in character, challenges, habits */
--pillar-movement:   #3ecf8e;  /* green — already close to accent */
--pillar-nutrition:  #f59e0b;  /* amber */
--pillar-sleep:      #818cf8;  /* indigo */
--pillar-mind:       #a78bfa;  /* violet */
--pillar-body:       #ef4444;  /* crimson */
--pillar-social:     #06b6d4;  /* cyan */
--pillar-discipline: #f97316;  /* orange */
```

These already partially exist in `observatory.css` (`--obs-accent`). Promote them to first-class tokens so every page that references a pillar uses the same color.

**Light mode warm-up**:
```css
:root[data-theme="light"] {
  --bg:             #fafaf8;       /* warm off-white (was #f4f7f5 — too green) */
  --surface:        #f0eeeb;       /* warm card surface */
  --surface-raised: #e8e5e0;       /* warm raised surface */
  --accent:         #008f5f;       /* slightly brighter than current #006c4a */
}
```

The shift from cool-green-undertone to warm-neutral makes light mode feel lived-in rather than clinical. Cards become visible without increasing border opacity further.

### 3C. Dark Mode / Light Mode Polish

**Dark mode** (keep 90% as-is, minor refinements):
- Surface layer contrast: increase `--c-surface-1` from `#0e1510` to `#0f1612` — 2% brighter for better card separation.
- Add subtle noise texture overlay to `<body>` background for depth:
  ```css
  body::after {
    content: '';
    position: fixed;
    inset: 0;
    background: url('/assets/images/noise-dark.png');
    opacity: 0.015;
    pointer-events: none;
    z-index: 9999;
  }
  ```
- Glow on accent elements: Add `text-shadow: 0 0 20px rgba(0, 229, 160, 0.15)` to `.vital__value` and hero counters. Subtle CRT phosphor effect.

**Light mode** (more substantial changes):
- Warm the background palette (see 3B above).
- Add paper-like texture (very subtle):
  ```css
  :root[data-theme="light"] body::after {
    background: url('/assets/images/noise-light.png');
    opacity: 0.02;
  }
  ```
- Cards get a soft shadow instead of relying only on borders:
  ```css
  :root[data-theme="light"] .vital,
  :root[data-theme="light"] .obs-stat {
    box-shadow: 0 1px 3px rgba(0, 0, 0, 0.04), 0 1px 2px rgba(0, 0, 0, 0.02);
    border-color: rgba(0, 0, 0, 0.06);
  }
  ```

### 3D. Motion & Micro-Interactions

**Current state**: `fade-up` on page load, `.reveal` on scroll. That's it.

**Proposed additions**:

**1. Number count-up animation** (for vitals and stats):
```css
@keyframes countUp {
  from { opacity: 0; transform: translateY(8px); }
  to   { opacity: 1; transform: translateY(0); }
}
```
Combine with JS `IntersectionObserver` — when a `.vital__value` scrolls into view, animate from 0 to actual value over 800ms with easing. This makes data feel ALIVE.

**2. Card hover lift** (for tiles, vitals, source pills):
```css
.vital:hover,
.tile:hover {
  transform: translateY(-2px);
  box-shadow: 0 4px 12px rgba(0, 229, 160, 0.08);
  border-color: var(--accent-dim);
  transition: all var(--dur-mid) var(--ease-out);
}
```

**3. Progress bar fill animation** (for signal bars, habit streaks):
```css
.signal-bar__fill {
  transform: scaleX(0);
  transition: transform 1.2s var(--ease-out);
}
.signal-bar__fill.is-visible {
  transform: scaleX(var(--fill-pct));
}
```

**4. Parallax hero scroll** (homepage only):
The weight counter section shifts at 0.5x scroll speed while background text shifts at 0.3x. Creates depth without performance cost (use `transform: translate3d` for GPU acceleration).

**5. Page transition feeling**:
Add a 200ms fade between page loads using a `<div class="page-curtain">` that briefly overlays green→transparent. This makes the site feel like an app, not a collection of HTML files.

**6. Staggered card reveals**:
When a grid of cards scrolls into view, stagger their reveal by 60ms per card:
```css
.reveal-grid > *:nth-child(1) { transition-delay: 0.00s; }
.reveal-grid > *:nth-child(2) { transition-delay: 0.06s; }
.reveal-grid > *:nth-child(3) { transition-delay: 0.12s; }
/* ... etc */
```

### 3E. Visual Elements & Graphics

**1. Data visualization upgrade**:
- Replace static metric displays with sparkline mini-charts (7-day trend) using inline SVG. A weight card that shows "302" is informative; one that shows "302" with a tiny downward-trending line beneath it is compelling.
- Sparkline implementation: `<svg class="sparkline" viewBox="0 0 80 24">` with a polyline. ~100 bytes per sparkline. Can be inlined in HTML.

**2. Avatar / Identity visual**:
- The character page needs a visual avatar — not a photo, but a generated silhouette or abstract representation that evolves with the character score. Think: a geometric figure whose complexity/brightness increases as the score rises.
- Simpler option for launch: a circular ring chart showing the 7-pillar breakdown, with each segment in its pillar color. This IS the avatar.

**3. Iconography**:
- Current state: emoji everywhere. Emoji is great for personality but renders differently per OS/browser.
- Proposal: Use SVG icons from Lucide or Phosphor for structural UI elements (nav, cards, badges). Keep emoji for personality moments (challenge tiles, achievement names, section kickers). This gives a professional base with a human overlay.

**4. Hero section background treatment**:
- The radial gradient glow (`rgba(0,229,160,0.06)`) is good but generic.
- Replace with a subtle animated mesh of connected dots (particle field) — very low density, very slow movement. This visualizes "data in motion" without being distracting. Implementation: ~40 lines of Canvas JS, positioned absolutely behind the hero content.

**5. Section dividers**:
- Replace the uniform `border-bottom: 1px solid var(--border)` between all sections with contextual dividers:
  - Between story sections: a subtle `···` centered dot divider (editorial style)
  - Between data sections: the current line (keep)
  - Between major site sections: a gradient fade from accent to transparent

**6. Photography / Imagery** (for launch):
- The site has ZERO photographs. This is a story about a real person. At minimum, the `/story/` and `/about/` pages need a photo or illustration.
- If Matthew doesn't want a photo: commission a simple line-art portrait or use a stylized silhouette. The absence of any human image makes the site feel like it's about a system, not a person.

---

## Part 4: Navigation Restructure

### Current Navigation

**Desktop**: AVERAGEJOEMATT [dropdown: Explore] [dropdown: Data] [dropdown: Build] [LIVE] [theme toggle]
**Mobile**: Hamburger → overlay with grouped sections
**Bottom nav**: Home / Live / Character / Chronicle / More

### Proposed Navigation

**Desktop top bar** (simplified, story-first):

```
[AJM logo] --- THE STORY  THE DATA  THE SCIENCE  THE BUILD  FOLLOW --- [LIVE] [theme]
```

Five clear sections matching the IA. No dropdowns on the primary level — each link goes to a section landing page that has its own sub-navigation. This reduces cognitive load from "which dropdown has what I want?" to "which section am I in?"

**Section landing pages** (new pattern):
When you click "THE DATA", you land on a page that shows:
- A 1-line section description
- Cards for each sub-page with a 1-line summary and a sparkline/preview
- This IS the sub-navigation — visual, not textual

**Breadcrumb trail** (add to all sub-pages):
```
THE DATA → Sleep Observatory → Architecture
```
Rendered as:
```html
<div class="breadcrumb">
  <a href="/live/" class="breadcrumb__section">The Data</a>
  <span class="breadcrumb__sep">→</span>
  <span class="breadcrumb__current">Sleep Observatory</span>
</div>
```

**Mobile bottom nav** (update):
```
Home | Story | Data | Science | Build
```
Replace "Chronicle" with "Story" (chronicle is inside story). Keep it to 5 tabs. "LIVE" becomes a floating badge on the Data tab (a pulsing green dot).

**Reading path component** (activate everywhere):
At the bottom of every page, before the footer:
```
← Previous: The Story          Next: Habit Protocols →
      /story/                      /protocols/
```
This creates a linear reading flow through the entire site. A new visitor can read the site like a book. The sequence should follow the narrative arc: Story → About → Live → Character → Habits → Protocols → Experiments → Discoveries → Sleep → Glucose → Platform → Subscribe.

### Sticky "Where Am I?" indicator
On scroll past the hero, show a thin bar below the nav:
```
━━━━━━━━━━━━━━━━━━●━━━━━━━━━━━━━
THE STORY    THE DATA    THE SCIENCE    THE BUILD
```
A dot shows which section you're in. Clicking a section scrolls/navigates.

---

## Part 5: Page-Specific Upgrades

### Priority Tier 1: Ship by April 1st

#### Homepage (`/`)
| Issue | Fix | Board owner |
|-------|-----|-------------|
| Hero weight counter shows null | Wire to live API data OR hardcode "302" as starting weight with "Day 1: April 1" | James (CTO) |
| No human element | Add a single tagline below the weight counter: *"One person. Every number. No hiding."* in Lora italic | Ava (Content) |
| Ticker bar data is stale | Refresh ticker with real data or make it explicitly "countdown" themed for launch | James |
| Sources grid is static | Add subtle animation — each source pill fades in staggered when scrolled into view | Tyrell (Design) |
| "Read the Story" CTA is a ghost button | Make it coral (CTA accent), make it bigger. This is the #1 action for a new visitor. | Sofia (CMO) |
| No live challenge visibility | The challenge bar at the bottom should show the active challenge with a progress indicator | Raj (Product) |

#### Story page (`/story/`)
| Issue | Fix |
|-------|-----|
| Reads like a data page | Switch to `body-story` class. Lora 17px. Generous line-height (1.85). Max-width 680px. |
| No pull quotes | Add `<blockquote class="pull-quote">` styling — Lora italic, oversized, accent left border |
| No section breaks | Add `···` dot dividers between narrative sections |
| Needs a photo or illustration | At minimum: a stylized silhouette or line-art illustration at the top of the page |
| No reading time estimate | Add "8 min read" below the title in mono small caps |

#### Character page (`/character/`)
| Issue | Fix |
|-------|-----|
| Score display is just a number | Replace with a radial ring chart — 7 segments, pillar colors, animated fill on load |
| No visual avatar | Add the 7-pillar ring as the avatar. It IS the identity. Centered, large, animated. |
| Pillar cards lack personality | Add pillar-specific accent colors from tokens. Each card's left border = pillar color. |
| Achievements buried | Move badge gallery into a horizontal scroll row below the score — "Recent Achievements" |

#### Live page (`/live/`)
| Issue | Fix |
|-------|-----|
| Static numbers | Add sparkline mini-charts (7-day) below each vital value |
| No "as of" freshness indicator | Add "Updated 2h ago" timestamp below each metric |
| Feels like a dashboard, not a story | Add a 1-line AI-generated narrative summary at top: "Today: Recovery is strong after yesterday's Zone 2 session. Sleep was 7.2h. Weight steady at 298." |

#### Subscribe page (`/subscribe/`)
| Issue | Fix |
|-------|-----|
| CTA button is green (same as everything) | Make it coral. Subscribe is the ONE action that matters for growth. |
| No social proof | Add "Join X subscribers following this experiment" (even if X = 12, honesty is the brand) |
| No preview of what you get | Show a mini-preview of the weekly email format. One screenshot or HTML mockup. |

### Priority Tier 2: Ship by April 7th

#### Sleep Observatory (`/sleep/`)
- Add the two-mode treatment: a narrative intro section (story mode: "Here's what I've learned about my sleep") followed by the signal dashboard
- Interactive sleep architecture chart — stacked bar showing each night's sleep stages with hover detail
- Add `--obs-accent: #818cf8` (indigo) as the page accent — sleep should feel nocturnal

#### Glucose Observatory (`/glucose/`)
- Same two-mode treatment: narrative intro + signal dashboard
- Interactive meal response chart — before/after glucose curve with meal annotation
- Add meal logging CTA: "What did you eat? See how it affected your glucose."

#### Challenges / Arena (`/challenges/`)
- Good as shipped (Arena v2 is strong)
- Add: animated category filter transition (tiles should slide/fade when filtering, not pop)
- Add: confetti micro-animation when a challenge is marked complete (game designer recommendation)

#### Experiments / Lab (`/experiments/`)
- Good as shipped (Lab v2 is strong)
- Add: timeline view option (in addition to tile grid) — experiments plotted on a horizontal timeline showing active periods
- Add: "Matthew's pick" badge for the next experiment he's planning to run

### Priority Tier 3: Post-launch polish (April 14+)

- **Data Explorer** (`/explorer/`): Interactive multi-metric chart builder. Visitor picks 2-3 metrics and sees them overlaid. This is the "wow" page.
- **Weekly Snapshot** (`/week/`): Auto-generated visual summary of the past 7 days. Sharable card format.
- **Milestones Gallery** (`/achievements/`): Visual timeline of achievements with dates and context.
- **Dark/light mode transition**: Animate the theme switch instead of instant-swapping (smooth color crossfade over 300ms).

---

## Part 6: CSS Implementation Checklist

All changes should be made through the token system. Here's the exact file hit list:

### `tokens.css` changes:
- [ ] Add `--c-coral-*` CTA accent ramp (500, 400, 300, 100, 050)
- [ ] Add 7 `--pillar-*` color tokens
- [ ] Add `--text-body-signal` and `--text-body-story` size tokens
- [ ] Add `--lh-signal` and `--lh-story` line-height tokens
- [ ] Warm up light mode `--bg` from `#f4f7f5` to `#fafaf8`
- [ ] Warm up light mode surfaces
- [ ] Bump light mode `--accent` from `#006c4a` to `#008f5f`

### `base.css` changes:
- [ ] Add `.body-signal` and `.body-story` classes
- [ ] Add `.pull-quote` blockquote styles
- [ ] Add `.breadcrumb` component
- [ ] Add `.sparkline` SVG styles
- [ ] Add card hover lift (`.vital:hover`, `.tile:hover`)
- [ ] Add number count-up animation keyframes
- [ ] Add `.reveal-grid` staggered animation
- [ ] Add section divider variants (`.divider-dots`, `.divider-fade`)
- [ ] Update `.reading-path` component (currently unused)
- [ ] Add coral CTA button variant (`.btn--cta`)
- [ ] Add text glow in dark mode for vital values

### `responsive.css` changes:
- [ ] Update bottom nav labels (Story/Data/Science/Build)
- [ ] Add breadcrumb responsive styles (collapse on mobile)
- [ ] Test light mode warm palette on all breakpoints

### New files:
- [ ] `/assets/images/noise-dark.png` — 200x200px tileable noise texture
- [ ] `/assets/images/noise-light.png` — 200x200px tileable noise texture (lighter)
- [ ] `/assets/js/animations.js` — Shared animation utilities (count-up, sparklines, staggered reveals)

---

## Part 7: Board Member Statements

### Mara Chen (UX Lead)
> "The biggest win available right now is the reading path. Every page should answer two questions: 'What am I looking at?' and 'Where do I go next?' We have the CSS component built — we just need to wire it into every page. A visitor who reads three pages instead of one is 5x more likely to subscribe. The breadcrumb + reading path combination turns a bounce into a journey."

### James Okafor (CTO)
> "Every proposal here works within the existing architecture. The token system means color and typography changes cascade automatically. The sparklines are inline SVG — no new libraries, no build step, no Lambda changes. The particle hero is the only thing that needs JS beyond what we have. I'd prioritize the token changes (30 minutes), then body class rollout (1 hour per page), then motion (iterative). We can ship Tier 1 in two focused sessions."

### Sofia Herrera (CMO)
> "The coral CTA button is the single highest-ROI change on this list. Right now, every call to action is the same green as the data. The subscribe button MUST stand out. The 'Join X subscribers' social proof is table stakes for any DTC launch. And we need one shareable visual per week — the Weekly Snapshot page gives us that. This is how we get organic social distribution."

### Dr. Lena Johansson (Longevity Science)
> "The two-mode approach (signal vs story) is exactly right for credibility. The narrative intros on data pages give visitors context — why this metric matters, what the research says, what Matthew is testing — before they see the numbers. This frames the data as science, not vanity metrics. The pillar color system also helps: when everything is green, nothing has semantic meaning. When sleep is indigo and movement is emerald, the colors themselves teach the framework."

### Raj Mehta (Product Strategy)
> "Reading path is the retention mechanic. The live challenge ticker bar is the re-engagement mechanic. The subscribe CTA redesign is the acquisition mechanic. Everything else is polish. If I had to ship three things and nothing else, it's those three. The particle hero, the noise textures, the parallax — nice to have. Reading path, challenge bar, coral subscribe button — must have."

### Tyrell Washington (Designer / Brand)
> "The noise texture is 15 minutes of work and transforms the feel. Right now the backgrounds are perfectly flat digital surfaces. A 1.5% opacity noise layer adds analog texture — it's the difference between a screen and a page. The card hover lift is another easy win. And the staggered reveals on card grids make the site feel alive. These are tiny CSS additions with outsized impact."

### Jordan Kim (Growth & Distribution)
> "Every page needs exactly one thing that makes someone want to screenshot it and send to a friend. The character score ring chart — that's screenshotable. The weight counter on the homepage — screenshotable. The challenge tile wall — screenshotable. Pages that DON'T have a screenshot moment: story (needs a pull quote graphic), sleep (needs a night-over-night comparison visual), subscribe (needs a preview card). Give me one screenshot moment per page and I can drive traffic."

### Ava Moreau (Content Strategy)
> "The typography change is the biggest storytelling unlock. When `/story/` switches from Space Mono 14px to Lora 17px, it immediately signals 'this is a different kind of page — slow down, read.' That signal costs zero engineering effort and completely changes how someone experiences the content. Every chronicle post, every discovery writeup, every narrative section benefits. The font IS the storytelling tool."

---

## Part 8: Priority Matrix

| Change | Impact | Effort | Ship by |
|--------|--------|--------|---------|
| `tokens.css` color/typography additions | HIGH | Low (30 min) | April 1 |
| `.body-signal` / `.body-story` classes | HIGH | Low (20 min) | April 1 |
| Coral CTA button variant | HIGH | Low (15 min) | April 1 |
| Reading path on all pages | HIGH | Med (2 hours) | April 1 |
| Breadcrumb component | Med | Low (30 min) | April 1 |
| Card hover lift + reveals | Med | Low (20 min) | April 1 |
| Light mode warm palette | Med | Low (15 min) | April 1 |
| Story page typography reformat | HIGH | Low (30 min) | April 1 |
| Homepage hero data fix | HIGH | Med (1 hour) | April 1 |
| Subscribe page coral + social proof | HIGH | Low (30 min) | April 1 |
| Character score ring chart | HIGH | Med (2 hours) | April 1 |
| Sparkline mini-charts | Med | Med (2 hours) | April 7 |
| Noise texture backgrounds | Med | Low (15 min) | April 1 |
| Number count-up animations | Med | Med (1 hour) | April 7 |
| Staggered grid reveals | Med | Low (20 min) | April 1 |
| Nav restructure (5 sections) | HIGH | High (4 hours) | April 7 |
| Section landing pages | Med | High (6 hours) | April 14 |
| Particle hero background | Low | Med (1 hour) | April 14 |
| Pillar accent colors per page | Med | Med (1 hour) | April 7 |
| Dark mode text glow | Low | Low (10 min) | April 1 |

---

## Appendix A: Font Loading Strategy

Already self-hosting. No changes to the loading strategy. Add weight variants if needed:

- `Lora 400` — have
- `Lora 600` — have
- `Lora 400i` — have
- `Lora 600i` — have
- `Inter 400` — need to add (`inter-400.woff2`)
- `Inter 500` — need to add (`inter-500.woff2`)
- `Inter 600` — need to add (`inter-600.woff2`)

Download from Google Fonts, upload via `deploy/download_and_upload_fonts.sh` pattern, add `@font-face` declarations to `base.css`.

## Appendix B: Accessibility Notes

- All color changes must maintain WCAG AA (4.5:1 body, 3:1 large text)
- Coral CTA on dark bg: `#ff6b6b` on `#080c0a` = 5.2:1 pass
- Coral CTA on light bg: `#cc4444` on `#fafaf8` = 5.8:1 pass (use darker variant)
- Light mode accent `#008f5f` on `#fafaf8` = 4.7:1 pass
- All animations respect `prefers-reduced-motion: reduce`
- Noise textures use `pointer-events: none` and `aria-hidden`

## Appendix C: Performance Budget

- Noise PNGs: ~4KB each (tiny tileable patterns)
- Inter font files: ~24KB per weight x 3 = ~72KB total
- No new JS libraries — sparklines and animations are vanilla
- Particle hero (if implemented): Canvas element, ~2KB JS
- Total added weight: ~80KB (fonts dominate)

---

*Prepared by the Product Board of Directors. External consultation credits: design systems audit (Figma patterns), DTC health brand positioning (Peloton/Whoop competitive analysis), documentary storytelling structure (non-fiction narrative arc), data visualization best practices (Observable/The Pudding), game design progression systems (habit loop + achievement architecture).*

*Next step: Matthew reviews, approves or edits, and we begin the April 1st sprint.*
