# Handover — v3.9.9 (2026-03-24)

> Prior: handovers/HANDOVER_v3.9.8.md

## SESSION SUMMARY
Content consistency architecture (ADR-034): built a 3-layer system to eliminate the "change one fact, edit 54 files" problem. Also: doc sync (17 tasks flipped in PROJECT_PLAN), public_stats.json staleness permanently fixed (site_writer.py in shared layer v11), OE-09 doc consolidation completed.

## WHAT WAS BUILT (ADR-034)

### Foundation files (all committed, NOT yet deployed to S3):
1. **`site/assets/js/site_constants.js`** — single source of truth for all factual content. Journey constants (302, 185, dates, phase), platform counts, bios, OG descriptions, reading paths. Auto-injects into `data-const="key.path"` HTML attributes.
2. **`site/assets/js/components.js`** — shared structural components (nav, mobile overlay, footer, bottom-nav, subscribe CTA, reading path). Pages use mount-point divs: `<div id="amj-nav">`, `<div id="amj-footer">`, etc.
3. **`site/data/content_manifest.json`** — inventory of every journey-sensitive paragraph across the site. Categories: constant, api_driven, prose_with_facts, narrative, archive. Includes `fragile_strings` list for CI.
4. **`site/data/data_sources.json`** — 19-source registry. Replaces per-page hardcoded source lists. Caught factual error: methodology/ lists "Oura" which isn't a data source.
5. **`deploy/lint_site_content.py`** — CI validator for data-const resolution, fragile string detection, source count consistency.
6. **`deploy/migrate_page_to_components.py`** — mechanical migration tool. Tested: `--all --dry-run` shows 50/50 pages eligible, avg 30% size reduction.

### How the component system works:
- **Before**: Every page has ~200 lines of duplicated nav/footer/CTA HTML inline
- **After**: Pages have 5 mount-point divs + 3 script includes. Components.js injects the HTML at runtime.
- **Migration tool**: `python3 deploy/migrate_page_to_components.py <file>` handles the mechanical transformation. `--all` does all pages. `--dry-run` previews.
- **Constants injection**: Add `data-const="journey.start_weight"` to a `<span>` and site_constants.js replaces its textContent on load.

## NEXT SESSION: PAGE MIGRATION

### Recommended batch order:
1. **Batch 1 (high-value):** `about/index.html`, `platform/index.html`, `methodology/index.html` — most hardcoded constants, biggest benefit from data-const
2. **Batch 2 (homepage):** `index.html` — most visible page
3. **Batch 3 (data pages):** `live/`, `character/`, `habits/`, `achievements/`, `explorer/`
4. **Batch 4 (everything else):** remaining ~40 pages — mechanical

### Per-page migration workflow:
```bash
# 1. Run migration (strips inline chrome, adds mount-point divs)
python3 deploy/migrate_page_to_components.py site/about/index.html

# 2. Manually add data-const attributes to hardcoded values in page content
#    Example: <span>302</span> → <span data-const="journey.start_weight">302</span>
#    Use content_manifest.json to find what needs tagging

# 3. Verify in browser
cd site && python3 -m http.server 8000
# Check: nav renders, footer renders, subscribe CTA works, reading path appears

# 4. Add page to MIGRATED_PAGES in deploy/lint_site_content.py
# 5. Run lint: python3 deploy/lint_site_content.py
# 6. Deploy: bash deploy/sync_site_to_s3.sh
```

### Pages that need manual inspection (migration script only added script tags):
- `journal/archive/index.html` — different HTML structure for nav/footer
- `journal/index.html` — same
- `progress/index.html` — same
- `results/index.html` — same
- `start/index.html` — same

### Known issues to fix during migration:
- **methodology/** source card grid lists "Oura" — not a data source; should use data_sources.json
- **platform/** arch grade hardcoded "A" — should be from site_constants or public_stats.json
- **about/** sidebar note says "January 2026" — should say "February 2026" (journey started 2026-02-22)
- **about/** Lambda count says "48" — now 50

## OTHER WORK COMPLETED THIS SESSION

### public_stats.json permanent fix
- **Root cause**: `site_writer.py` wasn't in the shared Lambda layer. Daily brief does `from site_writer import write_public_stats` inside silent try/except → ModuleNotFoundError after every deploy.
- **Fix**: Added `site_writer.py` to shared layer v11 (build_layer.sh + ci/lambda_map.json + p3_build_shared_utils_layer.sh). CDK deployed. Layer attached to all 15 consumers.
- **Immediate**: Ran `python3 deploy/fix_public_stats.py --write` for instant refresh.
- **Tomorrow's daily brief** will write fresh public_stats.json automatically.

### CI/CD p3 scripts restored
- `deploy/p3_build_shared_utils_layer.sh` and `deploy/p3_attach_shared_utils_layer.sh` were in `deploy/archive/20260311/` but CI/CD pipeline references `deploy/`. Restored with updated module/consumer lists.

### Doc sync
- PROJECT_PLAN: 17 task IDs flipped ⬜→✅ (CHAR-1/2/3/6, PLAT-2, PROTO-2/4, EXP-1, HAB-4, BOARD-2, NEW-1/2/3/4, HOME-2/3, PROTO-3)
- REDESIGN_SPEC: 4 "still needed" backend endpoints → ✅ done; Phase 2/3 updated
- OE-09: marked done. FEATURES.md + USER_GUIDE.md already removed; dead refs cleaned.
- ONBOARDING + PLATFORM_GUIDE + MCP_TOOL_CATALOG: version bumps, Google Calendar retirement, dead refs

## PENDING / CARRY FORWARD
- **ADR-034 page migration**: Foundation committed, pages NOT yet migrated. See "NEXT SESSION" above.
- **OG meta tag sync**: JS can't modify meta tags for crawlers. Needs either a build-time replacement script or Lambda@Edge injection. Deferred — works fine for now since OG tags are manually set per page.
- **CHRON-3/4**: Chronicle generation fix + approval workflow (unchanged from prior sessions)
- **G-8**: Privacy page email confirmation (Matthew)
- **Methodology/ Oura error**: Source card grid lists Oura — needs fixing during page migration
- **SIMP-1 Phase 2 + ADR-025 cleanup**: ~Apr 13
- **Withings OAuth**: No weight data since Mar 7 — may need `python3 setup/fix_withings_oauth.py`
