# Design System v5 — "Coherence"

Extends (does **not** replace) `DESIGN_SYSTEM_V4_THE_MEASURED_LIFE.md` and
`site/assets/css/tokens.css`. v4 gave us the *materials* (palette, type triad,
spacing, signatures). v5 gives us the *through-line*: one editorial spine and a
small shared kit so every page reads as a single package, not a pile of features.

> Context for this work: `~/.claude/plans/soft-baking-toast.md` (the redesign brief).
> Companions: [PLATFORM_NORTH_STAR.md](PLATFORM_NORTH_STAR.md) (the why),
> [SITE_MAP_AND_INTENT.md](SITE_MAP_AND_INTENT.md) (what each page is for),
> [SITE_UPLEVEL_PLAYBOOK.md](SITE_UPLEVEL_PLAYBOOK.md) (how to change it safely).

---

## 1. The spine: the causal loop

The site documents one thing — a feedback loop — and every page is a station on it:

```
THE DATA ──reads──▶ THE COACHING ──proposes──▶ THE PROTOCOLS
(the engine)         (AI on the data)           (levers that move data)
   ▲                                                  │
   └──────────────────── shifts ─────────────────────┘
                          │
                     THE STORY  (narrates the whole loop, week by week)

THE COCKPIT (/now) = today's slice of the loop.   HOME = teaches the loop.
```

**The one rule that kills "scattered":** every page's first screen must answer
*"which part of the loop am I, and what do I give you?"* — via the `.page-hero` +
`.loop-ribbon` (below). No page is allowed to open cold.

## 2. Information architecture

Top nav = **Home + 5 doors**: `the cockpit · the data · the coaching · the protocols · the story`.

| Door | Route | Loop role |
|---|---|---|
| Home | `/` | Teaches the loop; day-counter; routes in |
| The Cockpit | `/now/` | Today's slice |
| The Data | `/data/` (was `/evidence/`) | The engine: sources + domain readouts, now & over time |
| The Coaching | `/coaching/` | AI reads the data; tabbed coach profiles + board |
| The Protocols | `/protocols/` (new) | Supplements · Experiments · Challenges · Discoveries |
| The Story | `/story/` | Chronicle · Podcast · Journal · Timeline · About (+ meta) |

"Meta / under-the-hood" pages (reset log, the machine, how it holds up, methodology,
cost, AI-failure log, pipeline, build) are **footer-tier**, reachable from About +
the global footer — not top-nav doors. Old `/evidence/*` slugs 301 to `/data/` or
`/protocols/` via `redirects.map`.

## 3. The shared kit (in `tokens.css` §11)

These are additive — a page opts in by using the class; nothing changes until adopted.

### `.prose` — the typographic fix
The single wrapper for **all injected / AI-generated / long-form HTML** (chronicle,
coach reads, evidence readouts, journal, about). Apply it to the **container**; it
pins the triad's jobs on every descendant (`h2/h3` serif, `h4` mono label, body sans,
`blockquote` serif-italic + ember rule, ember links, consistent list + spacing rhythm).

This replaces ad-hoc per-section type — e.g. the old `story.css` rule that set whole
coach subsections (`.coach-char/.coach-hyp/.coach-voice`) to serif wholesale, which was
the literal source of "fonts all over the place under each coach." **Rule going
forward: any block built from model output or JSON-delivered HTML MUST be wrapped in
`.prose` (or `.prose.prose-sm` for sidebars/cards).** Do not style injected `<h2>/<p>/
<ul>` individually.

### `.page-hero` + `.loop-ribbon`
Identical orientation banner on all five doors. `.page-hero` holds an ember `.ph-kicker`
(mono label), a serif `.ph-title`, a muted `.ph-promise` (one line on what the page
gives you), and a `.loop-ribbon` showing the loop with the current door marked `.lr-here`.

### `.loop` (diagram)
The full causal-loop card row (`.loop-node` × 4 + `.loop-arrow`). Home + About use it to
*teach* the loop; the footer can carry a compact version.

### `.provenance`
Every number says where it came from and how fresh: `<p class="provenance"><span
class="pv-src">whoop</span> <span>updated 6m ago</span></p>`. Stale → add `.pv-stale`
(ember). This is the cheap, repeatable "elite / trustworthy" signal — use it under every
readout and chart.

