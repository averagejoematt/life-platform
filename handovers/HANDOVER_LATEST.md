# Handover — v6.9.0: Cycle Pause visualization on observatory charts

**Date:** 2026-05-03
**Scope:** Make the platform pause (April 12 → May 1 house move) immediately legible on every observatory chart, instead of looking like broken data.

Spec: `docs/SPEC_CYCLE_PAUSE_VIZ_2026_05_03.md` — WR-47 user-facing surface.

## What changed

1. **NEW shared module** — `site/assets/js/cycle-pause.js` (~270 lines). Exposes `getPauses()`, `filterTrend()`, `renderSvgBand()`, `renderCanvasBand()`, and `chartjsPlugin`. Single source of truth for pause windows; idempotent renders; conditionally hides when visible window doesn't intersect the gap.
2. **CSS additions** — `site/assets/css/observatory-v3.css` gets `.cycle-pause-label`, `.cycle-pause-band`, `.cycle-pause-overlay` utility classes (subtle gray dashed band, 10px monospace label).
3. **6 observatory pages wired** — sleep, glucose, nutrition, training, physical, mind. 11 charts total receive the band:
   - Raw SVG: 1 (sleep architecture)
   - Raw Canvas: 5 (sleep trend, glucose trend, nutrition trend, training trend, mind mood)
   - Chart.js (via plugin): 5 (physical weight + 2 dual-axis, training modality + steps, mind sentiment + vice timeline)
4. **Training week→date adapter** inlined for the weekly-aggregated trend chart (data uses `week` not `date`).

## Acceptance vs. spec

| Criterion | Status |
|---|---|
| Visible band Apr 12 → May 1 | ✅ shipped |
| Conditional render (7d window hides band) | ✅ early-return on out-of-window |
| Band sits behind data | ✅ insertBefore for SVG, render-order for Canvas, beforeDatasetsDraw for Chart.js |
| Tooltip on hover | ✅ SVG `<title>` (Chart.js: native tooltip system unaffected) |
| Mobile-safe label (≤60px hides label) | ✅ width gate |
| No JS errors | ✅ Node syntax check passes for all 15 inline blocks across 6 pages |
| Visual_qa.py screenshot | ⚠️ deferred — site is gated by cf-auth, headless tooling can't reach gated pages without auth handshake. **Manual visual check required Monday morning.** |

## Deploy

- `bash deploy/sync_site_to_s3.sh` — uploaded.
- CloudFront invalidation `IE64QQ3BEV6FAWEUOQ1PL0F0BZ` — created.

## Rollback

Purely additive: new file + new CSS classes + opt-in `if (window.CyclePause)` guarded calls. `git revert <sha> && bash deploy/sync_site_to_s3.sh && aws cloudfront create-invalidation --distribution-id E3S424OXQZ8NBE --paths "/*"`.

## Carry-forward

- **Manual visual check Monday** — open each of the 6 pages in incognito (after auth), confirm band appears in 30d/90d mode, hidden in 7d mode, no console errors.
- **Follow-ups** (per spec §10): config-driven pauses (JSON), DDB-backed pauses (`/api/cycle_markers`), pre/post-pause indicators, Discoveries page integration, public Pause Mode banner (WR-47 phase 2).

---

**Previous handover (v6.8.9 — Phase A-D pre-Monday readiness sweep):** see [HANDOVER_v6.8.9.md](HANDOVER_v6.8.9.md).
