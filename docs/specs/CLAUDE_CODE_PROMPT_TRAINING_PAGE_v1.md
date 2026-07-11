# CLAUDE CODE PROMPT — Training Page Redesign (v1, rev. with athlete additions)
**Target:** averagejoematt.com → `/evidence/training/`
**Companion spec:** `docs/specs/SPEC_TRAINING_PAGE_REDESIGN_2026-06-21.md` (read first — rationale, panel disagreements, field bindings)
**Date:** 2026-06-21

Implement in phases. Inspect existing code before changing it. API: `lambdas/site_api_lambda.py` (Lambda `life-platform-site-api`, **us-west-2**); page consumes `/api/training_overview`, `/api/strength_benchmarks`, `/api/workouts`, `/api/weekly_physical_summary`, `/api/pulse_history`. Locate the front-end `/evidence/training/` components; reuse the inline-SVG chart kit (no new deps).

---

## HARD RULES (non-negotiable)
1. **No fabricated data.** <4 points / per-lift <3 sessions → honest empty state ("fills in as days accrue — N logged"), never a drawn line/slope.
2. **No causal language, n=1, correlative only.** No Pearson/correlation chip until >=2 weeks overlap; ACWR/chronic-load need ~3-4 weeks → placeholder. Gate in code.
3. **Frame = building the engine, NOT PRs.** Never normalize maxing. 1RM data renders only as the Lift Index TREND, never a target with "goal met."
4. **Ember = "engine building / on protocol / cleared," not literally "up."** Down = muted ink, never red — EXCEPT RHR-down, which is a WIN → ember-positive. Get this inversion right.
5. **Color discipline.** Where a visual needs >1 category (modality composition; lift up/down), derive a tight ramp from ember (tints/shades + ink). Do NOT add a second hue. "More colorful" = ember intensity/heatmap, not rainbow.
6. **Honest empty states, never zero-rows.** Whoop returns 0 HR-zone minutes for lifts → "not captured for lifting," never a 0 bar.
7. **Design tokens only:** Fraunces, IBM Plex Mono, measuring-rule tick spine, mono<->serif two-voice. First-class dark AND light.
8. **Privacy tiering:** proven walking floor + present-vs-past-Matthew benchmark are blueprint-derived → private-by-default; no public render without an explicit opt-in flag.

---

## PHASE 0 — Fixes, twin-spine heroes, and the new visuals (buildable now)
**P0.1 — Lift Index (signature).** Replace the 1RM "✓ goal met" table with a grid of main lifts, each a sparkline + ▲/▼/flat trend tag (ember up / muted-ink down, never red). Per-tile honesty gate: NO arrow/slope until ~3+ sessions of that lift; show "fills in — N sessions" until then. Keep the expandable per-exercise set/rep/weight log beneath. Binds `strength_benchmarks` / Hevy set-level history as per-lift trend.
**P0.2 — Session-volume ramp hero.** Per-session total volume (6 sessions, 6,849->16,567 kg), WoW % annotated + honest "ACWR unlocks ~4 weeks" placeholder.
**P0.3 — RHR decline hero (promote out of vitals).** Line 65->55, cut-start marked, two-voice annotation, multi-factorial caveat in mono, RHR-down ember-positive. Binds `pulse_history` RHR.
**P0.4 — Zone-2 vs 150/week, cross-source.** Count BOTH Strava AND Hevy bike/elliptical minutes. Never Strava-only.
**P0.5 — HR of the engine.** Avg HR per cardio session + walking-HR trend toward the proven easy band (~97 bpm). Cardio HR exists today; lifting HR stays an empty state.
**P0.6 — Walking-as-engine + steps heatmap.** Steps + walking distance/pace as the primary engine; render steps as an ember-intensity heatmap/streak (saturation = volume), low days shown muted not hidden. Proven walking floor behind the privacy flag.
**P0.7 — Training-time modality composition.** Stacked-composition bar of minutes by modality (lift / walk-cardio / mobility) per day or week, ember-derived categorical ramp. This also moves mobility OUT of "recent cardio." Binds per-session duration by type (merged Hevy+Strava).
**P0.8 — Push/Pull/Legs balance.** Working-set-volume balance (three-bar or stacked) off Hevy session tags.
**P0.9 — Daily strain bar.** Replace naked avg-strain headline with a day-by-day Whoop strain bar.
**P0.10 — Signatures + declutter.** Measuring-rule tick spine on volume/RHR/Lift-Index; >=1 serif annotation; remove stretching/recovery from the cardio list.

## PHASE 1 — New capture + gated visuals
- **P1.1 RPE per set** → autoregulation + effort signal; feeds Training Feedback Loop.
- **P1.2 Session sRPE (RPE x duration)** → internal load for honest ACWR.
- **P1.3 Per-muscle volume vs MEV/MAV/MRV** — landmark bars. BLOCKED until the `get_muscle_volume` core->"Other"/staleness bug is fixed; do not ship core reading 0.
- **P1.4 Anatomical body-map (optional)** — only after P1.3's mapping is trustworthy. Flagged app-cliché; confirm with me it's worth the distinctiveness cost before building.
- **P1.5 HR strap for lifting zones** → fills the Whoop-returns-0 gap.
- **P1.6 Rucking load / incline on walks** → progressible walking.

## PHASE 2 — Load management + longer-window
- **P2.1 Strain vs recovery overlay** — Whoop strain + recovery/HRV; refuses <4 points.
- **P2.2 ACWR / training-density load gauge** — placeholder now; populate ~3-4 weeks.
- **P2.3 (private-only)** present-vs-PROVEN_BLUEPRINT training benchmark — never public.

---

## ACCEPTANCE CRITERIA / QA
Re-capture `evidence-training.png` + `-mobile.png` (390px) + `-light.png` and verify:
- [ ] No "✓ goal met"/1RM-target framing; Lift Index renders, tiles under 3 sessions show empty state (no arrow).
- [ ] Volume-ramp + RHR heroes lead; RHR-down reads ember-positive (not muted/red).
- [ ] Z2 includes Hevy bike/elliptical; HR-of-the-engine shows cardio HR; lifting HR is an honest gap.
- [ ] Steps heatmap shows low days muted, not hidden.
- [ ] Modality composition present; mobility no longer listed as cardio; no naked avg-strain headline.
- [ ] Push/Pull/Legs balance present; body-map NOT shipped unless P1.3 fix + my sign-off.
- [ ] Tick spine + >=1 serif annotation; single ember accent, no second hue, no red.
- [ ] Any <4-point chart shows honest refusal; no causal language; no ACWR/chip under window.
- [ ] Dark and light both first-class.

## STOP-AND-ASK gates (no proceed without sign-off)
- Load-management caution copy on the 2.4x volume ramp.
- Body-map build (distinctiveness cost) — P1.4.
- Any public render of walking floor / blueprint benchmark.
- Any deploy.

## DEPLOY (per convention)
`deploy/deploy_lambda.sh` for `life-platform-site-api` (us-west-2), 10s between deploys. Update CHANGELOG + PROJECT_PLAN; data-model changes → ARCHITECTURE/SCHEMA/DATA_DICTIONARY; `python3 deploy/sync_doc_metadata.py --apply` if counts changed; commit + push.

## OUT OF SCOPE
PR/max-testing prompts; live VO2max/lactate (not captured); VBT/bar-speed; ACWR before the window; second accent hue; any public blueprint/private-tier data without opt-in.
