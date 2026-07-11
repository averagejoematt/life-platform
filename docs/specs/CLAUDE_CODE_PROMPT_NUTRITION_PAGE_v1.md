# CLAUDE CODE PROMPT — Nutrition Page Redesign (v1)
**Target:** averagejoematt.com → `/evidence/nutrition/`
**Companion spec:** `docs/specs/SPEC_NUTRITION_PAGE_REDESIGN_2026-06-21.md` (read it first — it carries the rationale, the panel disagreements, and the field-level bindings)
**Date:** 2026-06-21

You are implementing a redesign of the nutrition evidence page. Work in phases. Inspect existing code before changing it — do not assume signatures. The API is served by `lambdas/site_api_lambda.py` (Lambda `life-platform-site-api`, **us-west-2**); the page consumes `/api/nutrition_overview`, `/api/frequent_meals`, `/api/protein_sources`. Locate the front-end `/evidence/nutrition/` template/components by inspection.

---

## HARD RULES (non-negotiable — violating these defeats the brand)
1. **No fabricated data.** If a series has < 4 points, the chart kit must render its honest refusal ("fills in as days accrue — N/7 logged"), never a fake line.
2. **No causal language, n=1, correlative framing only.** No Pearson coefficient or correlation chip anywhere until a pair of series has ≥ 2 weeks of overlapping data. Gate this in code, not just copy.
3. **Down/flat is muted ink, never red.** Single accent ember `#DD7A37`. Ember means **"on protocol / floor cleared,"** not literally "up" — so a low micronutrient must NOT render as a confident ember block.
4. **Energy basis for macro composition** (protein·4, carbs·4, fat·9), not gram mass.
5. **Honest empty states**, never zero-rows (no `Rest Day — Count 0`).
6. **Design tokens only:** Fraunces (serif/human), IBM Plex Mono (data), the existing inline-SVG chart kit, measuring-rule tick spine, mono↔serif two-voice. First-class dark AND light.
7. **Privacy tiering:** behavioural (food delivery), financial (Monarch), and PROVEN_BLUEPRINT-derived stats are **private-by-default**; gate public rendering behind an explicit flag.

---

## PHASE 0 — Fixes + the spine (all buildable now, no new capture)
Highest impact; ship this phase first.

**P0.1 — Hero verdict (replaces the 4 neutral big-number tiles).**
- New top component: measuring-rule spine `0 → estimated_TDEE`, with an `avg_calories` tick and `estimated_TDEE` tick; shade the gap = `avg_deficit`.
- Two-voice verdict line beside it: mono = the figures; serif = the judgement, computed from `protein_hit_pct` and `avg_deficit` (e.g. deficit real + protein hit 0% → "that's the trade you're making").
- Keep only the latest-day figure from the old tile row as "news"; fold calories/TDEE/deficit into the hero.

**P0.2 — Lead with the protein miss.** Promote `protein_hit_pct` to a primary, weighted figure (ember-as-warning when low). It currently renders tiny while avg protein renders huge — invert that.

**P0.3 — Kill the timing score.** Remove `protein_timing_score` from the render (or relabel "not yet measured — needs per-meal data"). Do not display a value that cannot change.

**P0.4 — Rebuild micronutrient bars.** Replace the block bars with horizontal sufficiency bars 0→100%, **sorted ascending** (worst first), each with a value label and a 100% target rule; ember reserved for the worst offenders. Fix the desktop right-edge clipping. Add mono caveat: "intake vs target from logged food, not blood levels." Binds `micronutrients{nutrient → {pct, actual, target}}`.

**P0.5 — Fix macro split basis** → kcal contribution. Apply to both the average split bar and the new per-day stacked chart.

**P0.6 — Suppress empty scaffold.** `Rest Day`, `Weekend`, `7d-vs-30d momentum` render honest "needs more days" empty states when their n is 0 or below threshold — not zero rows.

**P0.7 — Per-day macro composition chart** (§3): stacked bars by energy from the daily series; refuses < 4 points.

