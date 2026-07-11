# averagejoematt.com v4 — Claude Design Brief

**From:** Product Board (Tyrell Washington, design lead · Mara Chen, UX lead)
**Source of truth:** `V4_DESIGN_CONSTITUTION_2026_06_01.md` — read it first; this brief never overrides it.
**For:** Claude Design (visual system + interactive prototypes)
**Date:** 2026-06-01

---

## 1. The feel (the visual translation of the name)

The name *Average Joe Matt* is the visual guardrail. The site must look **honest-but-crafted**: clearly made with care, never slick. If a screen could plausibly belong to a supplement brand or a biohacking guru, it has failed.

- **Restraint reads as credibility.** Calm, editorial, lots of negative space. No dopamine-neon, no hype gradients, no hero-stat theatre.
- **Dark-mode-first**, with a real light mode (both must be first-class).
- **Editorial, not dashboard-y.** Type does real work. The site should feel closer to a well-designed longform publication that happens to be backed by live data than to a fitness app.
- **Motion earns its weight.** Used to reveal and to narrate (the Story), never as decoration.
- **Mobile-first for the Cockpit** (the daily glance happens on a phone); the Story and Evidence can be richer on desktop.
- **Do not echo WHOOP/Oura's dashboard look** — it undercuts the authenticity wedge and is being litigated. Borrow the *principle* (one number that answers the question), not the visual language.

---

## 2. Design tokens (a concrete starting direction, not a locked identity)

Claude Design should treat these as the opening position and refine.

- **Palette:** near-black canvas (not pure #000), warm off-white text, a quiet neutral ramp for surfaces. **One** restrained accent used sparingly to mark "this is the live signal." Pillar domains may carry muted category tints (Body / Mind), kept low-saturation so the page stays calm.
- **Typography:** an editorial display face for headings and the Story; a clean, neutral sans for UI; a mono for raw data/figures. Two weights in UI. Sentence case everywhere.
- **Layout:** **bento grid** — modular tiles of varying size, each a self-contained story (a stat, a verdict, a trend). This is the explicit replacement for the old flat equal-weight tile grid. Use CSS Grid/Subgrid; generous gutters; clear visual rhythm.
- **Shape & depth:** soft radii, flat surfaces, hairline borders. Glassmorphism only as a rare accent, never the language.
- **Honesty markers:** define a *visual vocabulary for down periods and pauses* — a muted, dignified treatment (not red-alert, not hidden) that says "this dipped, here's the context." This is a first-class design element, not an edge case.

---

## 3. Door 1 — The Cockpit (daily, Matthew)

**Job (acceptance test):** in one glance, *"Am I winning, and what's the one thing right now?"*

Required modules on the glance (bento):
- **The hub:** Character Level + tier, with today's movement. The single largest, calmest element.
- **The Chair's verdict:** the delivered cross-pillar synthesis — one sentence naming the one thing. This is what stops Matthew synthesising by hand. Surfaced from the existing digest computation.
- **Two domains:** **Body** (Movement, Nutrition, Sleep, Metabolic) and **Mind** (Mind, Relationships), each a tile showing the domain rollup with its pillars reachable inside.
- **Consistency band:** a cross-cutting discipline strip, not a peer tile.
- **A board one-liner:** a named persona's read on today/this week (the interpretation layer, made glanceable).
- **Time-scope control:** one global Today · Week · Month · Journey toggle that re-scopes everything.

**The disclosure interaction (non-negotiable):** picking a pillar opens its detail **in place** (no navigation away), and moving between the seven is a **lateral swap** on the same surface. A pillar view answers *"why it's here, where it's heading, what to do"* — score + trend + driving components + the relevant persona's read + one action.

**Prototype BOTH candidate patterns; do not pre-decide:**
- **A — Focus model (Mara):** one pillar in focus at a time, the rest collapsed but one tap away. Findability via focus + fast lateral movement. Lower risk; mobile-native.
- **B — Relational canvas (Tyrell):** a single canvas where pillar relationships are *drawn* (e.g. sleep → recovery → training), so synthesis is partly visual. Higher ceiling; higher risk of becoming the next over-busy UX.

Test both against the job above. The winner is the one where a returning Matthew gets "am I winning + the one thing" faster, and detail never costs a page.

---

## 4. Door 2 — The Story (the default door for anyone who discovers or is sent the link)

**Job:** *"What's the honest arc of this transformation?"* — and leave the visitor wanting to follow.

- **Scrollytelling:** the journey unfolds as you scroll — the climb, and the down weeks shown honestly (the honesty markers from §2). Data appears as *texture* in the narrative, not as a dashboard dropped into prose.
- **The interpretation layer is the cast:** Elena's chronicle is the narrative spine; the Third Wall (AI says vs how Matthew actually felt) is woven in as the emotional turn, not buried. These are characters, treat them with editorial weight.
- **The share artifact:** a clean, linkable Story is the thing a friend forwards ("you should see what he's doing with Claude"). One quiet follow/subscribe affordance — present, never pushy.
- **Reachability is the tone:** the takeaway must be "an ordinary person did this with tools I already own," never "look how superhuman."

---

## 5. Door 3 — The Evidence (skeptic + would-be-copier)

**Job:** *"What's the protocol, what's it built on, does the data hold up?"*

- The depth Matthew didn't want to lose: protocols, supplements (with *what* and *why* and *what's actually backed*), habits, biomarkers, and experiments **read-only** (his N=1 instrument exposed as proof; reader participation deferred, architected to switch on later).
- **Aesthetic:** an "archival index" treatment — structured, labelled, library-meets-gallery. Calm, credible, browsable. This is where rigor is performed visually.
- **Correlative framing in all copy** (Henning standard): never assert causation; flag thin data as preliminary.

---

## 6. Cross-cutting

- **The interpretation layer** (board personas, Elena, Third Wall) is the soul — give the persona voices a consistent, characterful visual identity across all three doors.
- **Accessibility:** WCAG AA minimum, full keyboard path, reduced-motion honoured (all scrollytelling has a static fallback).
- **Performance / sustainability:** vector over heavy assets; motion that doesn't earn its weight gets cut. The site should feel fast and light, which also reads as craft.
- **One engine, three doors:** the doors are presentation; they all read the existing data + AI engine. No new data model is implied by this brief.

---

## 7. What to hand Claude Design (deliverables)

1. A design-token sheet (palette, type scale, grid, motion principles) in both modes.
2. **Cockpit, Pattern A (focus)** and **Pattern B (relational canvas)** — interactive prototypes, tested against the §3 job.
3. The Story hero scroll sequence (the first screen-and-a-half of the scrollytelling arc, including one honest down-beat).
4. The Evidence index treatment (one representative depth page, e.g. supplements with the what/why/backed structure).

When the two Cockpit prototypes are in hand and one is chosen, this brief plus that choice compiles into the Claude Code build instruction.
