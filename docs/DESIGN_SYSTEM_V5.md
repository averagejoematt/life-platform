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

---

## 8. The graphic-identity system (icons · sigils · imagery) — DURABLE STANDARD

Added in the visual uplevel (PRs #260–#262). The point is **durability**: this is not a one-off
re-skin. New content, pages, and coaches must keep the theme by **reusing these modules** — most of
it is self-perpetuating by construction. Honours the same `earned glow / no gloss` rule: every mark
encodes identity, never decoration. All of it is code-drawn SVG — raster only as build-time
derivatives of checked-in vectors; AI image gen only under the §8.7 commissioning rule (ADR-106).

### 8.1 The line-icon set — `site/assets/icons/icons.svg` + `site/assets/js/icons.js`
A stroke-based `<symbol>` sprite (`currentColor`, `viewBox 0 0 24 24`). Use it everywhere a domain,
door, or section is labelled — **never reintroduce emoji** for these.
- `icon(name, {size, cls, title})` → an `<svg>` that `<use>`s the sprite. Decorative by default.
- `domainIcon(key, opts)` → resolves any domain name-space (cockpit pillar keys / `/data/` routes /
  coach `short_id`) via `DOMAIN_ICON` to one icon.
- **Adding a domain/icon:** add a `<symbol id="i-NAME">` to the sprite, then map the key(s) in
  `DOMAIN_ICON`. Nothing else — every consumer (cockpit rows, `/data/` nav+title, kickers) picks it up.
- **Door icons** are server-rendered inline `<use>` (no JS) — the nav markup is **duplicated** in
  `v4_build_evidence.py:topbar()`, `v4_build_coaching.py`, `v4_build_dispatches.py`, and the
  hand-authored `site/index.html` + `site/now/index.html`. Change all five together.
- **Gotcha:** keep `.ico` OUT of any `.chart` figure (`.chart svg{width:100%}` would stretch it).

### 8.2 Coach sigils — `site/assets/js/sigils.js`
`sigil(coach)` returns a deterministic geometric "instrument" mark (concentric rings + radial
measuring-ticks + orbital nodes), seeded by the coach's stable id (FNV-1a → mulberry32) — **same
coach → byte-identical mark forever; a NEW coach automatically gets a unique one** with zero work.
- **Rule:** anywhere a coach is rendered (badge, header, roster, popover, digest), use `sigil(c)`.
  Keep initials only as an `.sr-only` fallback. Do not render `c.emoji` for coaches.
- Colour rides the existing per-coach `--coach` channel — the **one sanctioned exception** to the
  single-ember rule (persona identity only, never data encoding). Set `--coach` on a host element.
- Classes: `.sigil` / `.sigil-lg` / `.coach-mark` / `.coach-head` in `tokens.css §13`.

### 8.3 Editorial imagery — `lambdas/editorial_image.py` + the duotone treatment
Atmospheric free-license (Pexels) cover art on the **narrative Story surfaces ONLY** (chronicle ·
podcast · blog). **Never** on data/meal/vitals surfaces — those stay image-free to protect the
truthfulness moat. The generators call it automatically for each new post (fail-soft, kill-switch
`EDITORIAL_IMAGES` default OFF). Front-end renders `image_url` under `.editorial-img .img-duotone`
(a warm ink↔ember wash so any photo reads as editorial texture, not glossy stock) + `.img-credit`
attribution. New narrative surfaces should follow the same `{image_url, image_credit}` optional
contract + the duotone classes. Live since 2026-07-03 (visual uplevel P3): the kill-switch is ON
durably via the email stack's `_email_env`; chronicle AND podcast generators both fetch covers
(the home teaser renders the latest chronicle cover too). SS-11 guardrail applies — a post with
no qualifying image ships honestly bare.

### 8.4 The instrument mark on share cards — `lambdas/og_image_lambda.mjs`
The OG card is on the v5 palette and carries the **same sigil vocabulary** (`instrumentMark()` =
ring + ticks + node, ember). Any new generated share/preview image should reuse the palette
constants + that mark so off-site previews match the site.

### 8.5 The one rule for future work
Before adding a glyph, avatar, emoji, or decorative image: **reach for these modules first**
(`icons.js`, `sigils.js`, `editorial_image.py`, the OG `instrumentMark`). If a new thing needs a
mark, extend the system (a sprite symbol, a `DOMAIN_ICON` entry) rather than introducing a one-off.
That is what keeps the identity coherent as the platform grows.

### 8.6 Pillar identity colors + the character sheet (2026-07)
The character sheet (`/data/character/`) resurrects the legacy RPG page inside this language.
Two sanctioned extensions, same clause structure as `--coach` (§8.2):

- **`--pillar-*` tokens** (`tokens.css`): seven desaturated identity hues, one per pillar
  (sleep · movement · nutrition · metabolic · mind · relationships · consistency). They color
  **pillar-identity encodings only** — ring segments, radar vertices, stat-bar fills, heatmap
  row accents, sparkline strokes — never buttons, text, alerts, or non-pillar data. Ember stays
  the "earned/up" accent; down stays muted ink, never red.
- **`--tier-accent`** (set via `data-tier` on the sheet's section root): used only on the tier
  emblem + hero frame. The **tier emblem** (`sigils.js tierEmblem()`) is the character's identity
  device — stroke-only, currentColor, no gradients — and its shape evolves with the tier
  (hexagon → flame hexagon → shield → crowned shield → crown).

The APIs serve emoji fields (`tier_emoji`, per-pillar `emoji`, effect emoji, challenge `icon`) —
**renderers ignore them all** and resolve marks via `domainIcon()`: movement → `i-training`,
metabolic → `i-glucose`, relationships → `i-people`, consistency → `i-habits`, mind → `i-mind`,
sleep → `i-sleep`, nutrition → `i-nutrition`; the sheet itself → `i-character` (figure-in-ring).
The hero composes the three proven primitives — the weight-driven silhouette (`dfBody`), the
7-segment pillar ring (`charts.js pillarRing`), the tier emblem — all drawn from real data.

### 8.7 Coach portraits — commissioned engraved identity (ADR-106)

The one sanctioned exception to "no AI image gen", drawn exactly (full argument in ADR-106; the
procedure in `docs/design/PORTRAIT_RUNBOOK.md`):

- **AI image generation is a one-time commissioning tool only**, for openly-fictional personas
  (ADR-040 cast) only. It produces *reference candidates* during a commissioning session — a
  generated raster is never a shipped artifact, never checked into `site/`, never regenerated at
  build/runtime. Hand-authored vectors (no AI step at all) are equally sanctioned and preferred.
- **The shipped artifact is a code-drawn layered-SVG recipe** (`config/portraits/<persona_id>.json`,
  fixed layer ids, schema-validated): flat-vector **character illustration** (amended 2026-07-05
  with the #587 pilot approval) — ink contours on `currentColor` over validated flat colour fills
  (per-recipe `palette` + per-element `tone`; skin tones flat and persona-derived), the coach
  channel as the accent tone, shape language per the runbook's style bible (distinct geometric
  base + one hyper-distinctive feature + the silhouette litmus). Rendered by
  `portraits.js portrait(c)` with the **`portrait(c) || sigil(c)` fallback chain** — an
  uncommissioned coach renders exactly as today, forever.
- **Human curation is mandatory**: Matthew approves a **contact sheet** (batch side-by-side,
  light + dark, 40/56/96 px) before anything ships. Kill criterion: 2 failed revision rounds →
  that coach stays sigil-only. Provenance (`_meta`: model/prompt/date/sign-off) required in every
  recipe; a reverse-image sanity check (no resemblance to a findable real person) per round.
- **SS-11 and the PG-14 photoreal NO-GO stay fully in force.** Portraits never ride the
  editorial-image pipeline; photoreal rendering of anyone stays NO-GO.
- **Disclosure is structural**: `aria-label="Illustrated portrait of <name>, a fictional AI
  persona"`; team/about surfaces carry the one-line disclosure sentence (runbook §6).

## 9. Performance budget — LCP/CLS/JS-bytes (#580)

The craft floor the later motion/cinematic phases build on top of: `tests/visual_qa.py` (the
gating CI job, ADR-076) now asserts a per-page performance budget alongside its render checks, so
a future change cannot quietly regress load quality. Numbers below were measured against
production on 2026-07-05 (headless Chromium, `PerformanceObserver` for LCP/CLS, response-body
byte-counting for JS) across the full 33-page sweep — re-derive them (`LCP_BUDGET_MS`,
`CLS_BUDGET`, `JS_BYTES_SOFT_BUDGET` at the top of `tests/visual_qa.py`) if the site's shape
changes enough that the headroom stops making sense, and update this section to match.

| Metric | Observed baseline (33 pages) | Enforced budget | Gate |
|---|---|---|---|
| LCP | 72ms – 1136ms (p90 984ms) | **2500ms** | hard fail (`issues`) |
| CLS | 0.059 – 0.614 (p90 0.570) | **0.75** | hard fail (`issues`) |
| Total JS / page | 119KB – 408KB | **550KB** | soft (`warnings` only) |

Budgets carry headroom over the observed max (LCP ~2.2x, CLS ~1.2x, JS ~1.35x) so ordinary
CI-runner network jitter doesn't flake the gate — the point is catching a real regression (a
newly-added render-blocking script, a runaway layout shift from a new widget), not chasing a
"good" Core Web Vitals score. **The current CLS baseline is already high** (0.5-0.6 on most
`/data/`, `/method/`, `/coaching/` pages) — the known cause is this site's async
data-render pattern (`··` placeholders resolving to real numbers/charts after the API responds),
not a font or layout bug. Lowering it is real future work, not something this issue fixes; the
budget here exists to stop it from getting *worse*, not to certify it's good today.

**Font subsetting.** `scripts/v4_vendor_fonts.py` now keeps only the Google Fonts **latin**
subset (the site is English-only; a browser's `unicode-range` selection never fetched the
vietnamese/latin-ext/cyrillic/cyrillic-ext blocks anyway, so this is a build/deploy-hygiene cut,
not a runtime-fetch one) — 18 vendored woff2 files → 5, 456KB → ~194KB under
`site/assets/fonts/v4/`, and `fonts.css` drops from 26 `@font-face` rules to 10. The weight/style
axis was already tight: the triad is used at weight 400/500 only (`--weight-reg`/`--weight-med`
are the only numeric-weight custom properties in `tokens.css`) with italic scoped to Fraunces
alone (the "human voice" token) — nothing on that axis was vendored-but-unused.

**Preload audit.** Every page preloaded the same three woff2 files, including Fraunces at
**italic** 400. An empirical LCP-element audit (Chrome's `LargestContentfulPaint.element`,
swept across all 33 pages) found the opposite is true almost everywhere: `.hero-h`, `.tier`,
`.page-hero .ph-title`, `.ev-h1`, `.dx-h1` — the actual LCP candidate on Home, Cockpit, and most
hub pages — are all **normal**-style Fraunces at weight 500; italic is reserved for secondary
quote/aside text that's essentially never the largest paint. The preload now points at the
normal-400-latin file instead (same swap across `site/**/index.html` and the three page-builder
scripts' `FONTS` constant). One page — `/method/benchmarks/`'s honest "no readouts yet" empty
state — currently LCPs on italic text; that's a transient sparse-data condition, not the page's
steady-state shape, so it wasn't used to justify keeping italic preloaded everywhere. Per-page-type
preload differentiation (drop Instrument Sans where it's not needed, etc.) was investigated but
**not** adopted: the audit showed Instrument Sans is actually the single most common LCP font
across the sweep (the dominant lede-paragraph style on `/data/`, `/method/`, `/protocols/`,
`/story/`, and `/coaching/` topic pages) and every one of the three families is the real LCP
element on at least one common page type — on a data-driven site where the LCP element can shift
day to day with what's populated, preloading all three uniformly is the robust choice; the
italic→normal swap was the one unconditional, evidence-backed fix.
