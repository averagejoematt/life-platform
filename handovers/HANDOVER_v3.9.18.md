# Handover — v3.9.18 (2026-03-25)

## Session Summary
**Home Page Evolution — Product Board Sprint A+B+C** — Convened full Product Board (8 personas) to review home page. Generated comprehensive implementation spec (`docs/HOME_EVOLUTION_SPEC.md`, 21 tasks across 5 sprints). Executed 14 of 21 tasks in three sprint waves. SEO, subscribe funnel, light-mode colors, dynamic discoveries, SVG glyph system, heartbeat reposition, Elena Voss placeholder, share mechanics.

## What Changed

### New Files
- `docs/HOME_EVOLUTION_SPEC.md` — Full Product Board implementation spec with task IDs, acceptance criteria, board attribution, sprint ordering

### Modified Files
- `site/index.html` — 14 tasks applied across Sprint A (6), B (4), C (4)
- `site/assets/css/tokens.css` — Added `--accent-rgb` / `--amber-rgb` CSS variable triplets (dark + light mode)
- `docs/CHANGELOG.md` — v3.9.18 entry
- `deploy/sync_doc_metadata.py` — Version bump to v3.9.18

## Key Decisions
- **Product Board unanimous**: "For Builders" page (BL-01) is highest-priority backlog item for growth
- **Bloodwork/Labs** (BL-02) is highest-priority for credibility (Lena Johansson)
- **Segmented Subscriptions** (BL-05) gated on reaching 200 confirmed subscribers
- **Section consolidation** (HP-09, 7→5 sections) deferred — needs dedicated session for major restructure
- **Elena Voss hero one-liner** — frontend ready, backend needs `elena_hero_line` field added to `write_public_stats()` in site_writer.py (or weekly digest Lambda)
- **Dynamic Discoveries** — frontend JS ready with graceful fallback. Backend needs `?featured=true&limit=3` parameter support in `/api/correlations` endpoint of `site_api_lambda.py`

## Task Status

### Sprint A (P0) ✅ ALL DONE
HP-01 ✅ HP-02 ✅ HP-03 ✅ HP-04 ✅ HP-05 ✅ HP-07 ✅

### Sprint B (P1) ✅ ALL DONE
HP-15 ✅ HP-08 ✅ GR-01 ✅ HP-06 frontend ✅

### Sprint C (P2) — 4/7 DONE
HP-10 ✅ HP-11 ✅ HP-12 frontend ✅ GR-02 ✅
HP-09 ❌ HP-13 ❌ HP-14 ❌

### Sprint D (Backlog Pages) — NOT STARTED
BL-01 ❌ BL-02 ❌

### Sprint E (Future) — NOT STARTED
BL-06 ❌ BL-05 ❌ (gated on 200 subs)

## What's Next (Priority Order)

### Immediate (next session):
1. **HP-06 backend**: Add `?featured=true&limit=3` support to `/api/correlations` in `site_api_lambda.py` — enables the dynamic discoveries JS that's already deployed
2. **HP-12 backend**: Add `elena_hero_line` field to `write_public_stats()` — enables the Elena Voss one-liner on the home page
3. **HP-14**: Add `chronicle_recent` array to `public_stats.json` + frontend cards

### Near-term:
4. **HP-09**: Section consolidation (7→5) — major HTML restructure, dedicated session
5. **HP-13**: Share card Lambda (PULSE-D1) + dynamic OG image
6. **BL-01**: "For Builders" page — unanimous board #1 backlog pick

### Background:
- **PULSE-B6**: Historical day navigation on Pulse page
- **SIMP-1 Phase 2 + ADR-025 cleanup** — ~April 13, 2026

## Pre-Existing Issues (unchanged from v3.9.17)
- 10 integration test failures (pre-existing)
- CHRON-3/4 chronicle generation workflow still open
- G-7/G-8 SES verification still open

## Critical Reminders
- `site_writer.py` is in the **shared Lambda Layer** — edits require layer republish + attach
- HP-06 dynamic discoveries will show fallback cards until backend `/api/correlations?featured=true` is implemented
- HP-12 Elena one-liner is hidden by default — shows only when `public_stats.json` has `elena_hero_line` field
- Sticky subscribe bar uses localStorage — won't reappear for 7 days after dismissal
- All emoji replaced with SVGs — if adding new feature cards, use inline SVG pattern, not emoji
