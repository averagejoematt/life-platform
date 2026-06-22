# Design review — NUTRITION page (paste whole into your claude.ai Project; attach screenshots)

You are running an elite, page-specific design review for ONE page of my personal
health-transformation website, **averagejoematt.com**. Work in two stages.

## STAGE 1 — Assemble the room (do this first)
Before any critique, design the IDEAL panel for THIS page's domain (**nutrition / metabolic &
dietary science / physique-cut nutrition**). Name 4–6 world-class specialists — real-archetype
credentials — who'd give the sharpest, most *specialist* read on this exact page (think: a
metabolic-health MD who's guided many physique transformations, an RD specializing in protein
distribution and aggressive-but-safe deficits, a CGM/glucose-response researcher, a
micronutrient/longevity-nutrition scientist), **plus one data-visualization designer**
(Tufte-school — makes numbers tell a story). Briefly justify each pick: why this expert, for this
page. Tailor hard to the domain + data below; this panel should look nothing like a strength or
sleep panel. Then have them introduce themselves in one line each.

## PLATFORM CONTEXT (every idea must live inside this)
averagejoematt.com is an honest, ongoing **documentary of an ordinary person rebuilding his health
with AI — the "anti-Blueprint."** The current cut started **2026-06-14**, so most series are ~1
week (~7 daily points); thin data shown honestly ("fills in as days accrue") is **on-brand, not a
flaw**. Audience priority: **me, daily → a few people who know me → a curious stranger** — me-first
but legible + interesting to all. **Honesty is the brand:** down weeks shown not hidden, never
superhuman/guru/clinical, "you could do this" reachability. No causal claims — n=1,
correlation-not-cause, **no Pearson coefficients until ~2+ weeks** of overlapping data.

## DESIGN SYSTEM (elevate within it — don't replace it)
Serif headings (**Fraunces**) = human voice; **IBM Plex Mono** = data/machine voice; **ONE accent
— ember `#DD7A37`** = "alive / up" (down/flat = muted ink, **never red**); restrained, data-forward,
first-class **dark AND light**. Reusable zero-dep inline-SVG chart kit: line chart (optional goal
line; **honestly refuses to draw under 4 points**), bar chart, stacked-composition bar, sparkline,
correlation chip. Ownable signatures to protect: the "measuring-rule" tick spine; the two-voice
mono↔serif dialogue. Propose new visuals as additions to this language.

## THE PAGE + ITS REAL DATA (ground every idea here — flag anything needing data I don't capture)
**Page:** `/evidence/nutrition/` — "the deficit, the protein, the meal honesty."
**Data the API (`/api/nutrition_overview` + `/api/frequent_meals` + `/api/protein_sources`)
returns right now:**
- Averages: calories, protein, carbs, fat, fiber (grams); protein target + **% of days hitting it**; days logged.
- **Estimated TDEE** + **avg deficit**; 7-day vs 30-day calorie/protein momentum; latest day's calories/protein.
- **Daily macro time-series:** `[{date, calories, protein_g, carbs_g, fat_g}]` (~5–7 days).
- **weekday-vs-weekend** split; **eating-window** (avg first meal, last meal, hours — the TRF/16:8 signal); **periodization** (training-day vs rest-day calories/protein/deficit).
- **Micronutrient sufficiency:** `{nutrient → {pct, actual, target}}` (e.g. fiber 72%, magnesium 40%, potassium 25%) + a **micronutrient avg %** + a **protein-distribution (timing) score** (currently 100).
- Most-logged meals (name × frequency); top protein sources (food × g/day).
- **NOT available yet:** CGM/glucose (sensor not active), per-meal glucose response.
**Currently rendered:** header figures (cals/protein/carbs/fat/deficit/TDEE/protein-hit), a
calorie-vs-TDEE trend, a protein-vs-target trend, an average macro-split stacked bar, training-vs-
rest + eating-window + weekday/weekend callouts, a new micronutrient-sufficiency bar + protein-
timing figures, and the meals/protein tables.
**Screenshots:** attached (full desktop scroll + mobile; light/dark if it differs).

## STAGE 2 — The review (after assembling + introducing the panel)
Have the panel react in their own voices, disagreeing where they genuinely would, and deliver:
1. **The one story** this page should tell that it currently doesn't.
2. **Specialist visuals** — concrete. Name the chart type + the exact fields it binds to. (Examples
   to push past, not copy: day-by-day protein bars color-coded by whether each day cleared the
   leucine/target threshold; an eating-window timeline showing 16:8 adherence over the week; a
   deficit "fuel gauge"; a micronutrient sufficiency heatmap; training-day vs rest-day fueling.)
3. **Features / interactions** that level it up.
4. **What to cut** — noise that doesn't serve the documentary's story.
5. **What's missing from my data** I should start capturing to unlock the best version (e.g. would
   a CGM change the page? meal photos? sodium/electrolytes?).
Rank everything by impact. Honor the design system + honesty + me-first. Mark each idea
**buildable now** vs **needs more weeks of data** (it's week one — most series are ~7 points).
