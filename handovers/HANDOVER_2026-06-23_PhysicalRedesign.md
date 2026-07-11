# Handover — 2026-06-23 (Physical page redesign — weight cockpit + composition arc + PhenoAge)

Fifth Evidence page through the design-review → Claude-Code pipeline (Nutrition → Training → Sleep → Habits → **Physical**). Spec: `docs/specs/SPEC_PHYSICAL_PAGE_REDESIGN_2026-06-21.md` + `docs/specs/CLAUDE_CODE_PROMPT_PHYSICAL_PAGE_v1.md`. Reframed `/evidence/physical/` on the spine **"weight is the metronome; composition is the arc."** 21 commits, one per P-item.

**Status: built + locally verified + DEPLOYED + live-verified + MERGED.** PR **#201** (`physical-page-redesign` → `main`, squash-merged `9773214c`, branch deleted). Build fingerprint `89c294fb` == HEAD live; live page renders all 13 sections with real (thin, ~9-day) data, zero console errors. Page renamed "Body composition" → **"Weight & composition"**.

## What shipped
- **Phase 0 — Tier 1 weight cockpit (P0.1–P0.7):** trend-weight hero (dual-layer raw dots + ember smoothed trend; **goal 185 = annotation NOT axis anchor**, HARD RULE 4; genesis marked; two-voice) · silhouette scrubber **linked to the trend marker in lockstep** (reused `dataFigure`; refactored wiring into `wireDataFigure(onWeight)`; below-axis goal pinned+muted via `moveTrendMarker`) · HappyScale stat cluster (high/latest/low · yesterday Δ · % complete) replacing DEXA % · **milestone ladder** (vertical measuring-rule, 315→185, rungs click ember when crossed, days-between annotated, live now-edge) · rate tempo strip (7d/30d/90d/since-genesis ember-intensity slope-gauges; 7d "early=water") · **projection cone** (widening fast/mid/slow band, rung date-markers, stated bet flagged early=water + gradeable) · BMI de-emphasized.
- **Phase 1 — Tier 2 composition arc (P1.1–P1.6):** next-DEXA countdown (cut-aware ~10wk-post-genesis, honest not-booked) · DEXA baseline as one dated lean-vs-fat stacked bar (pre-cut, snapshot-not-trend) · visceral fat callout + directional risk gauge (ember-intensity, never red, thresholds caveated) · lean/ALMI longevity (demoted, sarcopenia-floor) · **transparent Levine PhenoAge** · full-scan expander (dated) with **+3.9 T-score suppressed+flagged as artifact**.
- **Phase 2 (P2.1–P2.5):** capture-backlog grid of honest gated states — every STOP-AND-ASK gate honored by NOT building the gated thing.

## PhenoAge — privacy (Option A, owner-decided this session)
- **New `/api/phenoage`** (`site_api_data.py::handle_phenoage` + `_compute_phenoage`). Levine 2018 formula over the 9 markers + chronological age. **Chronological age is used ONLY to compute (from profile `date_of_birth`) and is NEVER returned — no chronological number, no chrono−pheno gap.** Verified live: zero chronological-leak terms in the payload. Live phenotypic age = **28**.
- **Lymphocyte % derived** (option 2a) from absolute lymphocytes ÷ WBC, labeled "derived" in the UI.
- All 9 markers shown (younger/older/neutral vs healthy reference; ember=younger); per-draw stamp (`latest_draw_date` 2026-04-03); mandated caveats (population-level not diagnostic; blood-based Phenotypic Age NOT the DNAm clock; per-draw; CRP-volatile). Replaces the DEXA `score_360.biological_age` black box (no longer rendered).
- ⚠️ **Residual (PHY-01, flagged to owner):** the 9 markers are public on the labs page, so a determined reader applying the Levine formula could approximate chronological age from the precise published phenotypic number. Option A removes the *obvious* leak; harder banding (round PhenoAge to nearest 5 / direction-only drivers) is available if Matt wants zero-deducibility. Low urgency.

## Architecture
- **API:** `lambdas/web/site_api_data.py` — new `handle_phenoage` + `_compute_phenoage` (+ `_PHENOAGE_COEF`/`_PHENOAGE_LABELS`). `lambdas/web/site_api_vitals.py::handle_journey` — added `height_inches` (profile, authoritative — DEXA-derived height disagrees ~1.5 in) for the de-emphasized BMI. Route wired in `site_api_lambda.py` (`/api/phenoage`). **No DDB schema change.**
- **Front-end:** `site/assets/js/evidence.js::renderPhysical` fully rebuilt (parts array, async, fetches weight_progress + journey + phenoage). New helpers: `physicalTrendHero`, `physicalStatCluster`, `physicalMilestoneLadder`, `physicalRateTempo` (+ `_slopePerDay`), `physicalDexaCountdown`, `physicalDexaBaseline`, `physicalVisceralCallout`, `physicalLeanLongevity`, `physicalPhenoAge`, `physicalFullScanExpander`, `physicalCaptureBacklog`. `WIRE.physical` added; `results:` silhouette wiring refactored to the shared `wireDataFigure`. New `charts.js` exports `weightTrendChart` + `projectionCone`. Styles (`wt-*`, `ml-*`, `rt-*`, `pc-*`, `dx-*`, `vf-*`, `pa-*`, `fs-*`, `cap-*`) in `tokens.css`. Page title/blurb via `scripts/v4_build_evidence.py` (rebuilt all 38 shells).

## Honesty / gates honored
- Goal never anchors the weight axis; genesis marked; early rate framed as water; <4-point charts refuse.
- ONE DEXA is a point — every composition figure dated 2026-03-30 + pre-cut-labeled; NO composition velocity/`changes_vs_baseline`-as-progress (P2.4 gated on scan two + LSC).
- +3.9 T-score suppressed; DEXA Body Score + black-box bio-age replaced by transparent PhenoAge.
- Ember positive on weight-down / fat-down / younger-bio-age; **no red** anywhere.
- STOP-AND-ASK gates: progress photos NOT publicly rendered (private-by-default); composition velocity NOT built (one scan); WHOOP Age NOT built (unofficial source). Deploy was authorized in-session ("keep going, do it all").

## Follow-ups (PHY-series in `docs/BACKLOG.md`)
PHY-01 PhenoAge inversion residual (owner decision) · PHY-02 schedule scan two · PHY-03 tape capture · PHY-04 progress-photo opt-in · PHY-05 composition velocity (gated) · PHY-06 complementary ages (vascular/VO₂max; WHOOP Age fragile).

## Verification
Local harness `/tmp/physical_render.py` (route-mocks physical_overview + weight_progress + journey + phenoage). `_compute_phenoage` unit-tested standalone (~10 yr younger than chronological across candidate ages). Live capture confirmed real-data render. 63 web/site-api tests pass; black clean. Build fingerprint == HEAD live.

See [[project_build_fingerprint]], [[reference_local_render_qa]], [[feedback_prod_deploy_authorization]] (deploy authorized in-session).
