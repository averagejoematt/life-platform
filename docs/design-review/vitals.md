# Design review — VITALS page (paste whole into your claude.ai Project; attach screenshots)

You are running an elite, page-specific design review for ONE page of my personal
health-transformation website, **averagejoematt.com**. Work in two stages.

## STAGE 1 — Assemble the room (do this first)
Design the IDEAL panel for THIS page's domain (**longevity / physiology / quantified-self
dashboards / wearable-data interpretation**). Name 4–6 world-class specialists (think: a
longevity/preventive-medicine physician, an HRV & autonomic-nervous-system researcher, a
quantified-self pioneer who's designed beautiful personal dashboards, a wearable-data scientist),
**plus a data-viz designer**. Justify each pick for THIS page; one-line intros.

## PLATFORM CONTEXT (every idea must live inside this)
Honest, ongoing **documentary of an ordinary person rebuilt with AI — "anti-Blueprint."** Cut
started **2026-06-14**; ~1 week of data; thin data shown honestly is on-brand. Audience: **me daily
→ a few who know me → a stranger**; me-first but legible. Honesty is the brand. n=1,
correlation-not-cause, **no Pearson coefficients until ~2+ weeks**.

## DESIGN SYSTEM (elevate within it — don't replace it)
**Fraunces** headings; **IBM Plex Mono** data; **ONE ember accent `#DD7A37`** (down = muted ink,
never red); restrained, data-forward, dark AND light. Chart kit: line (goal line; refuses <4 pts),
bar, stacked-composition bar, sparkline, correlation chip. Protect the measuring-rule spine + the
two-voice dialogue.

## THE PAGE + ITS REAL DATA (ground every idea here — flag anything needing data I don't capture)
**Page:** `/evidence/vitals/` (`/api/pulse` + `/api/pulse_history`) — "today's read, in context."
**Data right now (8/8 days populated):**
- Daily trends: **recovery %** (49→95), **HRV** (33.9→51.1, trending up), **RHR** (65→55, trending
  down), **strain**, **weight**, **steps** — all now chartable.
- Also on record daily: **SpO₂** (~94–96), **skin temperature**, **respiratory rate** (~13).
- A **temporal frame** the page already respects: recovery/HRV/RHR are about LAST NIGHT (they set
  today up); weight + steps are same-day — labeled so a reader doesn't misread last night's
  recovery as a "today" number.
- A daily narrative + "signals reporting" count.
**Currently rendered:** today's pulse narrative, then trend charts grouped by frame —
"Last night → sets up today" (recovery, HRV, RHR, sleep hours) and "Today — measured same-day"
(weight, strain, steps).
**Screenshots:** attached (full desktop scroll + mobile; light/dark if it differs).

## STAGE 2 — The review (after assembling + introducing the panel)
Panel reacts in their own voices, disagreeing where they would, and delivers:
1. **The one story** this page should tell that it currently doesn't (e.g. "the autonomic system
   recovering as the load comes off" — RHR↓ + HRV↑ together).
2. **Specialist visuals** — concrete; chart type + exact fields. (Push past, don't copy: an
   HRV↑/RHR↓ "recovery" dual-axis; an autonomic balance (FLOW/STRESS/RECOVERY/BURNOUT) quadrant
   from strain-vs-recovery; a single composite "readiness" gauge with component breakdown; a
   small-multiples grid of all daily series.)
3. **Features / interactions** that level it up.
4. **What to cut.**
5. **What's missing** I should capture (BP cuff? VO₂max? continuous HR?).
Rank by impact. Honor the design system + honesty + me-first. Mark **buildable now** vs **needs more
weeks** (week one — ~7–8 points each).
