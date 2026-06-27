# Design System v5 — "Coherence"

Extends (does **not** replace) `DESIGN_SYSTEM_V4_THE_MEASURED_LIFE.md` and
`site/assets/css/tokens.css`. v4 gave us the *materials* (palette, type triad,
spacing, signatures). v5 gives us the *through-line*: one editorial spine and a
small shared kit so every page reads as a single package, not a pile of features.

> Context for this work: `~/.claude/plans/soft-baking-toast.md` (the redesign brief).

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
