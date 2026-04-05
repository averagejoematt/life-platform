# Usability Study Implementation Brief
## averagejoematt.com — All Recommendations with Design & Technical Specs

**Source**: Simulated Usability Study (March 29, 2026) — 15 participants, 5 audience buckets
**Purpose**: Actionable specs for Claude Code sessions. Each item has design intent, technical approach, files to touch, and acceptance criteria.
**Platform state**: v4.4.0 — 67 pages, 59 Lambdas, 116 MCP tools, 26 data sources

---

## TABLE OF CONTENTS

1. [P0-1: Start Here Visitor Routing](#p0-1-start-here-visitor-routing)
2. [P0-2: Board of Directors Transparency Banner](#p0-2-board-of-directors-transparency-banner)
3. [P0-3: Homepage Hero — Transformation-First Frame](#p0-3-homepage-hero-transformation-first-frame)
4. [P0-4: Bloodwork / Labs Observatory Overhaul](#p0-4-bloodwork-labs-observatory-overhaul)
5. [P1-1: For Builders Page Enhancement](#p1-1-for-builders-page-enhancement)
6. [P1-2: Elena Voss AI Attribution](#p1-2-elena-voss-ai-attribution)
7. [P1-3: Methodology Page Enhancement](#p1-3-methodology-page-enhancement)
8. [P1-4: Sleep & Glucose Observatory Visual Overhaul](#p1-4-sleep--glucose-observatory-visual-overhaul)
9. [P1-5: Share Affordance + Expanded OG Images](#p1-5-share-affordance--expanded-og-images)
10. [P1-6: Audience-Specific Landing Pages](#p1-6-audience-specific-landing-pages)
11. [P2-1: What I Eat in a Day Page](#p2-1-what-i-eat-in-a-day-page)
12. [P2-2: PubMed Links on Protocols](#p2-2-pubmed-links-on-protocols)
13. [P2-3: Community Feature (Lightweight)](#p2-3-community-feature-lightweight)
14. [P2-4: Data Export / API Access for Builders](#p2-4-data-export--api-access-for-builders)
15. [MISC-1: Protocols vs Experiments Clarity](#misc-1-protocols-vs-experiments-clarity)
16. [MISC-2: Mobile Responsiveness Audit](#misc-2-mobile-responsiveness-audit)
17. [MISC-3: Elena Pull-Quotes on Observatory Pages](#misc-3-elena-pull-quotes-on-observatory-pages)
18. [MISC-4: "Currently Testing" on Homepage](#misc-4-currently-testing-on-homepage)
19. [MISC-5: Content-Hashed CSS/JS Filenames](#misc-5-content-hashed-cssjs-filenames)
20. [MISC-6: Matt Bio / Photo at Top of Site](#misc-6-matt-bio--photo-at-top-of-site)

---

<a id="p0-1-start-here-visitor-routing"></a>
## P0-1: Start Here Visitor Routing

**Problem**: 11/15 participants struggled in the first 2 minutes. Jessica Park (W3) scored 4.5/10 because she couldn't find the right entry point. 67 pages behind a 6-section dropdown overwhelms first-time visitors.

**Study evidence**: Jessica got lost in Platform pages. Diane clicked randomly. Even Priya (PM) said "a normal person would bounce." Seven participants independently asked for guided onboarding.

### Design Spec

**Implementation**: A full-screen modal overlay that appears on first visit (no cookie found). NOT a separate page — a modal so returning visitors never see it, and first-timers get the routing before they hit the nav.

**Visual design**: Dark overlay matching `--c-black` (#080c0a). Three large cards in a row (responsive to stack vertically on mobile). Each card has:
- An icon or small illustration (SVG, inline)
- A headline (font-display, --text-h3)
- A 1-line description (font-serif, --text-muted)
- A CTA button using existing `.btn .btn--primary` or `.btn--ghost` styles
- The accent color of the card matches its destination section

**Three paths**:

| Card | Headline | Description | Destination | Accent |
|------|----------|-------------|-------------|--------|
| 1 | "The Journey" | "Follow one person's health transformation — honest, public, no filter." | `/story/` | `--c-green-500` |
| 2 | "The Data" | "Explore 26 data sources, N=1 experiments, and live correlations." | `/explorer/` | `--c-amber-500` |
| 3 | "How It's Built" | "A non-engineer built this with Claude. See the full blueprint." | `/builders/` | `--lb-accent` (cyan) |

**Bottom of modal**: A small "Skip — take me to the homepage" link in `--text-faint` monospace. Sets the cookie immediately.

**Cookie**: `amj_visited=1` with 365-day expiry. If cookie exists, modal never shows. Also set on any page navigation (so if someone lands on `/nutrition/` directly, they don't see it on next homepage visit).

### Technical Spec

**Files to modify**:
- `site/assets/js/components.js` — Add modal injection logic at end of IIFE
- `site/assets/css/base.css` — Add modal styles (or inline in components.js to keep it self-contained)

**Approach**:
```
// In components.js, after footer injection:
if (!document.cookie.includes('amj_visited=1') && window.location.pathname === '/') {
  // Inject modal HTML
  // On any card click or "skip" click:
  //   document.cookie = 'amj_visited=1;max-age=31536000;path=/';
  //   Remove modal with fade-out animation
}
```

**Important**: Modal should have `animation: fadeUp 0.4s ease` on entry. Cards should stagger with `animation-delay: 0.1s, 0.2s, 0.3s`. Dismiss should fade out over 0.3s.

**Do NOT**: Create a separate `/start-here/` page. The modal approach means:
- Zero impact on returning visitors
- Works on homepage only (direct links to other pages bypass it)
- No new route needed in nav

### Acceptance Criteria
- [ ] First visit to homepage shows full-screen modal with 3 cards
- [ ] Each card navigates to correct destination and dismisses modal
- [ ] "Skip" link dismisses modal and shows homepage
- [ ] Cookie persists — second visit shows no modal
- [ ] Responsive: cards stack vertically below 768px
- [ ] Animation: fadeUp entry, fade-out dismiss
- [ ] Modal does NOT appear on non-homepage URLs

---

<a id="p0-2-board-of-directors-transparency-banner"></a>
## P0-2: Board of Directors Transparency Banner

**Problem**: 11/15 participants asked "are these real people?" — the #1 confusion point across ALL audience buckets. Creates a trust question at exactly the wrong moment.

**Study evidence**: Sarah Mitchell (W1) thought they were Matt's actual doctors. Diane Foster was confused. Even Priya (PM, T2) flagged it. This is a trust-eroding ambiguity.

### Design Spec

**Location**: Top of every board page (`/board/`, `/board/technical/`, `/board/product/`) — immediately below the page header, before any board member cards.

**Visual**: Left-bordered info block using `--lb-accent` (cyan) — the same pattern as disclaimers elsewhere on the site. NOT a dismissible alert — it should always be visible.

```
┌─────────────────────────────────────────────────────┐
│ ▌ AI ADVISORY FRAMEWORK                             │
│ ▌                                                   │
│ ▌ These advisors are AI-generated personas, not     │
│ ▌ real individuals. Each represents a distinct      │
│ ▌ domain of expertise — designed with deliberate    │
│ ▌ tension pairs to prevent groupthink and ensure    │
│ ▌ rigorous, multi-perspective analysis.             │
│ ▌                                                   │
│ ▌ Learn how the advisory system works →             │
└─────────────────────────────────────────────────────┘
```

**Typography**: Title in monospace uppercase (`font-family: var(--font-mono)`, `font-size: var(--text-2xs)`, `letter-spacing: 0.1em`). Body in regular `--text-sm`, `--text-muted`. Link in `--accent`.

### Technical Spec

**Files to modify**:
- `site/board/index.html` — Add banner HTML after header, before board member content
- `site/board/technical/index.html` — Same
- `site/board/product/index.html` — Same

**CSS**: Use existing pattern from `lb-disclaimer` on the Labs page:
```css
.board-transparency {
  border-left: 3px solid var(--accent);
  padding: var(--space-5) var(--space-6);
  background: var(--accent-bg-subtle, rgba(61,184,138,0.04));
  margin-bottom: var(--space-8);
}
```

**Link target**: "Learn how the advisory system works →" links to `/methodology/` (which already exists and covers the framework).

### Acceptance Criteria
- [ ] Banner appears on all 3 board pages
- [ ] Clear "AI-generated personas" language
- [ ] Styled consistently with existing disclaimer patterns
- [ ] Link to methodology page works
- [ ] Not dismissible — always visible

---

<a id="p0-3-homepage-hero-transformation-first-frame"></a>
## P0-3: Homepage Hero — Transformation-First Frame

**Problem**: The homepage leads with "The Measured Life — AI Health Experiment" which positions it as a tech demo. The highest-engagement audience (weight loss) connects with the TRANSFORMATION story, not the AI story.

**Study evidence**: Sarah Mitchell (W1, 11 visits/30 days) connected instantly with Day 1 vs Today. Every weight-loss participant anchored on the human transformation. Zoe (journalist) said "pick one primary frame." Sofia Herrera (CMO) recommended leading with transformation.

### Design Spec

**Current hero** (approximate):
- Title: "The Measured Life"
- Subtitle: "One person. 25 data sources. An AI that reads my sleep, habits, mood, and relationships..."

**New hero**:
- Eyebrow: `THE MEASURED LIFE` (monospace, `--text-2xs`, `--accent`)
- Title: "One man's public health transformation" (font-display, large)
- Subtitle: "Tracked with 26 data sources. Analyzed by AI. Documented with radical honesty. Every number. Every setback. Everything." (font-serif, `--text-muted`)
- The Day 1 vs Today section should be promoted ABOVE any other content blocks — it's already the most effective element on the page

**Keep**: The existing "What's New Pulse" and vital signs quadrant. These are strong.

**De-emphasize**: Any technical framing in the hero. The AI/data source count can appear further down the page. The hero's job is emotional connection, not technical credibility.

### Technical Spec

**Files to modify**:
- `site/index.html` — Rewrite the `.h-hero` section HTML and update meta descriptions

**Meta tag updates**:
```html
<meta name="description" content="One man's public health transformation — tracked with 26 data sources, analyzed by AI, documented with radical honesty. Every number. Every setback. Everything.">
<meta property="og:description" content="One man's public health transformation. 26 data sources. AI analysis. Radical honesty. Follow the entire journey.">
```

**Important**: Do NOT change the page `<title>` tag from "The Measured Life" — that's the brand name. Only change the visual hero and meta descriptions to lead with transformation.

**Ensure**: Day 1 vs Today section appears as the first data section after the hero, before vital signs quadrant or What's New.

### Acceptance Criteria
- [ ] Hero headline centers transformation narrative
- [ ] "Every number. Every setback. Everything." tagline present
- [ ] Day 1 vs Today is the first content section after hero
- [ ] Meta description + OG description updated
- [ ] Page title remains "The Measured Life"
- [ ] Technical framing (data sources, AI) moves below the fold

---

<a id="p0-4-bloodwork-labs-observatory-overhaul"></a>
## P0-4: Bloodwork / Labs Observatory Overhaul

**Problem**: 9/15 participants asked for bloodwork — the #1 content gap. The Labs page EXISTS at `/labs/` but is functional/clinical in design, not using the established observatory editorial pattern.

**Study evidence**: Maria (R3, husband's heart scare) specifically wanted ASCVD risk. Brandon (W2, post-bariatric) wanted it for post-surgery monitoring. Tyler (R2, nutrition major) wanted it for academic reference. Dr. Rao (A1) said bloodwork is what makes it a "legitimate longevity platform."

### Design Spec

**Transform `/labs/` from clinical table view to observatory editorial pattern** matching Nutrition, Training, and Inner Life observatories.

**Observatory pattern elements to add**:
1. **2-column editorial hero** with animated SVG gauge ring showing overall "in-range percentage" (e.g., 88% of biomarkers in range)
2. **Pull-quotes with evidence badges**: Extract 2-3 meaningful biomarker stories as editorial callouts. Example: `"Fasting glucose dropped 12 points across 3 draws — the metabolic needle is moving."` with badge: `N=1 · 3 DRAWS · TREND CONFIRMED`
3. **Monospace section headers with trailing dash lines** (the `n-section-header::after` pattern)
4. **3-column editorial data spread** showing key biomarker categories with sparkline trend arrows
5. **Left-accent bordered rule cards** for flagged biomarkers with clinical context

**Keep**: The existing accordion-by-category table view — but move it BELOW the editorial section. The editorial hero and pull-quotes draw people in; the detailed table serves the deep-dive.

**New sections to add**:
- **Trend section**: For biomarkers with 3+ draws, show a mini sparkline or directional arrow (improving/worsening/stable)
- **Flagged biomarkers spotlight**: The 9 flagged values should have their own editorial treatment — not just amber badges in a table, but a dedicated "What I'm Watching" section with context about why each is flagged and what protocol changes are addressing it
- **ASCVD risk projection** (if data supports): A computed 10-year ASCVD risk card using the standard Pooled Cohort Equations with available data (age, sex, race, total cholesterol, HDL, systolic BP, diabetes status, smoking status)

**Color accent**: Keep the existing `--lb-accent: #06b6d4` (cyan) — it's well-established for the Labs page.

### Technical Spec

**Files to modify**:
- `site/labs/index.html` — Major restructure: add observatory editorial layer above existing table
- `lambdas/site_api_lambda.py` — Ensure `/api/labs` endpoint returns trend data for multi-draw biomarkers (directional arrows, delta from first to latest draw)

**CSS approach**: Add the observatory editorial patterns. Copy the pattern from Nutrition observatory:
- `.lb-section-header::after` pattern (already exists)
- `.lb-pullquote` class family (adapt from `.n-pullquote` pattern)
- `.lb-gauge-ring` SVG animation (adapt from nutrition/training gauge rings)

**API enhancement**: The `/api/labs` response should include:
```json
{
  "labs": {
    "biomarkers": [...],
    "trends": {
      "glucose_fasting": { "direction": "improving", "delta": -12, "draws": 3 },
      "ldl": { "direction": "stable", "delta": +2, "draws": 3 }
    },
    "in_range_pct": 88,
    "flagged_count": 9,
    "total_draws": 7,
    "ascvd_risk_10yr": null  // compute if sufficient data
  }
}
```

**Gauge ring**: SVG circle with `stroke-dasharray` animation (same pattern as nutrition gauge). Percentage = `in_range_pct`. Ring color = `--lb-accent`.

### Acceptance Criteria
- [ ] Labs page uses observatory editorial pattern (hero, gauge ring, pull-quotes)
- [ ] Pull-quotes have evidence badges with draw count
- [ ] Trend arrows/sparklines for multi-draw biomarkers
- [ ] "What I'm Watching" section for flagged biomarkers
- [ ] Existing table view preserved below editorial section
- [ ] Page loads from `/api/labs` endpoint
- [ ] Responsive: 2-column hero collapses to single column on mobile
- [ ] ASCVD risk card (if data available) or placeholder

---

<a id="p1-1-for-builders-page-enhancement"></a>
## P1-1: For Builders Page Enhancement

**Problem**: The For Builders page exists and is solid, but 3 AI-enthusiast participants would have shared it to hundreds of people — and wanted MORE. The meta-story of a non-engineer building this with Claude IS the headline for the AI audience.

**Study evidence**: Luis (A3) said "this is the most compelling demo of AI-assisted development I've seen." Zoe (A2) said the builder story IS the article she'd write. Derek (T1) asked "where's the GitHub?"

### Design Spec

**The page already has a strong foundation.** Enhance, don't rewrite. Key additions:

1. **"The Meta-Story" section** (new, position after the numbers strip): A 2-3 paragraph narrative section. Who is Matt? Not an engineer. A Senior Director at a SaaS company. Started this on February 22, 2026. Five weeks later: 59 Lambdas. How? Every conversation was with Claude. Frame this as "what's possible when a domain expert pairs with AI."

2. **Update the numbers strip** to current stats: 59 Lambdas (was 52), 116 MCP tools (was 103), 26 data sources (was 19), current monthly cost. Use `data-const` attributes that `site_constants.js` already populates.

3. **"The AI Partnership" section** (new): Specific examples of what Claude did vs what Matt did. This is the content the AI audience craves. Examples:
   - Claude wrote the code. Matt defined the architecture decisions.
   - Claude built the observatory CSS. Matt defined the editorial design language.
   - Claude created the correlation engine. Matt defined the Henning Brandt standard.
   - The Board of Directors system: 34 AI personas that review every decision.

4. **Build timeline update**: Currently stops at Week 5. Extend through current state (Week 5+).

5. **Call-to-action enhancement**: Current CTA links to /platform/, /cost/, /intelligence/. Add: "Subscribe to follow the build →" linking to /subscribe/.

### Technical Spec

**Files to modify**:
- `site/builders/index.html` — Add new sections, update numbers, extend timeline

**Data-const updates**: Ensure `site_constants.js` has current values for:
- `platform.lambdas` = 59
- `platform.mcp_tools` = 116
- `platform.data_sources` = 26
- `platform.monthly_cost` = current value

**No API changes needed** — this is a static content page.

### Acceptance Criteria
- [ ] Numbers strip shows current stats via data-const
- [ ] "The Meta-Story" section frames Matt's background
- [ ] "The AI Partnership" section with specific Claude vs Matt examples
- [ ] Timeline extended beyond Week 5
- [ ] Subscribe CTA added alongside existing links
- [ ] Design matches existing builders page aesthetic

---

<a id="p1-2-elena-voss-ai-attribution"></a>
## P1-2: Elena Voss AI Attribution

**Problem**: Multiple participants were confused about whether Elena Voss is a real person. This creates a trust issue that compounds if unaddressed, especially for the weight-loss audience who emotionally connected with the chronicle.

**Study evidence**: T2 (Priya): "If she's AI, that's cool but you need to be transparent." W1 (Sarah): thought Elena was a real journalist. R1 (Diane): "Is Elena a real person writing about him?"

### Design Spec

**Add a single-line attribution below every chronicle entry:**

```
Written by Elena Voss — an AI narrative voice created to chronicle Matthew's journey.
```

**Typography**: `font-family: var(--font-mono)`, `font-size: var(--text-2xs)`, `color: var(--text-faint)`, `letter-spacing: 0.06em`. Subtle but always present.

**Also add** a brief intro on the Chronicle landing page (`/chronicle/`), near the top:

```
The Measured Life is narrated by Elena Voss, an AI-generated editorial voice.
She writes weekly, drawing from Matthew's real data — wearables, journals, and lab results —
to tell the story behind the numbers. The data is real. The analysis is real.
The voice is AI. The honesty is deliberate.
```

**Position**: Below the page header, above the first chronicle entry. Use the left-border callout pattern (`border-left: 2px solid var(--accent)`).

### Technical Spec

**Files to modify**:
- `site/chronicle/index.html` — Add intro callout below header
- `lambdas/chronicle_lambda.py` (or wherever chronicle HTML is generated) — If chronicle entries are dynamically generated, add the attribution line to the template. If they're static HTML, add to each entry.
- Any individual chronicle entry pages — Add attribution line at bottom of each entry

**Pattern**: Check how chronicle entries are rendered. If they're generated by a Lambda and written to S3, the attribution should be appended in the generation template. If they're static, add to each file.

### Acceptance Criteria
- [ ] Every chronicle entry has Elena Voss AI attribution line
- [ ] Chronicle landing page has intro callout explaining the AI voice
- [ ] Attribution is subtle but always visible (not dismissible)
- [ ] Tone is confident, not apologetic — "the voice is AI. The honesty is deliberate."

---

<a id="p1-3-methodology-page-enhancement"></a>
## P1-3: Methodology Page Enhancement

**Problem**: The Methodology page already exists and is strong, but participants wanted more: governance model, how evidence badges are assigned, and how the Board of Directors AI system works. Dr. Rao (A1) said this page "could be cited in academic papers."

**Study evidence**: Tyler (R2) wanted to reference it in class. Dr. Rao wanted to cite it. Both wanted more detail on the governance model.

### Design Spec

**The page already has strong content.** Add these sections:

1. **"AI Governance Model" section** (new, after Honest Limitations):
   - How the Board of Directors system works: 3 boards, 34 personas, deliberate tension pairs
   - How decisions are made: what triggers a board convocation, how disagreements are resolved
   - The throughline tiebreaker: "does this help a visitor connect the story from any page to any other page?"
   - Link to `/board/` for the full roster

2. **"Evidence Badge System" section** (new, after AI Governance):
   - What each badge means: `N=1 · CGM-CONFIRMED`, `N=1 · PRELIMINARY`, `HENNING STANDARD`, etc.
   - How badges are assigned: minimum observation counts, confidence thresholds
   - The Henning Brandt standard explained: N<30 = low confidence, <12 = preliminary
   - Visual: Show the actual badge HTML/CSS inline so visitors see exactly what they look like

3. **"Confidence Thresholds" table** (within Evidence Badge section):
   | Observations | Confidence Level | Badge |
   |-------------|-----------------|-------|
   | <12 | Preliminary Pattern | `PRELIMINARY · LOW N` |
   | 12-29 | Low Confidence | `N=1 · EMERGING` |
   | 30-59 | Moderate Confidence | `N=1 · CONFIRMED` |
   | 60+ | High Confidence | `N=1 · ESTABLISHED` |

### Technical Spec

**Files to modify**:
- `site/methodology/index.html` — Add new sections

**No API changes needed** — static content additions.

**CSS**: Use existing `.method-section` pattern. The evidence badge display can reuse the pull-quote badge CSS from any observatory page.

### Acceptance Criteria
- [ ] AI Governance section explains the 3-board system
- [ ] Evidence Badge section shows all badge types with visual examples
- [ ] Confidence threshold table is clear and specific
- [ ] Henning Brandt standard is named and explained
- [ ] Links to /board/ from governance section

---

<a id="p1-4-sleep--glucose-observatory-visual-overhaul"></a>
## P1-4: Sleep & Glucose Observatory Visual Overhaul

**Problem**: Already on the roadmap. The usability study confirmed it — these pages don't match the editorial quality of Nutrition, Training, and Inner Life observatories.

**Study evidence**: Rachel (F2, marathon runner) noted Sleep felt less polished. Multiple participants compared these pages unfavorably to Nutrition.

### Design Spec

**Apply the established observatory editorial pattern to both Sleep and Glucose pages.** The pattern (from Nutrition, Training, Inner Life):

1. **2-column editorial hero** with animated SVG gauge ring (primary metric: sleep score for Sleep, time-in-range for Glucose)
2. **Staggered pull-quotes with evidence badges** — 3-4 per page, alternating left/right offset
3. **Monospace section headers with trailing dash lines** (`.n-section-header::after`)
4. **3-column editorial data spreads** for key metrics
5. **Left-accent bordered rule cards** for insights/discoveries
6. **Page-specific accents**: Sleep uses existing sleep blue (`--c-blue-500` or similar), Glucose keeps its existing accent

**Sleep-specific content for pull-quotes**:
- HRV correlation with sleep duration
- Eight Sleep temperature optimization findings
- Sleep architecture breakdown (deep/REM/light percentages)
- Recovery score correlation

**Glucose-specific content for pull-quotes**:
- Time in range percentage
- Best/worst meal responses
- Fasting glucose trend
- Postprandial spike patterns

### Technical Spec

**Files to modify**:
- `site/sleep/index.html` — Major visual overhaul
- `site/glucose/index.html` — Major visual overhaul

**CSS approach**: Each observatory has self-contained `<style>` blocks (per memory note about observatory.css consolidation being on the roadmap). Follow the existing per-page style pattern for now. Copy the editorial class patterns from `site/nutrition/index.html` and adapt:
- Rename `.n-` prefix to `.sl-` for sleep, `.gl-` for glucose
- Update color variables to match each page's accent
- Keep the same structural patterns: `.sl-pullquote`, `.sl-section-header`, etc.

**API endpoints**: Both `/api/sleep` and `/api/glucose` should already return the data needed. If pull-quote content needs to be generated, consider whether these should be:
1. Hardcoded editorial content based on current data (simpler, matches other observatories)
2. Dynamically generated via `write_public_stats()` (more complex but auto-updating)

**Recommendation**: Match whatever pattern Nutrition/Training use. If they pull from `public_stats.json`, do the same for Sleep and Glucose.

### Acceptance Criteria
- [ ] Sleep observatory matches Nutrition/Training editorial quality
- [ ] Glucose observatory matches Nutrition/Training editorial quality
- [ ] Both have animated gauge rings, pull-quotes with evidence badges
- [ ] Both have monospace section headers with trailing dashes
- [ ] Responsive: 2-column hero collapses properly on mobile
- [ ] Page-specific accent colors maintained

---

<a id="p1-5-share-affordance--expanded-og-images"></a>
## P1-5: Share Affordance + Expanded OG Images

**Problem**: The unit of virality is the PAGE, not the site. 9/15 participants shared specific pages, not the homepage. But there's no share affordance on individual pages, and OG images are not page-specific across all pages.

**Study evidence**: Priya shared Inner Life on LinkedIn. Tyler shared with his professor. Amir shared with his training group. Jordan Kim (Growth lead) said "the unit of virality is the page."

### Design Spec

**Share button**: A small, tasteful share element on every page. NOT a social media bar with 5 icons. A single "share" icon (use Lucide `share-2` or similar minimal icon) that:
1. First tries `navigator.share()` (Web Share API — works on mobile, some desktop)
2. Falls back to copying the page URL to clipboard with a brief "Copied!" toast

**Position**: Fixed bottom-right corner, or integrated into the page footer. Should be subtle — monospace label, `--text-faint` color, small icon.

```
[↗ Share this page]
```

On click: Web Share API if available, otherwise copy URL + show "Link copied" toast for 2 seconds.

**OG Images**: The `og-image-generator` Lambda currently generates 12 images. Expand to cover ALL observatory pages and key content pages:

Pages needing unique OG images:
- `/sleep/` — `og-sleep.png`
- `/glucose/` — `og-glucose.png`
- `/nutrition/` — `og-nutrition.png` (may already exist)
- `/training/` — `og-training.png` (may already exist)
- `/mind/` — `og-mind.png`
- `/labs/` — `og-labs.png` (already exists per the labs HTML)
- `/character/` — `og-character.png`
- `/explorer/` — `og-explorer.png`
- `/chronicle/` — `og-chronicle.png`
- `/builders/` — `og-builders.png` (already exists per the builders HTML)
- `/methodology/` — `og-methodology.png`
- `/achievements/` — `og-achievements.png`
- `/weekly/` — `og-weekly.png`

### Technical Spec

**Share button — files to modify**:
- `site/assets/js/components.js` — Add share button injection to every page (same pattern as nav/footer injection)
- `site/assets/css/base.css` — Add share button styles

**Share button JS**:
```javascript
// In components.js, inject share element
var shareEl = document.getElementById('amj-share');
if (shareEl) {
  shareEl.innerHTML = '<button class="share-btn" onclick="amjShare()">↗ Share this page</button>';
}

function amjShare() {
  if (navigator.share) {
    navigator.share({ title: document.title, url: window.location.href });
  } else {
    navigator.clipboard.writeText(window.location.href).then(function() {
      // Show toast
    });
  }
}
```

**OG Images**: 
- Modify `lambdas/og_image_generator_lambda.py` (or equivalent) to generate images for all listed pages
- Each image should use the page's accent color and title
- Redeploy and run to generate new images
- Upload to `site/assets/images/` in S3

**Each page needs**: `<meta property="og:image" content="https://averagejoematt.com/assets/images/og-{page}.png">` — check which pages are missing this and add it.

### Acceptance Criteria
- [ ] Share button appears on every page
- [ ] Web Share API used when available, clipboard fallback otherwise
- [ ] "Copied" toast appears on clipboard copy
- [ ] All observatory + key content pages have unique OG images
- [ ] OG image meta tags present in every page's `<head>`

---

<a id="p1-6-audience-specific-landing-pages"></a>
## P1-6: Audience-Specific Landing Pages

**Problem**: When someone shares the site with a specific audience, there's no tailored entry point. Sarah Mitchell sharing with her weight loss support group would benefit from `/for/weight-loss` instead of the generic homepage.

**Study evidence**: Sofia Herrera (CMO) recommended this. Multiple participants said they'd share specific pages but wished there was a "for people like me" URL.

### Design Spec

**Three landing pages** — lightweight, each 1 page:

1. **`/for/weight-loss/`** — "Your health transformation, tracked honestly"
   - Hero: Emphasize the weight journey, Day 1 vs Today, vice streaks
   - Featured pages: Inner Life, Nutrition Observatory, Weekly Snapshots, Milestones
   - Tone: Warm, encouraging, honest about struggles
   - CTA: Subscribe to follow the journey

2. **`/for/builders/`** — Redirect to existing `/builders/` page (it already serves this purpose well)

3. **`/for/data/`** — "N=1 health science, live"
   - Hero: Emphasize the methodology, evidence badges, correlation engine
   - Featured pages: Data Explorer, Methodology, Experiments, Labs
   - Tone: Academic, rigorous, curious
   - CTA: Explore the data

**Each page structure**:
- Editorial hero with audience-specific messaging
- 4-6 "Start here" cards linking to the most relevant pages for that audience
- Subscribe CTA at bottom
- Minimal — these are routing pages, not content pages

**Design**: Use the existing page pattern (page header with eyebrow → content sections). Keep it clean and focused. Each card should be a link with a headline, 1-line description, and an arrow.

### Technical Spec

**Files to create**:
- `site/for/weight-loss/index.html` — New page
- `site/for/data/index.html` — New page
- `site/for/builders/index.html` — Simple redirect to `/builders/`

**No API changes needed** — these are static routing pages.

**No nav changes needed** — these pages are for SHARING, not for nav discovery. They exist as shareable URLs.

**S3 deploy**: Standard `aws s3 cp` for new page directories.

### Acceptance Criteria
- [ ] `/for/weight-loss/` page with transformation-focused messaging
- [ ] `/for/data/` page with research-focused messaging
- [ ] `/for/builders/` redirects to `/builders/`
- [ ] Each page links to 4-6 most relevant pages for that audience
- [ ] Subscribe CTA on each page
- [ ] Responsive
- [ ] Does NOT appear in main nav

---

<a id="p2-1-what-i-eat-in-a-day-page"></a>
## P2-1: What I Eat in a Day Page

**Problem**: 4 participants asked what Matt actually eats. The nutrition data exists in MacroFactor but there's no "human readable" food log on the site.

**Study evidence**: Sarah (W1): "If he's tracking macros, what is he actually eating?" Brandon (W2): "I want a food log." Two others mentioned meal examples.

### Design Spec

**New page at `/meals/` or a new section within `/nutrition/`** — "What I Actually Eat"

**Format**: A typical day laid out as a meal timeline:
- Breakfast, Lunch, Dinner, Snacks
- Each meal: description, approximate macros (P/C/F), total calories
- Optional: glucose response badge if CGM data available for that meal type
- One or two "meals that surprised me" callouts (meals where glucose response was unexpectedly good or bad)

**This can be manually maintained** — Matt provides a few example days, or the page pulls from MacroFactor data to show recent meal patterns.

**Alternatively**: A "Meal patterns" section showing the most common meals, weekly averages by meal type, and macro distribution.

### Technical Spec

**Option A — Static content page**:
- Create `site/meals/index.html`
- Matt provides 3-5 example meal days as content
- No API needed

**Option B — Dynamic from MacroFactor data**:
- Create `/api/meals` endpoint in site-api Lambda
- Pull from MacroFactor DynamoDB data
- Render meal patterns dynamically
- More complex but auto-updating

**Recommendation**: Start with Option A (static). It's faster to ship and the content is what matters, not the automation. Can upgrade to dynamic later.

### Acceptance Criteria
- [ ] Page shows realistic meal examples with macros
- [ ] Glucose response context where available
- [ ] "Meals that surprised me" callouts
- [ ] Links to/from Nutrition observatory
- [ ] Matches site design system

---

<a id="p2-2-pubmed-links-on-protocols"></a>
## P2-2: PubMed Links on Protocols

**Problem**: When protocols reference evidence ("evidence for Vitamin D supplementation"), there's no link to the actual research. Tyler (R2) and Dr. Rao (A1) both wanted PubMed references.

### Design Spec

**On the Protocols and Supplements pages**, wherever a protocol or supplement references scientific evidence, add a small monospace link:

```
Vitamin D3 — 5000 IU daily
▸ Supports immune function, bone density, and mood regulation
▸ Genome: VDR Taq1 variant detected → enhanced response likely
[PMID: 29943744 ↗]  [PMID: 31405892 ↗]
```

**Link format**: `https://pubmed.ncbi.nlm.nih.gov/{PMID}/`

**Typography**: `font-family: var(--font-mono)`, `font-size: var(--text-2xs)`, `color: var(--accent-dim)`. Opens in new tab.

### Technical Spec

**Files to modify**:
- `site/protocols/index.html` — Add PMID links to supplement/protocol WHY cards
- `site/supplements/index.html` — Same

**This is a content addition, not a feature.** Matt (or Claude) needs to compile the relevant PMIDs for each supplement/protocol. Can be done incrementally — start with the top 5-10 supplements that have the strongest evidence base.

**No API changes needed** — add links directly to HTML.

### Acceptance Criteria
- [ ] At least 5-10 protocols/supplements have PubMed links
- [ ] Links open in new tab
- [ ] Styled consistently with monospace evidence badge aesthetic
- [ ] PMID clearly visible for citation purposes

---

<a id="p2-3-community-feature-lightweight"></a>
## P2-3: Community Feature (Lightweight)

**Problem**: 5 participants wanted community. Kevin (T3) said "I want to talk to other people doing this. Not a subreddit — something small."

**Study evidence**: This was the HIGHEST desire that also has the highest operational complexity. The Product Board rated it P2 because of that complexity.

### Design Spec

**NOT a forum. NOT a chat room. NOT a subreddit.**

**Lightweight approach**: A "Fellow Travelers" or "Walking Alongside" section on the Subscribe page or a standalone page. Features:
1. **Subscriber count display**: "X people are following this journey" (already trackable from DynamoDB subscriber table)
2. **Anonymous "I'm here too" button**: One-click acknowledgment — "I'm on a similar journey." Shows a count. No accounts, no profiles, no conversation.
3. **Monthly reader question**: One curated question from a subscriber, answered in the weekly digest. This creates the FEELING of community without the overhead of maintaining one.
4. **Redirect to external**: If Matt wants deeper community later, link to a Discord or Circle — but don't build it into the platform.

### Technical Spec

**Lightweight implementation**:
- Add subscriber count to `/subscribe/` page (pull from existing DynamoDB subscriber data via `/api/stats` or similar)
- "I'm here too" button: Increment a DynamoDB counter. Simple POST to a new endpoint. No auth needed — rate limit by IP to prevent spam.
- Monthly reader question: Manual curation, added to weekly digest template

**This is intentionally minimal.** Full community is a different product with different operational requirements.

### Acceptance Criteria
- [ ] Subscriber count displayed on subscribe page
- [ ] "I'm here too" count visible (even if it starts at 0)
- [ ] No accounts, no profiles, no conversation features
- [ ] Path to deeper community acknowledged but deferred

---

<a id="p2-4-data-export--api-access-for-builders"></a>
## P2-4: Data Export / API Access for Builders

**Problem**: Derek (T1) said "I want to fork this." Luis (A3) wanted to reference patterns. Tech users want to play with the data or build their own version.

### Design Spec

**A "Data & API" section on the For Builders page** with:
1. **Public API documentation**: List the public endpoints (`/api/stats`, `/api/labs`, `/api/correlations`, etc.) with example responses
2. **Data export**: A downloadable JSON or CSV of anonymized/aggregated data (NOT raw personal data — summary statistics only)
3. **Architecture template**: A "starter kit" description — the minimum AWS resources needed to build a similar system

### Technical Spec

**Files to modify**:
- `site/builders/index.html` — Add "API & Data" section

**API docs approach**: Simple static HTML showing endpoint paths and example JSON responses. No Swagger/OpenAPI needed — just clean documentation matching the site's monospace aesthetic.

**Data export**: Generate a static JSON file via a Lambda or manual process, upload to S3, link from the builders page. Content: aggregated weekly averages (not daily raw), correlation matrix, character score history.

### Acceptance Criteria
- [ ] Public API endpoints documented on builders page
- [ ] Example responses shown in code blocks
- [ ] Data export link (JSON) with aggregated/anonymized data
- [ ] Clear note: "This is aggregated data, not raw daily values"

---

<a id="misc-1-protocols-vs-experiments-clarity"></a>
## MISC-1: Protocols vs Experiments Clarity

**Problem**: The distinction between Protocols and Experiments confused 5+ participants. "Are protocols things he's doing, and experiments things he's testing?"

### Design Spec

**Add a brief inline definition at the top of each page:**

On Protocols page:
```
Protocols are what I do consistently — daily habits, supplement stacks, sleep routines.
They're the system. → Experiments test whether the system should change.
```

On Experiments page:
```
Experiments are what I'm actively testing — structured N=1 trials with a hypothesis,
protocol, and measured outcome. → Protocols are the stable system experiments can change.
```

**Also**: Ensure the pipeline visualization (Protocols → Experiments → Discoveries) is prominently linked from both pages. If it's currently only visible on one, add a cross-link.

### Technical Spec

**Files to modify**:
- `site/protocols/index.html` — Add inline definition after header
- `site/experiments/index.html` — Add inline definition after header

**Trivial change** — 2-3 lines of HTML per page.

### Acceptance Criteria
- [ ] Protocols page has inline definition distinguishing it from Experiments
- [ ] Experiments page has inline definition distinguishing it from Protocols
- [ ] Cross-links between the two pages
- [ ] Pipeline visualization linked from both

---

<a id="misc-2-mobile-responsiveness-audit"></a>
## MISC-2: Mobile Responsiveness Audit

**Problem**: The 2-column editorial hero breaks below tablet width. Several observatory pages need a mobile pass.

### Design Spec

**Systematic audit of all observatory pages at 375px (iPhone SE), 390px (iPhone 14), and 768px (iPad) widths.**

**Key breakpoints to check**:
- 2-column editorial heroes → collapse to single column
- Gauge ring SVGs → ensure viewBox scales properly
- Pull-quote offsets (`.n-pullquote--left`, `.n-pullquote--right`) → remove offset on mobile
- 3-column data spreads → collapse to single column
- Nav dropdown → verify mobile overlay works
- Evidence badges → ensure they don't overflow
- Data Explorer scatter plots → touch-friendly controls

### Technical Spec

**This is a CSS-only task** across multiple pages. No JS or API changes.

**Files to audit**:
- `site/nutrition/index.html`
- `site/training/index.html`
- `site/mind/index.html`
- `site/sleep/index.html`
- `site/glucose/index.html`
- `site/labs/index.html`
- `site/index.html` (homepage)
- `site/character/index.html`

**Pattern**: Add `@media (max-width: 768px)` rules for each page's observatory-specific classes. The global `base.css` handles general responsiveness; each page needs its own mobile pass for observatory-specific layouts.

### Acceptance Criteria
- [ ] All observatory pages render cleanly at 375px
- [ ] 2-column heroes collapse to single column
- [ ] Pull-quote offsets removed on mobile
- [ ] Gauge rings scale properly
- [ ] No horizontal scroll on any page at mobile widths
- [ ] Nav overlay works on all pages

---

<a id="misc-3-elena-pull-quotes-on-observatory-pages"></a>
## MISC-3: Elena Pull-Quotes on Observatory Pages

**Problem**: The Elena Voss chronicle is the most emotionally resonant content on the site, but it's isolated on the Chronicle page. Fragments should appear as connective tissue across observatory pages.

**Study evidence**: Ava Moreau (Content Strategist) recommended this. The Product Board's throughline tiebreaker demands it: "does this help a visitor connect the story from any page to any other page?"

### Design Spec

**One Elena Voss pull-quote per observatory page**, positioned between data sections. Example:

On Sleep observatory:
```
"On the nights he sleeps well, you can hear it in his writing the next day.
The data confirms what the words already show."
— Elena Voss, Week 12
```

On Training observatory:
```
"He doesn't train like someone who hates his body.
He trains like someone learning to live in it."
— Elena Voss, Week 9
```

**Badge**: `CHRONICLE · WEEK {N}` in the existing pull-quote badge pattern.

**Link**: Each quote links to the full chronicle entry it's from.

### Technical Spec

**Option A — Static**: Manually add one quote to each observatory page's HTML.
**Option B — Dynamic**: Add Elena pull-quotes to `public_stats.json` output from `write_public_stats()`, so they update when new chronicle entries are published.

**Recommendation**: Start with Option A. Curate the best quotes manually. Upgrade to dynamic later if the chronicle grows enough to warrant it.

**Files to modify** (Option A):
- `site/sleep/index.html`
- `site/glucose/index.html`
- `site/nutrition/index.html`
- `site/training/index.html`
- `site/mind/index.html`
- `site/labs/index.html`

### Acceptance Criteria
- [ ] Each observatory page has one Elena Voss pull-quote
- [ ] Quote links to the source chronicle entry
- [ ] Badge shows `CHRONICLE · WEEK {N}`
- [ ] Styled using existing pull-quote pattern
- [ ] AI attribution clear (per P1-2)

---

<a id="misc-4-currently-testing-on-homepage"></a>
## MISC-4: "Currently Testing" on Homepage

**Problem**: Amir (F3) asked "Why isn't there a 'Currently Testing' section on the homepage? I want to know what experiment is running RIGHT NOW."

### Design Spec

**A small card on the homepage** (after Day 1 vs Today, near What's New Pulse) showing the active experiment:

```
┌────────────────────────────────────┐
│  CURRENTLY TESTING                 │
│                                    │
│  Creatine & Glucose Response       │
│  Day 14 of 30 · Hypothesis: ...   │
│                                    │
│  See experiment →                  │
└────────────────────────────────────┘
```

**Design**: Monospace eyebrow, card with left-accent border (experiment accent color), link to `/experiments/`.

### Technical Spec

**Data source**: The `/api/experiments` endpoint (or `public_stats.json`) should already include active experiment data. Pull the current active experiment and render a card.

**Files to modify**:
- `site/index.html` — Add "Currently Testing" card in the appropriate section
- May need JS fetch to `/api/experiments` to get current active experiment dynamically

### Acceptance Criteria
- [ ] Homepage shows active experiment card
- [ ] Shows experiment name, day count, hypothesis
- [ ] Links to full experiment page
- [ ] Handles "no active experiment" state gracefully (hide card or show "No active experiment")

---

<a id="misc-5-content-hashed-cssjs-filenames"></a>
## MISC-5: Content-Hashed CSS/JS Filenames

**Problem**: Already on post-launch roadmap. Cache busting ensures visitors always get the latest CSS/JS without CloudFront cache issues.

### Design Spec

Not a visual change — infrastructure improvement.

### Technical Spec

**Approach**: Build step that:
1. Hashes the content of each CSS/JS file
2. Renames to `{name}.{hash}.css` / `{name}.{hash}.js`
3. Updates all HTML references to the hashed filenames
4. Deploys to S3

**Files involved**:
- All CSS files in `site/assets/css/`
- All JS files in `site/assets/js/`
- All HTML files that reference them

**Script**: Create `deploy/hash_assets.py` that:
1. Reads each CSS/JS file
2. Computes MD5 hash (first 8 chars)
3. Copies to `{name}.{hash}.{ext}`
4. Regex-replaces references in all HTML files
5. Outputs manifest for deploy verification

### Acceptance Criteria
- [ ] Deploy script generates hashed filenames
- [ ] All HTML references updated automatically
- [ ] Old unhashed files still work (backward compatibility during transition)
- [ ] CloudFront invalidation not needed after asset updates

---

<a id="misc-6-matt-bio--photo-at-top-of-site"></a>
## MISC-6: Matt Bio / Photo at Top of Site

**Problem**: Diane (R1) said "I want to know WHO this person is before I see numbers. Put a photo of Matt and a paragraph about who he is right at the top."

### Design Spec

**This is partially addressed by the Start Here modal (P0-1) and homepage hero rewrite (P0-3).** But consider adding a small "About Matt" element to the homepage — a 2-sentence bio with a photo, positioned near the Day 1 vs Today section.

```
MATTHEW WALKER · TACOMA, WA
Senior Director at a SaaS company. Started at 297 lbs on Feb 22, 2026.
Built this entire platform with Claude. No engineering background.
```

**Photo**: If Matt provides one, use it. If not, the character sheet avatar or a simple monogram serves the purpose.

**Position**: Above or beside Day 1 vs Today. Small, not hero-sized. The data should still dominate — this just provides human context.

### Technical Spec

**Files to modify**:
- `site/index.html` — Add bio element near Day 1 vs Today section

**Requires**: A photo from Matt (or decision to use an avatar/monogram instead).

### Acceptance Criteria
- [ ] 2-sentence bio visible near top of homepage
- [ ] Photo or avatar present
- [ ] Does not compete with Day 1 vs Today for visual attention
- [ ] Matches site design system

---

## IMPLEMENTATION SEQUENCE

Recommended order for Claude Code sessions, balancing impact with dependencies:

### Session 1 — Quick Wins (est. 1 session)
- P0-2: Board transparency banner (trivial, fixes #1 confusion)
- P1-2: Elena Voss attribution (trivial, fixes trust issue)
- MISC-1: Protocols vs Experiments clarity (trivial, fixes confusion)

### Session 2 — Homepage & Routing (est. 1-2 sessions)
- P0-3: Homepage hero rewrite
- P0-1: Start Here modal
- MISC-4: Currently Testing card on homepage
- MISC-6: Matt bio element

### Session 3 — Labs Observatory Overhaul (est. 2 sessions)
- P0-4: Labs page observatory editorial pattern
- API endpoint enhancement for trends/gauge data

### Session 4 — Observatory Visual Parity (est. 2 sessions)
- P1-4: Sleep observatory overhaul
- P1-4: Glucose observatory overhaul

### Session 5 — Builders & Methodology (est. 1 session)
- P1-1: For Builders page enhancement
- P1-3: Methodology page enhancement
- P2-4: Data export / API docs on builders page

### Session 6 — Sharing & Distribution (est. 1 session)
- P1-5: Share affordance + OG image expansion
- P1-6: Audience-specific landing pages

### Session 7 — Content & Polish (est. 1-2 sessions)
- MISC-3: Elena pull-quotes on observatory pages
- P2-1: What I Eat in a Day page
- P2-2: PubMed links on protocols

### Session 8 — Mobile & Infrastructure (est. 1-2 sessions)
- MISC-2: Mobile responsiveness audit
- MISC-5: Content-hashed filenames

### Deferred
- P2-3: Community feature (low-lift version can be done anytime; full version deferred)

---

## REFERENCE: Current Nav Structure (from components.js)

```
The Story    → Home, My Story, The Mission, Milestones, First Person
The Data     → Sleep, Glucose, Nutrition, Training, Inner Life, Labs, Benchmarks, Data Explorer
The Pulse    → Today, The Score, Habits, Accountability
The Practice → The Stack, Protocols, Supplements | Experiments, Challenges, Discoveries
The Platform → How It Works, The AI, AI Board, Methodology, Cost, Tools, For Builders
The Chronicle → Chronicle, Weekly Snapshots, Weekly Recap, Ask the Data, Subscribe
```

## REFERENCE: Design System Tokens (from tokens.css)

- `--c-black: #080c0a` (page background)
- `--c-surface-1: #0f1612` (card background)
- `--c-green-500: #3db88a` (primary accent)
- `--c-amber-500: #c8843a` (journal accent)
- `--c-coral-500: #ff6b6b` (CTA accent)
- `--lb-accent: #06b6d4` (labs cyan)
- `--font-display` = display headings
- `--font-mono` = monospace labels/tags
- `--font-serif` = body prose on story pages
- Observatory pattern: 2-col hero, gauge rings, pull-quotes with evidence badges, monospace section headers with `::after` dashes, 3-col data spreads, left-accent rule cards

## REFERENCE: Key Conventions

- All pages use `components.js` for nav/footer injection
- `site_constants.js` provides `data-const` attribute population
- `reveal.js` handles scroll-triggered fade-in animations
- Observatory pages use self-contained `<style>` blocks (not shared CSS file)
- Deploy: `aws s3 cp` for single files, never `sync --delete`
- CloudFront invalidation: `aws cloudfront create-invalidation --distribution-id E3S424OXQZ8NBE --paths "/path/*"`
