# BRIEF_2026-06-29_reading_mind.md
**Design brief — The Mind Pillar (Reading) · averagejoematt.com · the measured life**
Repo path: `docs/briefs/BRIEF_2026-06-29_reading_mind.md`
Status: DRAFT for review · 2026-06-29 · harmonize with `DESIGN_SYSTEM_V5.md` / `V4_DESIGN_CONSTITUTION` (this brief feeds them; it does not reinvent the system)
Scope: design direction only. Data model, schema, build order are in the spec + Claude Code prompt.
> **Persona note (reconciled 2026-06-30):** the archetype names in this brief (Lena / Priya / Nadia / Crowe / Theo / Mara) are **superseded**. The reading coach is **Dr. Cora Vance** (`cora_vance`); counter-voices are the real roster (Coach Maya Rodriguez, Dr. Amara Patel, Mara Chen). See `docs/coaching/READING_CALIBRATION.md` §9 and `docs/BOARDS.md`. This dated brief is kept as the original build record.

---

## 0. The subject, pinned

One ordinary person using an AI machine to become a reader — and proving it by measuring what he *kept*, not what he consumed. The page's single job: make "I am becoming a reader" **tangible, honest, and his**. Audience is Matthew first (daily user), the public follower second (the proof).

**Not** a Goodreads clone, a stats dashboard, or a TBR list. It is the Mind half of a site that already promises "every source — *the body, the mind* — now and over time," and currently under-delivers the mind. This delivers it.

Design thesis in one line: **the body pillar measures what you can do; the mind pillar measures who you are becoming.**

---

## 1. Where it lives (no bolt-on)

One new page — **the Mind page** (extends the existing `SPEC_MIND_PAGE_REDESIGN_2026-06-21`) — plus a thread through every existing surface.

