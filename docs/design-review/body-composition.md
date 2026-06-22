# Design review — BODY-COMPOSITION page (paste whole into your claude.ai Project; attach screenshots)

You are running an elite, page-specific design review for ONE page of my personal
health-transformation website, **averagejoematt.com**. Work in two stages.

## STAGE 1 — Assemble the room (do this first)
Design the IDEAL panel for THIS page's domain (**body composition / DEXA interpretation / metabolic
& musculoskeletal health**). Name 4–6 world-class specialists (think: a body-composition scientist
who lives in DEXA data, a sports-medicine/physique physician, a metabolic-health researcher, a
longevity doc focused on lean mass + visceral fat), **plus a data-viz designer**. Justify each pick
for THIS page; one-line intros.

## PLATFORM CONTEXT (every idea must live inside this)
Honest, ongoing **documentary of an ordinary person rebuilt with AI — "anti-Blueprint."** Cut
started **2026-06-14**. Audience: **me daily → a few who know me → a stranger**; me-first but
legible. Honesty is the brand. n=1, correlation-not-cause.

## DESIGN SYSTEM (elevate within it — don't replace it)
**Fraunces** headings; **IBM Plex Mono** data; **ONE ember accent `#DD7A37`** (down = muted ink,
never red); restrained, data-forward, dark AND light. Chart kit: line (goal line; refuses <4 pts),
bar, stacked-composition bar, sparkline, correlation chip. There's also an existing **faceless body
silhouette whose girth is a pure function of the real weight** (a "data figure"). Protect the
measuring-rule spine + the two-voice dialogue.

## THE PAGE + ITS REAL DATA (ground every idea here — flag anything needing data I don't capture)
**Page:** `/evidence/physical/` (`/api/physical_overview` + `/api/weight_progress` + `/api/journey`).
**Data right now:**
- **One DEXA scan** (2026-03-30 — **pre-genesis, ~80 days old**): body_fat_pct (~42.7%), lean_mass,
  visceral fat, ALMI / FFMI / FMI, bone density (⚠️ a **T-score reading +3.9** that looks implausible
  — flag, don't trust), segmental fat & lean, a "Body Score" + biological age.
- **Weight trajectory:** 314.5 → 304 over the cut (clean daily line), goal 185, the real slope.
- `changes_vs_baseline` (large deltas vs an older baseline — surprising; treat carefully).
- **NOT available yet:** a second DEXA (so no composition *velocity*), tape measurements (0 records this cycle).
**Currently rendered:** a weight trajectory chart, DEXA figures, and composition/indices/bone tables.
**Screenshots:** attached (full desktop scroll + mobile; light/dark if it differs).

## STAGE 2 — The review (after assembling + introducing the panel)
Panel reacts in their own voices, disagreeing where they would, and delivers:
1. **The one story** this page should tell that it currently doesn't (honest tension: the *weight*
   is moving fast, but the *composition* truth is one stale scan — how to frame that without faking
   progress).
2. **Specialist visuals** — concrete; chart type + exact fields. (Push past, don't copy: weight
   trajectory with milestone markers + the goal as an annotation (not an axis anchor that flattens
   the line); lean-vs-fat mass at-scan; a segmental silhouette; a "next DEXA" countdown that turns
   the single scan into anticipation.)
3. **Features / interactions.**
4. **What to cut** (jargon-y raw index tables?).
5. **What's missing** I should capture (cadence of DEXA? tape measurements? progress photos — with
   a privacy stance?).
Rank by impact. Honor the design system + honesty + me-first. **Most of this page is honestly
"baseline, awaiting the next scan"** — lean into that rather than over-visualizing one data point.