### `.tabset` + `.tabpanel`
Accessible tabs for Coaching profiles (Bio / Track record / Current read) and Protocols
sub-sections. Buttons: `class="tab"` + `role="tab"` + `aria-selected`; panels:
`class="tabpanel"` + `hidden` when inactive.

### Reuse what already exists
The v4 library is large — **before adding a component, search `tokens.css`.** Already
present: `.label`, `.chart`/`.chart-frame` family + `charts.js`, `.site-foot` mega-menu,
`.two-voice` (machine↔human), the measuring-rule spine, the readout/ring/heat/suf-bar
families, `.cb-*` correlation cards, `.dis-*` disagreement cards, coach popover.

## 4. Non-negotiables (inherited from v4)

- Never hardcode a colour/font/radius/spacing outside `tokens.css`.
- One ember accent for "alive / up". Down/flat = muted ink, **never red**. `--alert`
  (oxblood) is reserved for out-of-range vitals state only, never direction.
- Type triad has fixed jobs: Fraunces = human voice, Instrument Sans = interface,
  IBM Plex Mono = machine voice & data (tabular-nums).
- Real first-class light + dark mode; AA contrast both ways.

## 5. Adoption order (design-system-first)

1. **Phase A (this doc + `tokens.css` §11):** kit built, dead tokens repaired. ✅
2. **Phase B:** re-pour each pillar onto the kit, fixing that page's data/content bug
   inline — Data → Coaching → Protocols → Story → Cockpit. Nav flips to 5 doors only
   once `/data/` + `/protocols/` exist (so links never 404).
3. **Phase C:** Home last.

## 6. Verification

`python3 tests/visual_qa.py --screenshot --ai-qa` (gating `visual-qa` CI job) for visual
coherence; the `/site-review` skill for the holistic "does each page's story land" pass.
Local render without deploy: Playwright + `http.server` + route-mocked API.

---

## 7. The motion & interaction layer (v5 "alive")

Added after the coherence pass to take the site from *tasteful-but-static* toward *fascinating*.
Source: `site/assets/js/motion.js` + `tokens.css` §11–12. **All of it is reduced-motion-aware and
fails OPEN** — the hidden reveal state is gated on `html.mo` (set by a tiny inline head script only
when motion is safe), with a head-side failsafe that removes `.mo` after ~2.6s, so if `motion.js`
never runs, content is always shown. Motion can never hide content.

- **Scroll reveals** — sections (`.beat`, `.rd-sec`, `.page-hero`, coach/team sections, cards…) fade
  + rise as they enter view via IntersectionObserver. Works for SPA-injected content too (MutationObserver).
- **Chart draw-in** — SVG line strokes animate on reveal (`stroke-dashoffset`).
- **Count-up** — opt-in via `[data-countup]`; numbers tick from 0. JS that sets a value *after* load
  (e.g. `story.js` for the day counter) calls `window.__moCount(el)` to trigger it.
- **Interactive line charts** — `lineChart` embeds `data-cpts` (normalized coords + a label per
  point); `motion.js` draws a focus dot + cursor-following tooltip. One change → every trend chart
  is explorable. **Runs even under reduced-motion** (it's interaction, not animation).
- **Hover lifts**, **constellation breathe**, **the loop flows** (arrows pulse Data→Coaching→Protocols→Story).

### Earned glow — the "forward depth" rule
The bolder/"2026-forward" feel comes from *restrained depth*, never gloss: a faint warm radial bloom
behind the **home hero** and **cockpit panel** (`--ember-wash`), and a soft ember glow on **truly-live
signals only** (the day counter). **Glow is earned — only on ember/"this-is-up" elements, never
decorative.** A neutral number (e.g. the cockpit's ink-colored level) gets depth, not glow. The test:
if it would read as "AI-template gloss," it's wrong. Restraint is the credibility moat.

### Wiring (every page)
The motion head-guard goes in `<head>` after the theme script; `<script src="/assets/js/motion.js" defer>`
goes before the page's main module script. The three builders inject both (evidence/coaching/dispatches
shells); the hand-authored Home + Cockpit have them inline.

### Headroom (not yet done)
Only `lineChart` is interactive — `barChart`/`dualLineChart`/rings/scatters are not yet. The identity
swing was kept deliberately restrained.