**P0.8 — Deploy the signatures:** measuring-rule tick spine on the calorie and protein trend charts; one serif "what this means" annotation under the protein-vs-target chart.

**P0.9 — Energy section loss-rate readout** (§1): render target-rate → required-deficit → actual-deficit → gap. Pull `get_deficit_sustainability` server-side and surface its flag honestly next to the rate. Keep the rate and the protein status in one sightline.

## PHASE 1 — New capture unlocks (after fields exist)
Add the API fields first (inspect the nutrition_overview handler and the upstream MacroFactor ingestion), then the front-end.

- **P1.1 Per-meal timestamps + per-meal protein** → eating-window ribbon (per-day first→last vs 16:8 reference) + meal-time-of-day distribution (§4) + real avg-protein-per-meal (§2) + a *real* timing score (revives P0.3 as legitimate).
- **P1.2 Sodium field** → §5 electrolyte framing + week-one water caveat.
- **P1.3 Daily hunger/energy 1–5 capture** → "can I hold this" signal; surface a sparkline.
- **P1.4 Lean-mass estimate** (from Withings body-comp) → g/kg protein floor line in §2.

## PHASE 2 — Cross-source signature features (the wow; honesty- and privacy-gated)
Each is its own ticket; do not bundle.

- **P2.1 Standing self-grading prediction.** Server: emit a projection object (target metric, date, confidence band) from the prediction ledger / intelligence layer. Front-end: render the bet AND its later verdict (confirmed/refuted/drifted). The band and verdict are mandatory.
- **P2.2 Reconciliation (scale vs log).** Server: expose projected-loss-from-energy-balance alongside the Withings weight trend. Front-end: two trajectories, gap annotated, no Pearson. Gate on ≥ 2 weeks overlap.
- **P2.3 Food-delivery off-protocol tell.** Server: join food-delivery events with daily deficit adherence. Front-end: home-cooked vs delivery-day comparison, framed as data not verdict. **Private-by-default.**
- **P2.4 (defer)** protein→Whoop-recovery observation strip; last-meal→sleep observation. Observation-only, ≥ 2 weeks, no causal copy.
- **P2.5 (private-only)** present-vs-PROVEN_BLUEPRINT benchmark — never public.

## CGM (designed now, data later)
Build the §8 empty state: ghosted glucose-curve-with-meal-markers placeholder + "sensor not active — fills in when you wear one." No live binding yet.

---

## ACCEPTANCE CRITERIA / QA
Re-capture `qa-screenshots/evidence-nutrition.png` + `-mobile.png` and verify:
- [ ] The protein-target-hit (0%) reads as the leading/weighted signal, not buried.
- [ ] No `100` timing score on the page (or clearly labeled "not yet measured").
- [ ] Micronutrient bars are scaled, labeled, ranked worst-first, none clipped on desktop or mobile (390px); a low value does NOT read as ember "good."
- [ ] Macro split percentages reflect kcal contribution (fat ≈ 30%, not 16%).
- [ ] No zero-rows anywhere (Rest Day / Weekend render empty states).
- [ ] Measuring-rule tick spine present on both trend charts; ≥ 1 serif annotation present.
- [ ] Any chart with < 4 points shows the honest refusal, not a drawn line.
- [ ] Dark and light both first-class. No red. Single ember accent.
- [ ] No causal language; no correlation chip on any < 2-week pairing.

## DEPLOY (per repo convention)
- API: `deploy/deploy_lambda.sh` for `life-platform-site-api` (us-west-2). Wait 10s between sequential deploys.
- If any MCP tool surface changed: tool fns BEFORE `TOOLS={}`; run `pytest tests/test_mcp_registry.py` before MCP deploy.
- Update `CHANGELOG.md` + `PROJECT_PLAN`; if data model changed, `ARCHITECTURE`/`SCHEMA`/`DATA_DICTIONARY`; run `python3 deploy/sync_doc_metadata.py --apply` if counts changed. Then commit + push.

## OUT OF SCOPE
Bare hydration ring; weekday/weekend split at week one; any public rendering of blueprint/behavioural/financial data without an explicit opt-in flag; live CGM binding.
