# SPEC — /evidence/nutrition/ Page Redesign
**Date:** 2026-06-21
**Page:** averagejoematt.com → /evidence/nutrition/ — "the deficit, the protein, the meal honesty."
**Source of this brief:** elite page-specific design review (nutrition-science bench + product/UX bench), grounded in the live page screenshots (`qa-screenshots/evidence-nutrition.png`, `…-mobile.png`) and the real API data.

---

## 0. The one story (the spine)
The page is currently a stack of ~10 equally-weighted sections — a tile board, not a trajectory. It must hang off **one question**:

> **"A deficit I can hold, hitting the protein to keep muscle, without quietly costing me anything."**

Deficit, protein floor, and micronutrient/behaviour cost are not separate tiles — they are the halves of one claim. Order the page to argue it.

## 1. Current-state findings (real data, must fix)
Pulled from the live page on 2026-06-21 (data window Jun 15–19, n=5):

- **Protein-target hit = 0%.** Avg protein 143.8 g vs a 190 g goal — missed every logged day. Today it is rendered tiny while `143.8g AVG PROTEIN` is a giant neutral headline. **The hierarchy is inverted: the failing metric must lead.**
- **`100` protein-timing score** sits directly above `46%` micronutrient avg and a page-wide `0%` protein hit. A score that can't fall, congratulating the spacing of a thing he isn't eating enough of. **Kill it or relabel "not yet measured"** (no per-meal timestamps exist to compute real timing).
- **Micronutrient bars actively mislead.** Three solid ember blocks (fiber/magnesium/potassium), not legibly scaled to their %, no axis, no value labels, and **ember = "alive/up" makes a 25% potassium deficiency read as a win.** The third bar also **clips off the right edge on desktop.** Replace entirely.
- **Macro split appears computed by gram mass, not energy.** Shows `PROTEIN 144g·44% / CARBS 128g·39% / FAT 53g·16%` — those are gram fractions. By calories it's ~37/33/30; fat at "16%" badly understates where calories come from. **Recompute on a kcal basis.**
- **Empty scaffold rendered as data:** `Rest Day — Count 0` and `Weekend — Days 0` show as findings. Suppress with honest empty states.
- **The page isn't using its own signatures.** No measuring-rule tick spine on the charts; the mono↔serif two-voice dialogue is nearly absent (Fraunces appears only in the H1). Deploy both here.
- **Working well (keep):** the protein-vs-target chart draws the 190 g dotted goal with the ember line clearly below — best element on the page; the honest `n=5` footer and `5 PTS` labels; the meals + protein-source tables.

## 2. Page architecture (top to bottom)
Status legend: **[now]** buildable today · **[needs-data]** requires new capture · **[defer]** later / cross-page.

**§0 — The verdict (hero).** Replaces the four neutral big numbers. One measuring-rule spine: intake tick vs TDEE tick, the gap shaded = deficit. Beside it the honest verdict in two-voice (mono states, serif judges), e.g. *"Deficit's real. Protein's missing every day. That's the trade you're making."* Binds `avg_calories`, `estimated_TDEE`, `avg_deficit`, `protein_hit_pct`. **[now]**

**§1 — Energy: the deficit story.** Calorie trend line with the TDEE reference line drawn; a direction chip (avg, up/down vs prior days); a loss-rate readout: target rate → required deficit → actual deficit → honest gap. Binds daily `calories[]`, `estimated_TDEE`, `avg_deficit`. **[now]**
> **Disagreement to surface on the page:** target rate 3 lb/week ≈ ~1,500 kcal/day deficit. Okafor: defensible early at his size, *if* monitored. Marchetti: 3 lb/wk sustained + protein at 0% + micros at 46% = muscle/mineral drawdown, not fat loss. Raman: the rate is only safe at a protein floor he isn't hitting. **The loss-rate readout and protein status must share a sightline.** Pull `get_deficit_sustainability` to flag this honestly; never hide the rate.

**§2 — Protein: the muscle-retention story.** Per-day bars, ember when the day clears the floor / muted when not; 190 g target line; annotate the floor as a g/kg-lean muscle-retention line (needs lean-mass for the exact value). Add avg-protein-per-meal as a secondary figure. Binds `protein_g[]`, `protein_target`. **[now]** (g/kg floor **[needs-data: lean mass]**)

**§3 — Macros: where the cut comes from.** Per-day stacked composition **by energy** (protein·4 / carbs·4 / fat·9), revealing whether the cut comes out of carbs/fat while protein holds. Binds daily macro series → kcal. Refuses < 4 points. **[now]**

**§4 — Rhythm: fasting & meal timing.** (a) Eating-window ribbon: per-day first→last meal vs a 16:8 reference; (b) meal-time-of-day distribution (when calories/protein land across the clock). Real data already shows a 7.8 h window (11:30–19:15) — closer to 18:6 than 16:8; surface it. Average window **[now]**; per-day ribbon + time-of-day histogram **[needs-data: per-meal timestamps]**

