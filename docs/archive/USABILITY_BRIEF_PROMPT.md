# Claude Code Session Prompt — Usability Study Implementation

Paste the following into Claude Code to begin:

---

```
Read docs/USABILITY_IMPLEMENTATION_BRIEF.md — this is a comprehensive implementation brief generated from a simulated usability study of averagejoematt.com with 15 participants across 5 audience buckets (tech workers, fitness enthusiasts, weight loss, AI enthusiasts, general audience). The Product Board synthesized all findings into 20 prioritized recommendations with full design and technical specs.

Start with the recommended Session 1 — Quick Wins (P0-2, P1-2, MISC-1), which are the three trivial changes that fix the top confusion points identified by the study:

1. P0-2: Board of Directors transparency banner — add a left-bordered info block at the top of /board/, /board/technical/, and /board/product/ pages, immediately below the page header, clearly stating these are AI-generated personas. 11/15 participants asked "are these real people?" Use the existing disclaimer pattern (border-left: 3px solid var(--accent), background: var(--accent-bg-subtle)). Link "Learn how the advisory system works →" to /methodology/.

2. P1-2: Elena Voss AI attribution — add a single attribution line below every chronicle entry: "Written by Elena Voss — an AI narrative voice created to chronicle Matthew's journey." Monospace, --text-2xs, --text-faint. Also add a brief intro callout on the /chronicle/ landing page explaining: "The data is real. The analysis is real. The voice is AI. The honesty is deliberate."

3. MISC-1: Protocols vs Experiments clarity — add a brief inline definition at the top of both /protocols/ and /experiments/ pages distinguishing them from each other, with cross-links. Protocols = the stable system. Experiments = active tests that might change the system.

Read the brief for full design specs, CSS patterns, file paths, and acceptance criteria for each item. After completing Session 1, we'll move to Session 2 (Homepage & Routing — P0-3, P0-1, MISC-4, MISC-6).

Before starting, read handovers/HANDOVER_LATEST.md for current platform state.
```

---

## For subsequent sessions, paste:

### Session 2 — Homepage & Routing
```
Continue with the usability implementation brief (docs/USABILITY_IMPLEMENTATION_BRIEF.md), Session 2 — Homepage & Routing. Four items:

1. P0-3: Homepage hero rewrite — change the hero from "AI experiment" framing to transformation-first: "One man's public health transformation." Promote Day 1 vs Today above all other content blocks. Update meta descriptions. Keep page title as "The Measured Life."

2. P0-1: Start Here visitor routing modal — full-screen modal on first homepage visit (no amj_visited cookie). Three cards: "The Journey" → /story/, "The Data" → /explorer/, "How It's Built" → /builders/. Cookie-based dismissal. fadeUp animation with staggered delays. Skip link at bottom. Modal only on homepage.

3. MISC-4: "Currently Testing" card on homepage — small card showing the active experiment (name, day count, hypothesis) with link to /experiments/. Handle "no active experiment" gracefully.

4. MISC-6: Matt bio element — 2-sentence bio near Day 1 vs Today section. "Senior Director at a SaaS company. Started at 297 lbs on Feb 22, 2026. Built this entire platform with Claude."

Read the brief for full specs. Read handovers/HANDOVER_LATEST.md first.
```

### Session 3 — Labs Observatory Overhaul
```
Continue with usability implementation brief, Session 3 — P0-4: Bloodwork / Labs Observatory Overhaul. This was the #1 content gap (9/15 participants asked for it).

The Labs page exists at /labs/ but uses a clinical table layout. Transform it to use the established observatory editorial pattern matching Nutrition/Training/Inner Life: 2-column editorial hero with animated SVG gauge ring (in-range percentage), staggered pull-quotes with evidence badges showing draw counts, monospace section headers with trailing dashes, "What I'm Watching" section for flagged biomarkers, trend arrows for multi-draw biomarkers. Keep the existing accordion table below the editorial section.

May need to enhance the /api/labs endpoint to include trend data and in_range_pct. Use --lb-accent: #06b6d4 (cyan). Read site/nutrition/index.html for the editorial pattern to replicate.

Full specs in the brief. Read handovers/HANDOVER_LATEST.md first.
```

