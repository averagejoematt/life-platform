# averagejoematt.com — Holistic Site Review Methodology

> Repeatable process for reviewing the *whole* public site as a product and a story —
> not "did it render" (that's the gating `tests/visual_qa.py`), but "does each page's
> story land, does the site cohere into one throughline, and does the data corroborate
> and tell the right story." Runs as a human-in-the-loop pass in Claude Code via the
> `/site-review` skill (Claude Code sees the screenshots directly).
> First review: 2026-06-20. Cadence: weekly through the first 3 months, then monthly.
> Findings stored in `docs/site-reviews/`. Tooling: `tests/site_review.py` (capture +
> data corroboration), `tests/site_review_bindings.py` (page→endpoint map).

---

## ⚠️ What this review is — and is not

**This is internal self-assessment by Claude against a rubric the platform authored**
(the V4 Design Constitution + the Product Board's standing questions). It measures
*conformance to the site's own stated intent* — not external quality, not market
validation, not "an A from real users." It is a useful internal QA signal and a
work-order generator; it is **not** a substitute for the one thing that actually
validates a product: real members of the target audience using it cold. The standing
recommendation is to periodically put the site in front of an actual stranger and an
actual friend and watch. Treat every verdict here as "passes our own bar," never as
"validated." Reproduce this caveat at the top of every review document.

---

## The grounding (what "good" is measured against)

### North star (the tiebreaker above all — Constitution §0)
> **An honest living documentary of an ordinary life rebuilt with AI — the anti-Blueprint.**

### Audience hierarchy (Constitution §1) — the decisive tiebreaker
1. **Spine = Matthew, daily.** The site is a tool he opens every day; everything else is a *view onto* that tool.
2. **The circle** (partner, a few friends) who check in frequently.
3. **The discoverer** — a stranger who lands or is sent the link.

When "best for me daily" collides with "legible to a stranger," **me-daily wins.** Success is *recurring value*, not viral reach, not first-impression wow.

### The three doors (Constitution §3, ADR-071)
| Door | Path | The one question it answers |
|------|------|------------------------------|
| **Cockpit** | `/now/` | "Am I winning, and what's the one thing right now?" (the daily tool) |
| **Story** | `/story/` | "What's the honest arc of this transformation?" (the writing hub) |
| **Evidence** | `/evidence/` | "What's the protocol, what's it built on, does the data hold up?" (the archive) |
| Home | `/` | the cinematic hook into the above |

### The moat (Constitution §7) — protect these, they're why a $300 ring can't reproduce it
1. **The interpretation layer** — named characters who argue about Matthew, Elena's weekly story, the Third Wall. The *soul*, not a feature.
2. **Honesty as design** — down weeks, relapses, pauses are *shown and narrated*, not hidden. Visible setbacks make the N=1 more credible, not less.
3. **Radical accessibility** — "you could do this," built with Claude + consumer wearables, not a million-dollar lab.
4. **The gamified character layer** — levels/tiers/pillars as the human-friendly synthesis.

### Editorial guardrails (Constitution §11) — privacy lines that override everything
No employer/industry/role specifics · partner never named · the two vice categories never named · bereavement out unless opted in · chest-tightness paired with cardiovascular bloodwork framing only · escapism stays metaphorical. Honesty about the *journey* is required; it never means disclosing these. **A guardrail breach is always a `critical` finding.**

---

## The lenses (the Product Board — `docs/BOARDS.md` §3)

Each page is read through these standing questions. Findings are tagged with the lens that surfaced them.

| Lens (persona) | Standing question | What it catches |
|----------------|-------------------|-----------------|
| **Mara Chen** — UX/IA | "Can someone use this without instructions?" | navigation, hierarchy, mobile flow, accessibility |
| **Tyrell Washington** — design/brand | "Does this look and feel world-class?" | visual polish, type, design-system consistency, dark mode, responsive |
| **Sofia Herrera** — CMO | "Would someone share this? Would they pay for it?" | positioning, messaging, shareability, monetization signal |
| **Raj Mehta** — product | "Does this move the needle on the metric that matters?" | feature value, engagement loops, retention |
| **Jordan Kim** — growth | "Will this get shared? Will this convert?" | SEO, onboarding, the discoverer's first 10 seconds |
| **Ava Moreau** — content | "What's the content engine that runs without Matthew?" | narrative format, repurposing, the Elena pipeline |
| **Dr. Lena Johansson** — science | "Is this scientifically defensible?" | claims, evidence framing, N=1 honesty |
| **James Okafor** — CTO | "Can we build/keep this without breaking what exists?" | feasibility of proposed fixes (read-only engine, `/api/*` contracts) |

**When lenses disagree** (the designed tension pairs — Mara↔Raj, Sofia↔Lena, James↔Tyrell, Jordan↔Ava), the tiebreaker is the **throughline**: *does this help a visitor connect the story from any page to any other page?* If yes → ship. If no → backlog. Above that sits the north star (§0) and the audience hierarchy (§1).

---

## How to run

### Step 1 — Capture (build the packet)
```bash
python3 tests/site_review.py                # full site → qa-screenshots/<today>/
python3 tests/site_review.py --door story   # one door (the weekly-cadence default)
python3 tests/site_review.py --page /now/    # single-page deep dive
python3 tests/site_review.py --from-report qa-screenshots   # augment a CI capture instead of re-shooting
```
Produces `qa-screenshots/<date>/`: screenshots (full + mobile + chart crops), `api/*.json` (the data each page is built from), `consistency.json` (cross-page metric agreement), `manifest.json` (the index), and an `annotations/` drop-zone.

### Step 2 — (optional) Point at specifics
Drop marked-up screenshots into `qa-screenshots/<date>/annotations/`, named `<slug>-<label>.png` (e.g. `now-font.png`). The skill reads them and treats your markup as **directed, top-priority** findings — this is how you "show exactly what you mean."

### Step 3 — Review (the `/site-review` skill, in Claude Code)
`/site-review review <date>` (defaults to the latest packet, one door per run for the weekly cadence). Claude reads `manifest.json` + `consistency.json` + this doc + the constitution, then walks the pages in `narrative_order`, **reading each screenshot**, and for every page asks:
1. **What is this page trying to say** — for Matt-daily, the circle, the discoverer, commercialization. Does it land? (the audience-hierarchy + Sofia/Raj lenses)
2. **Visual / type / IA** — Tyrell + Mara lenses; restraint-reads-as-credibility; mobile parity.
3. **Narrative / throughline** — Ava lens + the §0 archetype; does this page advance the one story.
4. **Data integrity** — compare each rendered number on the screenshot to that page's captured `api/*.json`; fold in the cross-page `consistency.json` disagreements; flag NaN/undefined, stale dates, unit slips, guardrail breaches.

It maintains a running **story spine** ("after this page, what does the visitor now believe / feel?") and flags any page that breaks or drops the arc.

### Step 4 — Work order
The skill writes `docs/site-reviews/SITE_REVIEW_<date>.md` and a top-10 prioritized work order. Each finding cites its evidence (a screenshot and/or an `api/*.json` file) — no finding without an artifact.

---

## Findings schema

```
| ID | Page | Category | Severity | Lens | Finding | Evidence | Fix | Effort |
```
- **Category**: `visual | font | ia | narrative | data`
- **Severity**: `critical | high | medium | low` (a guardrail breach or a cross-page data disagreement is always ≥ high; a guardrail breach is `critical`)
- **Lens**: the Product Board persona (or `consistency` for a deterministic cross-page mismatch, or `annotation` for a user-directed note)
- **Effort**: `S | M | L`
- **Evidence**: the screenshot filename and/or `api/*.json` path the finding is grounded in

The doc leads with the **story spine** and a one-line **throughline verdict** (`COHERES` | `BREAKS AT <page>`), then the top-10 work order, then the full findings table.

---

## Data corroboration — three layers

1. **Rendered vs source** (per page, in the skill): does the number on the screenshot equal the value in that page's captured `api/*.json`? Catches render/format bugs.
2. **Cross-page consistency** (deterministic, in `site_review.py`): the same canonical metric pulled from ≥2 endpoints must agree within tolerance (weight ≤0.1 lb; level/day-count exact; ratios ≤0.5pp). Catches "weight = 305 on Home but 306 on Cockpit." Tracked metrics + tolerances live in `tests/site_review_bindings.py::METRIC_TOLERANCE`.
3. **Right story** (judgement, in the skill): beyond exact-match — is the number *framed honestly* (anti-Blueprint, setbacks shown), in the right unit, with enough context to inform rather than mislead?

The binding map (`tests/site_review_bindings.py`) is the single source of truth for which endpoints back which page; its evidence half is generated from `scripts/v4_build_evidence.py::REGISTRY` so it can't drift. Add a new page or rename an endpoint and the binding self-check fails loudly.

---

## Cadence & scope

- **Weekly** for the first 3 months (high-change period), then **monthly**.
- **One door per weekly run** (Cockpit / Story / Evidence) keeps each session focused and within Claude Code's image-context budget; rotate doors week to week.
- **Full-site pass** before launching any new door or major surface, and at each monthly review.
- Phase 2 (designed, deferred): an automated budget-gated vision panel runs the Product Board over the captured screenshots weekly and emails a ranked digest, seeding the human run. See the plan in `handovers/`.