**§5 — Hydration & electrolytes.** **Do NOT ship a bare hydration ring** (vanity metric, off-brand). Only build if captured *with* sodium/potassium and framed as "water-weight & electrolyte honesty on a cut" (also feeds the week-one "the drop is water" caveat). **[needs-data]** — contested even then.

**§6 — The food itself.** Keep the two tables (most-logged meals; top protein sources). Add the **fixed micronutrient bars** (ranked ascending, axis-bound, labeled) reframed as "what your food is short on." Add a **"be mindful" lane** — not red-flagged foods, but the honest flip: your calorie-dense / low-protein logs, derived from the same data. Mono caveat: *intake-vs-target from logged food, not blood levels.* Binds meals/protein tables + `{nutrient → pct}`. **[now]**

**§7 — Top tips / next level.** Coaching layer in the serif voice, **data-derived not generic**, e.g. *"Protein's ~46 g under target; from your logged foods the cheapest close is another Greek yogurt or a second turkey serving."* Fed by meals/protein tables. **[now]**

**§8 — [Coming online] CGM × meal overlay.** Glucose curve with meal markers, spikes annotated. Render a **designed empty state** now ("sensor not active — fills in when you wear one," ghost of the eventual chart), not a blank. **[defer]**

**§9 — [Later, cross-page] Food → sleep/recovery.** Observation-only ("ate late, slept worse — noted"), never a claimed effect, no correlation chip until ≥2 weeks overlapping data (honors the no-Pearson-before-two-weeks rule). **[defer]**

## 3. Cross-source signature layer (the "wow" — what makes it about Matthew, not an app)
Ranked. Honesty-gated and privacy-tiered.

1. **Standing self-grading prediction [now to state, resolves over weeks].** Platform projects a weight/date crossing from intake + TDEE, with a confidence band, then resolves confirmed/refuted/drifted in the open. Uses the prediction ledger. **Must show the band and the eventual verdict** — a prediction you don't grade is a horoscope.
2. **Reconciliation: scale vs food log [needs ~2 weeks].** Energy-balance projected loss vs actual Withings trend, both drawn; the gap is the honest logging-accuracy / TDEE-drift story. Two lines, no Pearson.
3. **Food delivery as the off-protocol tell [now/soon].** Deficit adherence on home-cooked vs delivery days, from the food-delivery behavioural source. Frame as data, not verdict. **Private-by-default; public only if Matthew opts in.**
4. **[defer] Protein day → next-morning Whoop recovery** — labeled observation strip only until weeks accrue (Vogt wants it sooner; rigor bench holds the line).
5. **[defer] Last-meal time → sleep quality** (Eight Sleep / Whoop).
6. **[private-only] Present-Matthew vs past-Matthew** — current protein/walking vs the PROVEN_BLUEPRINT loss period. Powerful but the blueprint is private; never public-facing.
7. **[optional] Protein cost-per-dollar** via Monarch grocery spend — documentary texture, low priority.

## 4. Cut list
- The `100` timing score (or relabel "not yet measured").
- Empty Rest-Day / Weekend rows → honest empty states.
- Gram-basis macro split → recompute by energy.
- 7d-vs-30d momentum and weekday/weekend split at week one → honest "needs 2+ weeks" states, not zero rows.
- Redundant header number-tiles once §0 hero exists (keep the latest-day figure as news).

## 5. Data-capture backlog (unlocks, ranked by leverage)
1. **Per-meal timestamps + per-meal protein** — highest leverage; resurrects the timing score and lights up §4 (ribbon + time-of-day) and §2 (avg protein/meal).
2. **Sodium** (have potassium, not sodium) — enables the §5 electrolyte framing and the week-one water caveat.
3. **Daily hunger/energy 1–5** — cheap; powers the "can I hold this" story; ties to mood continuity.
4. **Lean-mass estimate** (Withings/DEXA) — makes the §2 protein floor a real g/kg line.
5. **CGM** — glamorous but lower priority than (1); defer as a standalone experiment.

## 6. Must-honor constraints
- **Design system:** Fraunces (serif = human voice), IBM Plex Mono (data voice), ONE accent ember `#DD7A37`; down/flat = muted ink, **never red**. First-class dark AND light. Reuse the zero-dep inline-SVG kit (line / bar / stacked / sparkline / correlation-chip). Protect the two signatures: the measuring-rule tick spine and the mono↔serif dialogue — and **deploy them on this page.**
- **Ember semantics here:** on a deficit page "up/alive" is ambiguous (you want some lines down). Define ember = **"on protocol / floor cleared,"** direction read contextually — so the accent never cheers a deficiency (the micronutrient-bar bug).
- **Honesty:** n=1, correlative framing only, no causal language, **no Pearson/correlation chip until ≥2 weeks** of overlapping data. Down weeks shown, never hidden. Charts honestly refuse under 4 points. Thin data shown as "fills in as days accrue," not faked.
- **Audience:** me-first → people who know him → curious stranger. Privacy-tier the behavioural/financial/blueprint signals (private-by-default).
