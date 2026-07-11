# Handover — 2026-06-23 (Vitals page redesign — glance-first, three altitudes)

Sixth Evidence page through the design-review → Claude-Code pipeline (Nutrition → Training → Sleep → Habits → Physical → **Vitals**). Spec: `docs/specs/SPEC_VITALS_PAGE_REDESIGN_2026-06-21.md` + `docs/specs/CLAUDE_CODE_PROMPT_VITALS_PAGE_v1.md`. Reframed `/evidence/vitals/` (the landing page) into a glance-first instrument panel, three altitudes. 7 P-item commits.

**Status: built + locally verified + DEPLOYED + live-verified + MERGED.** PR **#205** (`vitals-page-redesign` → `main`, squash-merged `c3a42093`). **Front-end only — no server change.** Live: 10 sections, status RECOVERED, zero console errors.

## What shipped
- **Altitude 1 (P0.1–P0.4):** status word synthesised from 4 component rings (anti-black-box) · now/7d/30d ladder (30d "fills in") · earned glyphs (light ember only on real signal; habits X-of-N fallback) · thin-data stamp + dashed ring tracks.
- **Altitude 2 (P1.1–P1.3):** two-voice autonomic narrative · autonomic hero (RHR inverted + HRV one frame) · readiness decomposed into driver bars.
- **Altitude 3 (P2.1–P2.5):** autonomic 2×2 (no arrows) · small-multiples grid (replaced the 8 equal charts) · background-vitals honest empty · hub links.
- **Phase 3 (P3.1–P3.6):** honest capture cards; cross-metric correlations WITHHELD until ≥2wk.

## Reserved RED (new, scoped)
This page introduces `--alert` (#B14A33, restrained oxblood) in `tokens.css` — the FIRST page to use red. **Scoped strictly to a genuine STATE alert** (run-down / out-of-range), NEVER to encode a falling direction. RHR-down / HRV-up / weight-down all stay ember-positive. On a recovered day it renders zero times (verified). The spec notes red may later propagate to sleep/nutrition at-risk states — NOT applied there yet.

## Architecture (front-end only)
- `site/assets/js/charts.js`: new exports `ring`, `autonomicHero` (RHR inverted + HRV, normalised, both-up = recovery), `autonomicQuadrant` (recovery×strain 2×2, no arrows).
- `site/assets/js/evidence.js::renderPulse`: fully rebuilt (parts array; fetches `/api/pulse` + `/api/pulse_history` + `/api/habits`). Helpers: `_vitalsComponents`, `vitalsStatusRead`, `vitalsLadder`, `vitalsGlyphs`, `vitalsNarrative`, `vitalsReadinessDecomposed`, `vitalsSmallMultiples`, `vitalsBackgroundStrip`, `vitalsHubLinks`, `vitalsCaptureBacklog`. The old 8 equal charts are gone.
- `site/assets/css/tokens.css`: `--alert`/`--alert-wash`/`--alert-line` tokens + `vs-*`, `vr-*`, `vl-*`, `vg-*`, `ah-*`, `aq-*`, `sm-*`, `vh-*` blocks.
- Data: status decomposed from `pulse.glyphs.recovery` (recovery_pct/hrv_ms/rhr_bpm) + `pulse.glyphs.sleep`; baselines + hero + 2×2 + small-multiples from `pulse_history`; habits today from `/api/habits` history `t0_done`/`t0_total`. No DDB/endpoint change.

## Honesty / gates honored
- Glance-first, ~2s readable; status decomposed (rings ARE the components), never a lone grade.
- Red reserved (state-alert only); thin-data stamp + "fills in"; temporal last-night/same-day labels; charts refuse <4 pts.
- STOP-AND-ASK: no cross-metric correlation before ≥2 weeks (P3.6 withheld at day 10); deploy authorized in-session. Red NOT expanded beyond the reserved state-alert.

## Prior shipped this session
RQA-04 (readiness on Cockpit, #202), RQA-05 (deficit-sustainability panel, #203), WQA-06 (coach disagreements, #204), Physical page (#201). See those handovers + CHANGELOG.

## Next: Doors / IA redesign (queued)
Specs: `docs/specs/CLAUDE_CODE_PROMPT_DOORS_v1.md` + `docs/specs/SPEC_DOORS_EXPERIENCE_REDESIGN_2026-06-21.md`. Cross-site IA review (5-door model + me-first LOCKED). P0 = a real bug: the Day-N/Week stamp disagrees across doors (Home says Week 1 on Day 8; correct is Week 2) → build ONE genesis source of truth every door consumes. Then de-dupe artifacts (P1), per-door uplevels (P2), the moat (P3, incl. the Third-Wall reply mechanic = STOP-AND-ASK). NEVER `--delete` on S3 sync; never run deploy via MCP.

See [[project_build_fingerprint]], [[reference_local_render_qa]], [[feedback_prod_deploy_authorization]].
