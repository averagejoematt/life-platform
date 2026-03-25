# Handover — v3.9.19 (2026-03-25)

## Session Summary
**HP-06/HP-12/HP-14 backend + frontend** — Completed three home page evolution tasks from the Product Board sprint (HOME_EVOLUTION_SPEC.md). HP-06 adds `?featured=true&limit=3` query param support to `/api/correlations` so the homepage dynamic discoveries JS (already deployed in v3.9.18) now pulls live correlation data. HP-12 wires `elena_hero_line` into the `public_stats.json` pipeline via `site_writer.py`. HP-14 adds `chronicle_recent` array generation to the pipeline and a new "Recent Chronicles" 3-card section on the homepage.

## What Changed

### Modified Files
- `lambdas/site_api_lambda.py` — `handle_correlations()` accepts event, supports `?featured=true&limit=N`, added `p`/`description`/`direction`/`metric_a`/`metric_b` fields, early-routed in lambda_handler
- `lambdas/site_writer.py` — new `elena_hero_line` param on `write_public_stats()`, new `_get_recent_chronicles()` helper, `chronicle_recent` + `elena_hero_line` in payload
- `site/index.html` — new `<section id="chronicle-cards">` between Discoveries and Day 1 vs Today, JS loader, responsive mobile styles
- `docs/CHANGELOG.md` — v3.9.19 entry
- `deploy/sync_doc_metadata.py` — version bump to v3.9.19

## Key Decisions
- HP-06 featured mode filters to `p<0.05 OR fdr_significant`, falls back to top |r| if no significant pairs found
- HP-06 auto-generates description text for correlations missing one in DynamoDB
- HP-14 chronicle cards JS tries `window.__amjStats` first, then falls back to direct `public_stats.json` fetch after 1.2s timeout
- HP-12 `elena_hero_line` will be null until a caller passes it — the natural integration point is the wednesday-chronicle Lambda

## Deployed
- site_api_lambda ✅
- Shared layer v13 ✅ (attached to all 15 consumers)
- Site HTML ✅ + CloudFront invalidated

## Task Status (HOME_EVOLUTION_SPEC.md)

### Sprint A (P0) ✅ ALL DONE
HP-01 ✅ HP-02 ✅ HP-03 ✅ HP-04 ✅ HP-05 ✅ HP-07 ✅

### Sprint B (P1) ✅ ALL DONE
HP-15 ✅ HP-08 ✅ GR-01 ✅ HP-06 ✅

### Sprint C (P2) — 6/7 DONE
HP-10 ✅ HP-11 ✅ HP-12 ✅ GR-02 ✅ HP-14 ✅
HP-09 ❌ HP-13 ❌

### Sprint D (Backlog Pages) — NOT STARTED
BL-01 ❌ BL-02 ❌

### Sprint E (Future) — NOT STARTED
BL-06 ❌ BL-05 ❌ (gated on 200 subs)

## What's Next (Priority Order)

### Immediate (next session):
1. **Wire elena_hero_line into wednesday-chronicle Lambda** — generate a one-liner from the weekly Chronicle and pass it to `write_public_stats(elena_hero_line="...")` so HP-12 displays on the homepage
2. **HP-09**: Section consolidation (7→5) — major HTML restructure, dedicated session
3. **HP-13**: Share card Lambda (PULSE-D1) + dynamic OG image

### Near-term:
4. **BL-01**: "For Builders" page — unanimous Product Board #1 backlog pick
5. **BL-02**: Bloodwork/Labs page — highest credibility page (Lena Johansson)

### Background:
- **PULSE-B6**: Historical day navigation on Pulse page
- **SIMP-1 Phase 2 + ADR-025 cleanup** — ~April 13, 2026

## Pre-Existing Issues (unchanged)
- 10 integration test failures (pre-existing)
- CHRON-3/4 chronicle generation workflow still open
- G-7/G-8 SES verification still open

## Critical Reminders
- `site_writer.py` is in the **shared Lambda layer** — edits require layer republish + attach (now v13)
- HP-06 dynamic discoveries shows live data now — if the weekly_correlations DynamoDB record has no `description` field, the auto-generator creates one from metric labels
- HP-12 Elena one-liner is hidden by default — shows only when `public_stats.json` has `elena_hero_line` field (non-null)
- HP-14 chronicle cards show fallback message until `chronicle_recent` populates in `public_stats.json` (next daily-brief run)
- Sticky subscribe bar uses localStorage — won't reappear for 7 days after dismissal
- All emoji replaced with SVGs — if adding new feature cards, use inline SVG pattern, not emoji
