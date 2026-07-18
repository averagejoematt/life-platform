# Design System v5 — "Coherence"

> **Status:** canonical · **Owner:** Matthew · **Verified:** 2026-07-11

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
Every SVG/div chart is now interactive (`data-cpts`, #582). The identity swing was kept deliberately restrained.

---

## 7a. The confidence grammar — uncertainty as a first-class visual (ADR-105, #551)

The rigor backend produces **real** intervals (block-bootstrap CIs), **real** sample sizes (overlapping-day `n`), and graded forecasts. Most 2026 health products hide all of it; here it is drawn, honestly — *uncertainty rendered beautifully is the "ahead of its time" look*. Source: three reusable helpers in `charts.js`, tokens in `tokens.css` (the `--band-*` set + the `.cf-*` classes).

**The one grammar, read the same on every chart** (`confLevel(...)` in `charts.js` maps a real input — CI width, `n`, or a `provisional` flag — to a level):

| level | when | visual treatment |
|---|---|---|
| **HIGH** | tight CI (≤0.5 of the estimate), or `n ≥ 21`, or stated confidence ≥ 0.8 | a **defined, tight** band (solid ember edge) / a **solid ember** dot row — trust it |
| **MEDIUM** | wider CI, or `n ≥ 8`, or confidence ≥ 0.5 | a **wider, dashed-edge** band / a **muted** dot row — directional |
| **LOW** | provisional, very wide, or `n < 8` | **NO band at all** — the point is drawn honestly, never a fabricated spread |

**ONE hue (ember), never red.** Band opacity + edge treatment carry the message; the width *is* the interval.

**The three primitives (all bind to REAL data — the hard rule):**
- **Fan chart** — `projectionCone(...)`, extended so the widening band's edges are the real block-bootstrap slope CI (`weekly_rate_ci_low/high`) and the dated "bet" is the backend's own goal-date **range** (`projected_goal_date_earliest/latest`), not a point. Open-ended slow bound ⇒ the slow edge holds flat (goal not guaranteed at this trajectory), honestly. *Applied: the weight projection (`/data/physical/`).*
- **CI band / whisker** — `ciWhisker(value, lo, hi, …)`: a point estimate with its real interval on an auto-scaled rail + a faint **zero reference** so "the interval crosses zero → the direction isn't established" reads at a glance. *Applied: the weekly-rate forecast (`/data/physical/`).*
- **Sample-size dots** — `nDots(n, …)`: `n` as a row of dots so the reader **sees** the evidence weight, not just a number. Real overlapping-day `n` only, never padded. *Applied: the Discoveries correlations + the intelligence correlation matrix.*

**The honest fallback is the whole point:** where an interval isn't available, draw the **point**, not a guessed band (the LOW treatment). A fabricated spread to look sophisticated is exactly the "AI-template gloss" the earned-glow rule forbids.

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

## 10. The mobile / responsive layer (the spec — #998 Epic B)

The site is **one responsive codebase + an installable Cockpit PWA** (board-ratified
2026-06-14, PRs #118/#119) — not a separate mobile build. This section is the **spec a PR
must satisfy** on the responsive layer, written after the 2026-07-11 mobile review filed it
as tribal knowledge (this doc had zero mobile content before #1011). The enforcing harness is
the pre-merge render gate at 390 + 360 (`tests/pr_render_gate.py`, #1012) plus the failure-class
assertions in `tests/visual_qa.py` (#1013): a PR that violates the rules below fails CI.

### 10.1 Breakpoints — six canonical boundaries, nothing else (#1006)

CSS custom properties **cannot** be used inside `@media` queries and the site has **no CSS
build step**, so breakpoints are documented **named constants** (see the block at the top of
`tokens.css`), not `var()`s. Every `@media` in `site/assets/css/**` uses exactly one of:

| token | value | job |
|---|---|---|
| `--bp-xs` | 360 | tiny-phone last resort (hide brand tag, shrink door labels) |
| `--bp-sm` | 480 | small phone — stack tight 2-ups, drop non-essential columns |
| `--bp-md` | 600 | **phone / chrome boundary** — app-bar, single-column, the "is this a phone" call |
| `--bp-lg` | 760 | tablet — 2-col content grids, sticky side rails begin |
| `--bp-tw` | 820 | tablet-wide — the evidence 2-col reading layout (rail + readout) |
| `--bp-xl` | 900 | desktop — 3-col grids, hero / subscribe split-screens |

**Rule:** pick the boundary by *job*, not pixel-taste. **Convention:** `max-width` uses the
token exactly (360/480/600/760/820); `min-width` uses **token+1** (601/761/821/901) so a
min/max pair straddling a boundary never both fire at the same pixel. A PR must not introduce
a seventh value — `grep -rhoE '\((max|min)-width: *[0-9]+px\)' site/assets/css` returns only
those nine numbers. **Enforced (#1212):** `scripts/check_css_tokens.py` turns that grep into an
assertion (a rogue value fails the gate), alongside the raw-hex / font-size / undefined-token
sweep over the seven consumer sheets; run in CI via `tests/test_css_tokens.py`.

### 10.2 The bottom app-bar — @layer, not !important (#1007)

On mobile (`≤600`) the five doors become a **fixed, thumb-reachable bottom app-bar**. It is
built with **CSS cascade layers**, declared once at the top of `tokens.css`:
`@layer chrome-base, chrome;`.
- **chrome-base** — the per-door *desktop* nav chrome (`.doors`, `.story-top`, `.cockpit-top`,
  …), which lives in `cockpit.css` / `story.css` / `evidence.css` (they load *after* tokens.css).
- **chrome** — the mobile bottom app-bar (tokens.css). A *later* layer, so it wins over
  chrome-base **by layer order** — no `!important`, no specificity war.

**Load-bearing, do not remove:** the **backdrop-filter neutralizer** — a `backdrop-filter` /
`transform` / `filter` ancestor creates a containing block that traps `position:fixed` children,
which pins the bar to the top bar instead of the viewport bottom. The neutralizer zeroes those
on `.story-top/.ev-top/.cockpit-top` at mobile width. (Only `.story-top` actually sets one; the
rest are defensive.)

**Rules for a PR touching the chrome:** (a) never add an `!important` to a `.doors`/app-bar rule
— put the competing rule in `@layer chrome-base` instead; (b) any rule that could beat the app-bar
must be layered (unlayered rules beat *both* layers); (c) the app-bar row width ≤ viewport at 360
**and** 390, the theme toggle on-screen + tappable, no door-label truncation, follow pill hidden
(all asserted by #1013). The doors stack **icon-over-label** (`flex-direction:column` + `min-width:0`)
so the longest word ("protocols") gets the full door width.

### 10.3 Touch grammar

Charts use a **Pointer-Events** grammar (`motion.js`) — not hover-first — so a line chart is
explorable by touch, and a **~2600ms fail-open timer** un-gates motion if `motion.js` never
initializes (so reveals can't strand content). **Scroll-reveal is height-independent**
(`threshold:0` + `rootMargin`, #1002): a fractional IntersectionObserver threshold silently never
fires on a section taller than `viewport/threshold`, so any reveal wrapper over a data-driven list
**must** use `threshold:0`. Reduced-motion (`prefers-reduced-motion`) paints everything immediately.

### 10.4 Tap-target floor — 44px effective (#1010)

Interactive controls must reach a **44px effective hit area** on touch, expanded *without visual
redesign*, by technique:
- **isolated icon/button** (theme toggle, intro "×"): a transparent centered `::after` overlay,
  expanded **vertically** (`height: max(100%,44px)`, `width:100%`) — a horizontal overlay on the
  right-edge app-bar toggle would overflow the fixed bar.
- **form control** (scrubbers, selects): `min-height: 44px`.
- **text button**: `min-height:44` + block padding.
- **checkbox**: expand the wrapping `<label>` (pseudo-elements don't render on replaced inputs).
- **inline prose link**: `padding-block` (no reflow; never an inline-flex 44px block or an overlay
  that swallows adjacent-word taps).
Touch-width only, so desktop hover is untouched. The `visual_qa` tap-target audit (#1013) reports
violations (advisory).

### 10.5 Type registers at mobile sizes

The triad's jobs are unchanged on mobile; only the register tightens. Data tables use `--fs-small`
(14px) cells with `--fs-label` (11px, uppercase, tracked) headers — the **11px mono label** is the
smallest register that ships, and only for machine-voice labels, never body copy. Door labels drop
to `.66rem` in the app-bar (icon-over-label gives them the width to stay legible).

### 10.6 The responsive-table primitive (#1008)

One shared pattern: `.table-scroll` (tokens.css) — the block-scroll trick (`display:block;
width:100%; overflow-x:auto`), no wrapper element needed, columns stay aligned. The shared
`.rd-tbl` readout-table class inherits it at `≤820`. **Rule:** a wide data table must scroll inside
its own box (`width:100%`, never `width:auto` — `auto` lets a `display:block` table size to content
and blow out the page under real data, which auto-rolled-back a deploy on 2026-07-11) or reflow to
cards; it must never squeeze columns until headers truncate. Wide **non-table** content (stat rows,
strips) relies on the section-level `.rd-sec { overflow-x:auto }` scroll — keep it.

### 10.7 PWA layer

The Cockpit is an installable PWA: a web manifest + an active service worker (`sw.js`). SW
registration is deliberately scoped to the **cockpit-PWA island** — home (`/`), `/cockpit/`, and the
`/coaching/` shells (the daily-return loop) — and the cache VERSION is stamped with the build SHA
at deploy, with a hard-fail guard if the stamp misses (#1020; details in
`docs/SITE_AUTHORING.md` §4). A PR that changes cached assets should assume the SW may serve a
stale copy until the cache rolls (≤5 min: `sw.js` is served `max-age=300, must-revalidate`).

### 10.8 The section-TOC primitive — deep pages get in-page anchors (#1015)

One shared module for very deep pages (the labs readout is ~19 screens at 390px):
`site/assets/js/section_toc.js` + `site/assets/css/section_toc.css` (self-injected by the JS, so
generated shells need no rebuild). `mountSectionToc(scope, { content, before })` scans `content`
for `.rd-h` headings, gives each enclosing `.rd-sec`/`.gr-cat-head` a real slug id (shareable
deep links), and mounts a **top-sticky, collapsible "on this page" bar**: one tap opens the list,
one tap jumps — every major section ≤ 2 taps. Rules: shown only at ≤820 (`--bp-tw`); **top-sticky
by contract** so it can never collide with the bottom app-bar (§10.2), `z-index` kept below the
app-bar's 60; the open list is an absolute overlay (no layout shift), height-capped; toggle and
links meet the 44px floor (§10.4); anchor targets get `scroll-margin-top` so the stuck bar never
covers a jumped-to heading. `scope` must be sticky-safe (no overflow/transform ancestor between it
and the viewport — `.ev-main` and `.gr-wrap` qualify). Adopted: `/data/labs/`, `/data/character/`
(allowlisted in `evidence.js` — shallower topics keep thumb-scroll), `/gear/` (static mount from
`v4_build_gear.py`). Adding it to another deep page is one `mountSectionToc` call.
