# Design review — SLEEP page (paste whole into your claude.ai Project; attach screenshots)

You are running an elite, page-specific design review for ONE page of my personal
health-transformation website, **averagejoematt.com**. Work in two stages.

## STAGE 1 — Assemble the room (do this first)
Design the IDEAL panel for THIS page's domain (**sleep medicine + circadian biology +
thermoregulation/sleep-environment**). Name 4–6 world-class specialists (think: a sleep-medicine
MD/researcher, a circadian-rhythm scientist, a sleep-tech/thermoregulation specialist who knows
Whoop & Eight Sleep intimately, a recovery/HRV physiologist), **plus a data-viz designer**.
Justify each pick for THIS page; one-line intros. Tailor hard — nothing like the nutrition/fitness panels.

## PLATFORM CONTEXT (every idea must live inside this)
An honest, ongoing **documentary of an ordinary person rebuilding his health with AI — the
"anti-Blueprint."** Cut started **2026-06-14**; ~1 week of data; thin data shown honestly is
on-brand. Audience: **me daily → a few who know me → a stranger**; me-first but legible. Honesty is
the brand (down nights shown, never superhuman/guru/clinical). n=1, correlation-not-cause, **no
Pearson coefficients until ~2+ weeks**.

## DESIGN SYSTEM (elevate within it — don't replace it)
**Fraunces** headings; **IBM Plex Mono** data; **ONE ember accent `#DD7A37`** (down = muted ink,
never red); restrained, data-forward, dark AND light. Chart kit: line (goal line; refuses <4 pts),
bar, stacked-composition bar, sparkline, correlation chip. Protect the measuring-rule spine + the
two-voice dialogue.

## THE PAGE + ITS REAL DATA (ground every idea here — flag anything needing data I don't capture)
**Page:** `/evidence/sleep/` — "last night, and what tonight should be."
**Data (`/api/sleep_detail` + `/api/circadian` + `/api/sleep_reconciliation`) right now:**
- Nightly **sleep score** (sanity-gated), **hours**, **efficiency %**, **recovery**, **HRV**, **RHR** — keyed to LAST NIGHT (sets up today).
- **Sleep stages in hours** — deep / REM / light — from **BOTH Whoop and Eight Sleep** (dual-device).
- **Bed temp / room temp** (Eight Sleep), sleep onset / midpoint / consistency, WASO, time-to-sleep.
- **Circadian-compliance forecast** — a *predictive* 0–100 score from today's behaviors across four anchors ("tonight's sleep is at risk → act now"), DST-aware.
- **Cross-wearable unified sleep record** (Whoop + Eight Sleep + Apple reconciled).
- Nightly **sleep-score trend** (~7 pts).
**Currently rendered:** last-night figures, a new last-night stage stacked bar (deep/REM/light),
a stages & physiology table (quality, bed temp), the nightly sleep-score trend, and the circadian
forecast tile.
**Screenshots:** attached (full desktop scroll + mobile; light/dark if it differs).

## STAGE 2 — The review (after assembling + introducing the panel)
Panel reacts in their own voices, disagreeing where they would, and delivers:
1. **The one story** this page should tell that it currently doesn't.
2. **Specialist visuals** — concrete; chart type + exact fields. (Push past, don't copy:
   stage-composition stacked over the week; a bedtime/wake consistency scatter + social-jet-lag
   readout; bed-temp vs deep-sleep; Whoop-vs-Eight-Sleep agreement; the circadian forecast as a
   "tonight's odds" gauge with the four anchors.)
3. **Features / interactions** that level it up.
4. **What to cut.**
5. **What's missing** I should capture (a sleep diary? caffeine/alcohol timing? light exposure?).
Rank by impact. Honor the design system + honesty + me-first. Mark **buildable now** vs **needs more
weeks** (week one — ~7 nights).
