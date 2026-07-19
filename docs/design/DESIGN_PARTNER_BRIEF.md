# DESIGN_PARTNER_BRIEF — the design-session contract

> **Status:** canonical · **Owner:** Matthew · **Written:** 2026-07-19 (#1464)
>
> This file travels with the design system: `/design-sync` (#1463) pushes it into the
> "AverageJoeMatt Design System v5" design project as project-root **`BRIEF.md`**, so
> every Claude Design session — or any outside designer — opens on the rules. It is the
> contract that makes **"Design proposes, only Code ships"** enforceable (ADR-106 stance,
> extended from portraits to every design surface).
>
> Sources of truth this distills (read them for depth, never contradict them):
> `docs/PLATFORM_NORTH_STAR.md` · `docs/DESIGN_SYSTEM_V5.md` · `docs/SITE_MAP_AND_INTENT.md`.

---

## 1. What you are designing for (the north star, distilled)

`averagejoematt.com` is an **honest, living documentary** of one ordinary person rebuilding
his health with consumer wearables, his own data, and AI coaching — N=1, in public, down
weeks shown. **Proof, not promises.** The anti-Blueprint. Weight is the first falsifiable
instrument reading, never the meaning; the goal underneath is life satisfaction.

**The one causal loop** — every page is a station on it, and every proposal must protect it:

```
THE DATA ──reads──▶ THE COACHING ──proposes──▶ THE PROTOCOLS ──shifts──▶ (the data)
                        ▲                                        │
                        └──────────── THE STORY narrates it ◀────┘
COCKPIT = today's slice of the loop · HOME = teaches the loop in one screen, then routes in
```

The rule that kills "scattered": **every page's first screen answers "which part of the
loop am I, and what do I give you?"**

**Four audiences, design for all of them:** Reddit newcomers (get the loop in one screen,
then hook them), Matthew himself (a daily instrument — returnability), friends & family
(the story: is he okay, is it working), quantified-self skeptics (depth, methods,
failures shown honestly).

**The success bar:** coherent (one package, the loop everywhere) · honest (misses and down
weeks are content, not bugs) · alive (motion, exploration) · credible to a skeptic
(correlative-only, n and confidence visible) · legible to a newcomer. Elite ≠ shiny —
the aesthetic is a **beautifully-made instrument**, the opposite of AI-template gloss.

## 2. Hard constraints (violations are an automatic revision round)

1. **Tokens only.** Every colour, font, radius, spacing, shadow comes from the synced
   `tokens.css`. No hardcoded values; propose new tokens explicitly (see §4).
2. **The triad only, fixed jobs.** Fraunces = the human voice. Instrument Sans = the
   interface. IBM Plex Mono = the machine voice & data (tabular-nums). No fourth face.
3. **Earned glow.** One ember accent means "alive / up." Glow and warm bloom appear ONLY
   on truly-live signals. A neutral number gets depth, not glow. If it would read as
   "AI-template gloss," it's wrong — restraint is the credibility moat.
4. **Never red for direction.** Down/flat = muted ink. `--alert` (oxblood) is reserved for
   out-of-range vitals state only.
5. **Six canonical breakpoints, nothing else:** 360 / 480 / 600 / 760 / 820 / 900
   (`--bp-xs/sm/md/lg/tw/xl`, documented constants — CSS vars can't enter `@media`).
   Pick by job, not pixel-taste; a seventh value fails CI.
6. **Motion fails OPEN and is reduced-motion-aware.** Motion may never hide content;
   interaction (chart focus, tooltips) is welcome even under reduced-motion. Every
   animation needs a reason tied to the loop or a live signal.
7. **Uncertainty is drawn honestly** (the confidence grammar, ADR-105): real intervals get
   bands, LOW confidence gets a point — never a fabricated spread to look sophisticated.
8. **No emoji, no stock imagery, no photoreal people on data surfaces.** Marks derive from
   the sigil/instrument vocabulary (`icons.js`, `sigils.js`, generative marks) or from
   real data. Portraits follow ADR-106/PORTRAIT_RUNBOOK exclusively.
9. **Light AND dark are both first-class.** AA contrast both ways; design both, always.
10. **Privacy absolutes.** Never name substances/vices, never expose genome identifiers or
    chronological age, nothing Matthew-private on a public surface.

## 3. The Slop Litmus v1 (run every proposal through all ten)

A proposal that fails any point goes back for a revision round — cite the point number.

1. **The masthead test.** Cover the wordmark. Is the screen still identifiable as THIS
   site (the loop, the triad's voices, the instrument vocabulary) — or could it be any
   AI-generated health dashboard?
2. **No purple-blue gradient, no glassmorphism, no generic shadcn geometry.** The 2024–26
   template look is an automatic fail.
3. **Every decorative mark earns its existence** — derived from the sigil/instrument
   vocabulary or drawn from real data. Ornament with no data behind it is slop.
4. **Glow audit.** Point at each glow/bloom: which live signal earns it? No answer = strip it.
5. **Typography leads with the triad's voices** — a Fraunces human line, Instrument Sans
   chrome, Plex Mono numbers. A center-aligned hero + three-card grid is the slop
   silhouette; if the layout could be a SaaS landing template, restructure.
6. **Motion has a reason.** Name the loop station or live signal each animation serves.
   "It feels dynamic" is not a reason.
7. **Uncertainty honest?** Any band, range, or error visual must map to a real computed
   interval; LOW confidence renders as a point.
8. **Copy in the site's voice.** Plain, specific, honest — "the sheet grades itself
   against how the week felt," never "Unlock your journey" SaaS-speak. Numbers cited,
   hedges kept.
9. **Both themes designed** — not one theme plus an inversion. Check ember/ink balance in
   each.
10. **The loop is findable.** From the proposed screen, can a newcomer tell which loop
    station they're on and where the loop-forward door is?

## 4. The deliverable contract (`proposals/<slug>/`)

Every design-session output lands in the design project under `proposals/<slug>/`:

- **Plain HTML/CSS on the synced tokens** — files reference the project's `assets/`
  copies by relative path; no CDNs, no frameworks, no absolute site URLs.
- **`NOTES.md`** — intent, the Slop-Litmus self-audit (all ten points, one line each),
  which pages/components it touches, and any open questions for the taste-pause.
- **`token-deltas.css`** — REQUIRED whenever the proposal wants a token that doesn't
  exist: the proposed custom properties with a one-line justification each. New tokens
  are a proposal, never a fait accompli; Code decides whether they enter `tokens.css`.
- Variations welcome (2–3 is the norm for identity-level changes — the frontpage-rework
  precedent); label them `v1/v2/v3` inside the slug.

## 5. The posture (non-negotiable)

**Design proposes. Only Code ships. Only Matthew approves identity-level changes.**
A design session never edits `site/` — its output is consumed by `/design-implement`
(#1465), which re-expresses the chosen proposal through the site's conventions (builders,
tokens, motion wiring, QA registries) in a worktree PR, with render-QA at 1280+390 and
the performance budget green. Taste-level swings (home first screen, palette shifts,
new art layers) wait for Matthew's pick from rendered screenshots — the taste-pause —
before implementation. This mirrors ADR-106: AI may sketch; the shipped artifact is code.