| Surface | What reading adds |
|---|---|
| **Seven pillars (home)** | Mind becomes a pillar, sized and ember-lit, joined by edges to Recovery / Mood (the cross-domain links are already the home page's visual grammar). |
| **The cockpit (`/now/`)** | Today's reading line: current cover, the "read today" tick, any **due recall prompt**. The daily nudge lives here. |
| **The data (`/data/`)** | The mind half, populated: roundedness wheel, difficulty ratchet, retention trend (private), streak history — "now and over time." |
| **The coaching (`/coaching/`)** | Lena Marsh joins with a stance, a track record, and a logged disagreement. Post-book debrief = a **Third Wall** instance. |
| **The protocols (`/protocols/`)** | Reading challenges, reading experiments (tested against real biometrics), discoveries. |
| **The story (`/story/`)** | Finished books become beats; reflections feed the journal; milestones hit the timeline. |
| **Results (`/method/results/`)** | "Mind composition" beside body composition — the parallel proof. |
| **Ask the data (`/method/ask/`)** | Reading becomes queryable, correlatively, confidence shown. |

---

## 2. The signature element — The Constellation

**Spend the boldness here, keep everything else quiet.**

As books are read, their *ideas* (not their covers) become nodes, and the connections between them become edges — a slowly growing, navigable graph of one mind getting more rounded. The site's whole thesis — *becoming, made visible* — rendered for the mind the way the pillar map renders the body.

- **Honest until true.** Below a meaningful node count → not a sparse sad graph, but an honest empty state: a single lit point and "the constellation begins with the first idea you keep." (Mirrors charts-refuse-under-4-points.)
- **Ember = recency/aliveness**, muted ink = settled. Never red.
- **Earned, not launched** (Mara Quinn's gate): the signature we build *toward*; the closed loop ships first. The empty state is beautiful on day one regardless.
- Motion: nodes settle with a gentle physics ease on add; hover lights edges. One orchestrated reveal, not scattered sparkle. `prefers-reduced-motion` → instant settle.

---

## 3. Token system (extends the existing system; adds no new hues)

- `--ink-void: #0E0C08` — background (existing theme color).
- `--ember` — reserved for *on-protocol / alive / toward-identity* reading behavior (read today, idea kept, streak intact, Constellation recency).
- `--ink-muted` — neutral / settled / off-pace. **A stalled book is muted ink, never red.**
- `--state-alert` (red) — STATE alerts only. **Reading has no red states.** A 30-day-stalled book is a gentle muted prompt, not an alarm. Hard rule.
- Cover art supplies incidental color; chrome stays disciplined so the spines carry the warmth.

**Type** — inherit display/body/utility roles. One reading-specific move: **the reader's own words (takeaway, synthesis) are set in the display face, larger, as pull-quotes** — the loudest type on the finished-book view, above metadata. The page's personality is *his sentences*.

**Layout** — two registers, deliberately: **shelf = warm** (tactile, dimensional spines, no skeuomorphic kitsch); **instrument = cool** (precise, quiet data view).

**Signature** — the Constellation (§2).

---

## 4. The shelf (identity surface)

- A real wall of spines/covers — makes "I am a reader" physical in a way a list never is.
- Covers fetched on add (Open Library → Google Books fallback), cached to S3, key on `BOOK#`. Coverage gaps guaranteed.
- **Missing-cover placeholder is *designed*, not broken:** a generated spine in the house palette with title + author in the display face. The empty state of one book honors the same honesty as the empty state of a chart.
- States as a quiet machine: `want → reading → finished | abandoned`. **Abandoning is first-class and dignified** — a "set down" shelf, not a failure bin. The reason is captured (the engine needs it); the UI never scolds.

---

## 5. The post-book Third Wall (the loop, made visible)

Renders on the existing Third Wall pattern: **Lena hoped ↔ how it hit.**

- **Two clocks, never merged.** The *debrief* (immediate, warm, produces the public takeaway) is reaction. The *probes* (spaced, weeks later, EventBridge) are retention. The UI keeps them visually distinct so "I remember yesterday's book" is never mistaken for "I retain."
- **Prediction reckoning.** Lena's logged prediction/hope sits beside his lived reaction; the gap is the most interesting — and most honest — thing on the view. Resolutions feed her public track record.
- **Voice debrief (backlog):** the debrief as a spoken conversation, transcribed then distilled. Gated behind the text loop working.

---

## 6. Public / private split (architectural, not cosmetic)

- **Public** = currently-reading, finished shelf, takeaways/synthesis, input streak, Constellation. Inspiring, accountable, Tom-visible.
- **Private** = retention score, probe performance, the cognitive-reserve/longevity framing, the mind-body correlations. **Hidden by default, his toggle, his eyes.** A bad retention week is never public.
- Retention measures **gist + changed-prior, never verbatim**, and is **n-gated** (no score until enough probes mean anything — Henning's refuse-to-render, applied to the thing he's most anxious about). The interview *is* the intervention; the UI should feel like care, not a test.

---

## 7. Anti-black-box (every recommendation explains itself)

No opaque "readers also enjoyed." Every recommendation carries a **reason string** decomposed to its inputs:

> *Recommended because — your journal's been heavy this fortnight (restoration), it's short enough for a deficit week (capacity), and fiction is your thinnest slice (breadth). Passing over the dense one I'm saving for a GREEN week.*

Confidence labeled and honest while `n` is small. The reason string is a first-class design element — it is *how trust is earned on the page.*

---

## 8. Copy voice

- Plain, active, sentence case. The interface's own voice, never a person's apology.
- Empty states are invitations: *"the constellation begins with the first idea you keep."* / *"nothing on the shelf yet — the first book is the whole point."*
- Reading spoken of as **pleasure and becoming** (Priya's register), never a KPI to grind (the longevity framing stays on the private instrument). The daily nudge never says "you're behind."
- A stalled book, gently and specifically: *"Klara's been waiting three weeks — pick it back up, or set it down honestly. Both are fine."*

---

## 9. Quality floor (un-announced, non-negotiable)

Responsive to mobile (he authors at night, often on phone). Visible keyboard focus. Reduced-motion respected (Constellation settles instantly, no physics). The shelf degrades to a clean list on narrow viewports without losing the cover identity. Honest empty states everywhere by default. Meets `A11Y_BASELINE.md`.

---

## 10. Successors (separate artifacts)

- `docs/coaching/READING_CALIBRATION.md` — priors, difficulty model, periodization, re-rank triggers, Lena's mandate + standing disagreements.
- `docs/SPEC_READING_MIND_2026-06-29.md` — entities, schema, GSIs, recommender objective, journal-resonance, mind-body hooks, public/private enforcement.
- `docs/specs/CLAUDE_CODE_PROMPT_READING_MIND_v1.md` — phased build + paste-ready Phase A prompt.

This brief sets the *look, feel, and rules*. It does not set the data model or build order.

---

*Boldness spent once (the Constellation). Red reserved for nothing here. The reader's own words are the loudest type on the page. The body pillar measures what he can do; this one measures who he is becoming.*
*Panel (Lena, Priya, Crowe, Nadia, Theo, Mara) are archetypes — reconcile against `docs/BOARDS.md` before they surface on the coaching page.*