### Session 4 — Observatory Visual Parity
```
Continue with usability implementation brief, Session 4 — P1-4: Sleep & Glucose Observatory Visual Overhaul.

Both pages need to match the editorial quality of Nutrition/Training/Inner Life observatories. Apply the established pattern: 2-column editorial hero with animated SVG gauge ring, staggered pull-quotes with evidence badges, monospace section headers with trailing dashes, 3-column editorial data spreads, left-accent bordered rule cards.

Use site/nutrition/index.html as the reference implementation. Rename class prefixes: .sl- for sleep, .gl- for glucose. Keep each page's existing accent color. Self-contained <style> blocks per page (not shared CSS file — that consolidation is a separate roadmap item).

Full specs in the brief. Read handovers/HANDOVER_LATEST.md first.
```

### Session 5 — Builders & Methodology
```
Continue with usability implementation brief, Session 5 — three items:

1. P1-1: For Builders page enhancement — add "The Meta-Story" section (who Matt is, non-engineer background), "The AI Partnership" section (Claude vs Matt responsibilities), update numbers strip to current stats via data-const, extend build timeline past Week 5, add subscribe CTA.

2. P1-3: Methodology page enhancement — add "AI Governance Model" section (3 boards, 34 personas, tension pairs, throughline tiebreaker), "Evidence Badge System" section (all badge types with visual examples), confidence threshold table (Henning Brandt standard: N<30 = low, <12 = preliminary).

3. P2-4: Data export / API docs — add an "API & Data" section to the builders page documenting public endpoints with example JSON responses. Generate a downloadable aggregated stats JSON.

Full specs in the brief. Read handovers/HANDOVER_LATEST.md first.
```

### Session 6 — Sharing & Distribution
```
Continue with usability implementation brief, Session 6 — two items:

1. P1-5: Share affordance + OG images — add a share button to every page via components.js injection. Use navigator.share() with clipboard fallback. Show "Copied" toast. Also expand og-image-generator to cover all observatory + key content pages (13+ new images).

2. P1-6: Audience-specific landing pages — create /for/weight-loss/ (transformation-focused, links to Inner Life, Nutrition, Weekly Snapshots, Milestones) and /for/data/ (research-focused, links to Data Explorer, Methodology, Experiments, Labs). /for/builders/ redirects to /builders/. These are shareable routing pages, NOT in the main nav.

Full specs in the brief. Read handovers/HANDOVER_LATEST.md first.
```

### Session 7 — Content & Polish
```
Continue with usability implementation brief, Session 7 — three items:

1. MISC-3: Elena pull-quotes on observatory pages — one Elena Voss pull-quote per observatory page (Sleep, Glucose, Nutrition, Training, Inner Life, Labs), positioned between data sections. Badge: CHRONICLE · WEEK {N}. Links to source chronicle entry. Start with manually curated quotes (Option A).

2. P2-1: What I Eat in a Day page — create /meals/ showing typical meal examples with macro breakdowns and glucose response context. Start static (Option A). Include "meals that surprised me" callouts.

3. P2-2: PubMed links on protocols — add PMID links to the top 5-10 supplements/protocols on /protocols/ and /supplements/ pages. Format: [PMID: XXXXXXXX ↗] in monospace, opens in new tab.

Full specs in the brief. Read handovers/HANDOVER_LATEST.md first.
```

### Session 8 — Mobile & Infrastructure
```
Continue with usability implementation brief, Session 8 — two items:

1. MISC-2: Mobile responsiveness audit — systematic audit of all observatory pages at 375px, 390px, and 768px. Key fixes: 2-column heroes collapse to single column, pull-quote offsets removed, gauge rings scale, no horizontal scroll, nav overlay works. CSS-only task across all observatory pages.

2. MISC-5: Content-hashed CSS/JS filenames — create deploy/hash_assets.py that hashes CSS/JS files, renames to {name}.{hash}.{ext}, updates all HTML references, outputs manifest. Eliminates need for CloudFront invalidation after asset updates.

Full specs in the brief. Read handovers/HANDOVER_LATEST.md first.
```
