# Design review — FITNESS / TRAINING page (paste whole into your claude.ai Project; attach screenshots)

You are running an elite, page-specific design review for ONE page of my personal
health-transformation website, **averagejoematt.com**. Work in two stages.

## STAGE 1 — Assemble the room (do this first)
Before any critique, design the IDEAL panel for THIS page's domain (**physique transformation +
strength & conditioning + exercise physiology**). Name 4–6 world-class specialists — real-archetype
credentials — who'd give the sharpest, most *specialist* read on this exact page (think: an elite
physique-transformation coach who's taken many people from obese→lean, a strength scientist
(volume-landmark / velocity-based-training school), an endurance & Zone-2 physiologist, a coach who
specializes in training the previously-sedentary/large athlete safely), **plus one
data-visualization designer** (sports-analytics caliber). Briefly justify each pick: why this
expert, for this page. Tailor hard to the data below; this panel should look nothing like a
nutrition or sleep panel. Then one-line intros.

## PLATFORM CONTEXT (every idea must live inside this)
averagejoematt.com is an honest, ongoing **documentary of an ordinary person rebuilding his health
with AI — the "anti-Blueprint."** The current cut started **2026-06-14**, so most series are ~1
week; thin data shown honestly is **on-brand, not a flaw**. Audience: **me daily → a few who know
me → a curious stranger**; me-first but legible. **Honesty is the brand:** down weeks shown, never
superhuman/guru, "you could do this." n=1, correlation-not-cause, **no Pearson coefficients until
~2+ weeks**. (He's ~300 lb, week one of a structured "Foundation" block — the right frame is
*building the engine*, not PRs.)

## DESIGN SYSTEM (elevate within it — don't replace it)
Serif headings (**Fraunces**); **IBM Plex Mono** for data; **ONE accent — ember `#DD7A37`** (down =
muted ink, **never red**); restrained, data-forward, **dark AND light**. Chart kit: line (goal
line; refuses <4 points), bar, stacked-composition bar, sparkline, correlation chip. Protect the
"measuring-rule" tick spine + the two-voice dialogue. Add visuals as extensions of this language.

## THE PAGE + ITS REAL DATA (ground every idea here — flag anything needing data I don't capture)
**Page:** `/evidence/training/` — "the work: lifts, cardio, the body's response."
**Data the APIs (`/api/training_overview` + `/api/strength_benchmarks` + `/api/workouts` +
`/api/weekly_physical_summary` + `/api/pulse_history`) return right now:**
- **Hevy strength, set-level:** 6 named sessions (Push/Pull/Legs/Engine/Recovery), per-exercise
  sets/reps/weight, **total volume per session climbing 6,849 → 16,567 kg**, set counts.
- **Estimated 1RM per main lift** (Epley, from weight_kg) vs personal targets — with "✓ goal met"
  when exceeded; lifts not done this window show "—" not 0.
- **Cardio sessions** — merged Strava + Hevy (walks, elliptical, **cycling** w/ distance + minutes), avg/max HR where present.
- **Zone-2 minutes** vs the 150-min/week target; **daily steps** (Apple Health, ~7–10k), walking distance + pace.
- **Whoop strain** — daily + per-workout; **resting HR trend falling 65→55** during the cut; recovery/HRV trends.
- **NOT available yet:** per-workout HR-zone minutes (Whoop returns 0 for lifts), VO2max, lactate threshold.
**Currently rendered:** header figures (workouts/wk, Z2 %, avg strain, strength sessions, avg
steps), an estimated-1RM table, the per-exercise Hevy strength log (expandable), recent cardio
(incl. cycling + stretching), a steps bar, a daily-movement table, and (in vitals) RHR + strain trends.
**Screenshots:** attached (full desktop scroll + mobile; light/dark if it differs).

## STAGE 2 — The review (after assembling + introducing the panel)
Have the panel react in their own voices, disagreeing where they genuinely would, and deliver:
1. **The one story** this page should tell that it currently doesn't (e.g. "the engine being built,"
   "load managed so a 300-lb body doesn't break").
2. **Specialist visuals** — concrete; name the chart type + exact fields. (Push past, don't copy:
   per-muscle weekly volume vs MEV/MAV/MRV landmarks; a 1RM progression line against a "proven
   curve" benchmark; strain-vs-recovery overlay; Zone-2 minutes vs 150-min target; the session
   volume ramp; a training-density / ACWR load gauge once the window's long enough.)
3. **Features / interactions** that level it up.
4. **What to cut** — noise that doesn't serve the story.
5. **What's missing from my data** I should capture (HR straps for true zones? RPE per set? bar
   speed? rucking load?).
Rank by impact. Honor the design system + honesty + me-first. Mark each idea **buildable now** vs
**needs more weeks of data** (week one — most series ~7 points; ACWR/chronic-load need ~3–4 weeks).
