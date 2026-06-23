# Handover — 2026-06-23 (Training evidence page redesign — P0→P2)

Second page through the design-review → Claude-Code pipeline (after Nutrition). Spec: `docs/SPEC_TRAINING_PAGE_REDESIGN_2026-06-21.md` + `docs/specs/CLAUDE_CODE_PROMPT_TRAINING_PAGE_v1.md` (from `docs/design-review/fitness.md` run through the claude.ai expert panel). Rebuilt `/evidence/training/` on the twin spine: **"building the engine — and managing the load so a heavy body absorbs the work instead of breaking."** 20 commits, one per P-item (+1 fix).

**Status: built + locally verified; NOT deployed (deploy is Matthew's).** PR **#? (`training-page-redesign` → `main`)** — clean off `origin/main` (no cherry-pick; branched after #193 merged). Local renders verified desktop + mobile-390px + light.

## What shipped
- **Phase 0 (P0.1–P0.10):** Lift Index (load-trend sparklines, NO 1RM "goal met"; tiles <3 sessions = "fills in") · session-volume ramp hero (signed-off load caution) · RHR decline hero (RHR-down = ember-positive inversion) · Zone-2 vs 150 cross-source (Hevy bike/elliptical now folded into Z2, server) · HR-of-the-engine (cardio HR; lifting HR honest gap) · walking-as-engine + ember steps heatmap · modality composition (ember ramp, mobility out of cardio) · Push/Pull/Legs balance · daily strain bar (replaced naked avg-strain) · signatures + declutter.
- **Phase 1 (P1.1–P1.6):** RPE per set (autoregulation — 99 populated sets verified) · session sRPE (internal load) · **per-muscle volume vs MEV/MAV/MRV** (blocker #186 verified fixed; compact classifier ported into site-api) · **anatomical body-map** (built per explicit sign-off, overriding the skip rec — stylized front+back, ember-intensity by volume) · HR-strap + rucking honest empty states.
- **Phase 2 (P2.1–P2.3):** strain-vs-recovery overlay (no Pearson, refuses <4) · ACWR placeholder (unlocks ~4 weeks) · present-vs-PROVEN_BLUEPRINT (**private, server-gated, flag OFF**).

## Architecture
- **API:** `lambdas/web/site_api_observatory.py::handle_training_overview` — added `muscle_volume` (compact in-package port of `mcp/strength_helpers.classify_exercise` + landmarks, since site-api can't import mcp/) and folded Hevy bike/elliptical minutes into Z2. `handle_strength_benchmarks` now emits per-lift `history` (Lift Index). New flag `TRAINING_BLUEPRINT_PUBLIC` (default OFF). **No DDB schema change.**
- **Front-end:** `site/assets/js/evidence.js::renderTraining` (now `parts`-style concatenation). New chart-kit fns in `charts.js`: `targetSpine`, `heatStrip`, `stackedDayColumns`, `landmarkBars`; `dualLineChart` gained `showGap`; `lineChart` `spine` reused. `muscleBodyMap`/`liftIndex`/RPE helpers are training-local. Styles in `tokens.css`.

## Privacy / flags
`TRAINING_BLUEPRINT_PUBLIC` on `life-platform-site-api` — leave unset permanently (ADR-089, blueprint never public). Gated at the server (off → `training_reference` never queried). See [[project_nutrition_privacy_flags]] for the sibling nutrition flags.

## Follow-ups
- The `_MUSCLE_MAP`/`_LANDMARKS` in site_api_observatory.py are a port of mcp/strength_helpers — keep in sync if the MCP classifier changes.
- Body-map is stylized/blocky (on-brand with the data-figure); fine but could be refined later if Matthew wants more anatomical detail.
- Deploy: `bash deploy/deploy_site_api.sh /api/training_overview` + `bash deploy/sync_site_to_s3.sh` (Matthew runs). Then live-capture the canonical `evidence-training{,-mobile,-light}.png`.
- Local render harness: `/tmp/training_render.py` (route-mocks the 5 endpoints). See [[reference_local_render_qa]].

## Honesty rails honored
engine-not-PRs (Lift Index trend, never "goal met") · RHR-down ember-positive · ONE hue / ember-intensity ramps, no second colour, no red · no 0-min HR-zone bars on lifts · Z2 counts Hevy cardio · Lift-Index tiles need 3+ sessions · no correlation chip / ACWR until the window.
