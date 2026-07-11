# Handover — 2026-06-21 (Nutrition evidence page redesign — P0→P2 + CGM)

Driven by a turnkey spec (`docs/specs/SPEC_NUTRITION_PAGE_REDESIGN_2026-06-21.md` + `docs/specs/CLAUDE_CODE_PROMPT_NUTRITION_PAGE_v1.md`). Rebuilt `/evidence/nutrition/` from a flat tile-board into one argued trajectory: **"a deficit I can hold, hitting the protein to keep muscle, without quietly costing me anything."** All three phases, one commit per P-item.

**Status: DEPLOYED + live-verified.** Site-api + site both deployed by Matthew; production build `8d342e15`. Verified on live desktop + mobile-390px + dark/light. **PR [#193](https://github.com/averagejoematt/life-platform/pull/193) (`nutrition-redesign-pr` → `main`) is open — merge it to bring `main` in sync with what's deployed** (the deploy ran from the local `nutrition-page-redesign` branch; the PR is the clean cherry-pick onto `origin/main`, since hevy is already on main via #192).

## What shipped (19 feature commits + 1 docs)
- **Phase 0 (P0.1–P0.9):** §0 hero verdict (measuring-rule energy spine + two-voice) · lead with the 0% protein miss (ember-as-warning, never a "win" block) · kill the frozen timing score · worst-first horizontal micronutrient sufficiency bars (no clip) · kcal-basis macro split (fat ~30%, not 16%) · honest empty states (no zero-rows) · per-day macro composition stacked by energy (<4pts refuses) · the two signatures deployed (tick spine on both trend charts + serif annotation) · §1 loss-rate readout (target 3 lb/wk → required → actual → gap) + deficit-intensity flag.
- **Phase 1 (P1.1–P1.4):** per-meal timing+protein → §4 rhythm (eating-window ribbon vs 16:8, time-of-day, avg protein/meal, **real** distribution score reviving P0.3) · sodium → §5 electrolyte honesty + week-one water caveat · hunger/energy not sourceable → honest "needs capture" empty state · lean mass (Withings) → g/kg-lean protein floor in §2.
- **Phase 2 (P2.1–P2.5 + CGM):** standing self-grading weight prediction (bet+band+verdict) · scale-vs-log reconciliation (two trajectories, gap annotated, **no Pearson**, gated ≥2wk overlap) · food-delivery off-protocol tell (**private, flag OFF**) · present-vs-PROVEN_BLUEPRINT (**never public, flag OFF**) · CGM × meals designed empty state. P2.4 deferred per spec.

## Architecture / where things live
- **API:** `lambdas/web/site_api_observatory.py::handle_nutrition_overview` — added computed response objects `loss_rate`, `meal_rhythm`, `electrolytes`, `lean_mass`, `projection`, `reconciliation`, `food_delivery`, `blueprint_benchmark`. **No DynamoDB schema change** — all computed from existing macrofactor/withings/food_delivery/training_reference data.
- **Front-end:** `site/assets/js/evidence.js::renderNutrition` (data-driven section list). New chart-kit fns in `site/assets/js/charts.js`: `intakeSpine`, `sufficiencyBars`, `stackedColumns`, `mealWindowRibbon`, `dualLineChart`, plus a `spine` option on `lineChart`. Styles in `site/assets/css/tokens.css` (chart kit) — reuses the spine (§4) / two-voice (§5) / honesty (§6) design tokens.

## Privacy (IMPORTANT — see [[project_nutrition_privacy_flags]])
Two server-side env flags on `life-platform-site-api`, both **OFF** (gated at the server — with the flag off the private source is never queried):
- `NUTRITION_DELIVERY_PUBLIC` — P2.3. Wired but dark. Flip to `true` **only after Matthew confirms**; ping before rendering.
- `NUTRITION_BLUEPRINT_PUBLIC` — P2.5. **Leave unset permanently** (ADR-089: blueprint never surfaces publicly).

## Known follow-ups / next
- **Matthew wants this same redesign treatment applied to the other evidence sections** — this page is the template. He notes the nutrition page "still needs some work" (design polish) but is much improved.
- **P2.1 standing bet** currently renders only when a current Withings *weight* + positive implied rate exist (absent on genesis-week live — honest). Full auto-grading (confirmed/refuted/drifted) needs a **persistent weekly snapshot in a compute lambda**; today it states the bet with a pending verdict + resolution date. Follow-up.
- Cosmetic: the reconciliation chart legend computes its own endpoint gap while the prose uses the API's `gap_lbs` — they match on real data (diverged only in the synthetic mock by rounding).
- **QA without deploy:** local Playwright render harness at `/tmp/nutrition_render.py` (route-mocks the 3 API endpoints, serves `site/` over http, captures dark/light/390px). Documented as a reusable technique in [[reference_local_render_qa]]. Canonical live screenshots: `qa-screenshots/evidence-nutrition{,-mobile,-light,-light-mobile}.png`.

## Honesty rails honored throughout
kcal-basis macro split · no zero-rows · ember never cheers a deficiency · honest empty states under 4 points · leads with the 0% protein miss · **no correlation chip / Pearson on any <2-week pairing** · single ember accent, no red, dark+light first-class.
