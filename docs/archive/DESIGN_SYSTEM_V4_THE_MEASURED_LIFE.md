# Design System — averagejoematt v4 — "The Measured Life" (Direction 05)

**Status:** Locked (board unanimous, 2026-06-01) · **Visual reference:** `v4_art_direction_05_the_measured_life.html`
**Feeds:** `assets/css/tokens.css` and the whole front-end build. Read alongside the Design Brief and Build Instruction.

The concept: **a measured life rendered as a beautifully made instrument log kept by a real person.** Warm, crafted, honest — the deliberate opposite of clinical biohacking gloss, and the deliberate opposite of generic AI-template aesthetics.

---

## 1. The two signatures (the ownable ideas — protect these)

These are why the site can't be mistaken for a template or guessed as AI-built. A style can be copied; a concept can't.

1. **The measuring-rule spine.** A tick-marked rule runs as a structural element — the "measured life" made literal. It anchors the Cockpit edge, segments the Story timeline, and indexes the Evidence. It is the connective tissue across all three doors.
2. **The two-voice dialogue.** The machine voice (mono) and the human voice (serif) are set in literal conversation on the page — this is the Third Wall (AI-says vs how Matthew felt) turned into the type system itself. It is the single most distinctive, on-brand device on the site.

Discipline rule (per the consultants): the signatures appear with intent, not everywhere. Don't let them metastasize onto every element.

---

## 2. Palette

Dark-mode-first; a real Daybook-informed light mode. Express these in OKLCH with `color-mix()` for tints.

**Dark (primary)**
- page `#0E0C08` · surface/paper `#16130E`
- ink `#ECE3D2` · ink-muted `#A99F8C` · ink-faint `#6B6253`
- rule `rgba(236,227,210,0.12)` · tick `rgba(236,227,210,0.28)`
- **live signal (ember)** `#DD7A37` — the one accent; used sparingly for "this is alive / this is up"

**Light (Daybook-informed)**
- paper `#F4EFE4` · surface `#FBF8F1`
- ink `#221E17` · ink-muted `#6E665A` · ink-faint `#A39A8A`
- rule `rgba(34,30,23,0.13)`
- live signal (ember, deepened for contrast) `#C2611F`

Dominant warm neutral + one sharp accent. Never an evenly-distributed rainbow. Down/flat states use the muted ink, never red.

---

## 3. Typography — the triad (each font has a job)

- **Fraunces** (variable serif, optical sizing) — **the human voice.** Headlines, narrative, the Chair's verdict, Matthew's replies, the Story. Warm, characterful.
- **Instrument Sans** — **the interface.** Everything you operate and read as UI. Calm, gets out of the way.
- **IBM Plex Mono** — **the machine & the instruments.** Every number, label, the board/AI voice, tabular data readouts. Always `tabular-nums`.

Never Inter, Roboto, system defaults, or Space Grotesk. Scale: editorial display (Fraunces, large, Story + key moments) / data display (Plex Mono, large, the score) / body (Instrument Sans) / label (Plex Mono, uppercase, tracked). Use `text-wrap: balance` on headings, `pretty` on body.

---

## 4. Per-door treatment (one system, three intensities)

- **Cockpit** — calm instrument. Logbook restraint, the rule spine, the score in big tabular mono, the two-voice dialogue for the daily verdict-and-reply. **Stays a one-second read** (Raj's condition): editorial drama is *not* here.
- **Story** — editorial scale (the Dispatch register): large expressive Fraunces, scrollytelling, and **the relational constellation as the hero visual** (the canvas from the Cockpit decision lives here, with room to breathe). This is the wow / shareable door.
- **Evidence** — archival index: structured, labelled, browsable, with a touch of instrument precision (the "Readout" influence) for dense data and biomarkers.

---

## 5. Motion & technology (2026-native — also a craft signal)

- **View Transitions API** for in-place pillar disclosure and door-to-door moves (no jarring reloads).
- **Scroll-driven animations** (`animation-timeline: scroll()/view()`) for the Story scrollytelling — native, performant, with a static `prefers-reduced-motion` fallback.
- **Variable fonts** (Fraunces optical/weight axes), **CSS Subgrid** for the bento, **container queries** for the mobile-first Cockpit, **OKLCH + color-mix()** for the palette.
- One orchestrated page-load reveal (staggered), not scattered micro-animations. Motion earns its weight or it's cut (performance = craft).

---

## 6. Honesty vocabulary (first-class, not an edge case)
Down weeks and pauses render in muted ink with a dashed hairline marker and a plain-language line — and, where it fits, Matthew's human-voice reply. Never alarm-red, never hidden. This is the moat and the anti-Blueprint anchor made visual.

---

## 7. Anti-template guardrails (so no one guesses it's AI/Claude-built)
No Inter/Roboto/system fonts. No purple-on-white gradients. No stock shadcn/SaaS cards, no uniform rounded-everything. No emoji section headers. Bespoke signatures (§1) over borrowed styles. Restraint and craft over decoration.

---

## 8. Implementation
Build `assets/css/tokens.css` from §2–§3 (both modes), then component primitives honouring §4–§6. The two reference HTMLs (`v4_art_direction_the_logbook.html`, `v4_art_direction_05_the_measured_life.html`) are the visual source of truth for spacing, weight, and feel. AA contrast in both modes; full keyboard path; reduced-motion fallback everywhere.
