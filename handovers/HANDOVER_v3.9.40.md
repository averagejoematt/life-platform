# Handover v3.9.40 — Nav Spacer Architecture + Bug Sweep

**Date**: 2026-03-27
**Session focus**: 5-bug triage, S3 path fix, nav spacer architecture (Tech Board approved), 37-file sweep

---

## What Shipped

### Nav Spacer Architecture (Tech Board Approved — 5-1-1 vote)
- **components.js**: Injects `.nav-spacer` div after nav — single source of truth for fixed-nav clearance
- **base.css**: `.nav-spacer { height: var(--nav-height); flex-shrink: 0; }` class
- **deploy/nav_spacer_sweep.sh**: Automated sweep script handling 3 patterns across 37 files:
  - Pattern A: `calc(var(--nav-height) + var(--space-XX))` → `var(--space-XX)` (most files)
  - Pattern B: `margin-top:var(--nav-height)` on tickers → `margin-top:0` (home, achievements, chronicle)
  - Pattern C: `top:var(--nav-height)` on fixed elements → KEPT (chronicle reading progress bar)

### S3 Path Mismatch Fix
- Challenge catalog + experiment library were uploaded to `config/` but Lambda reads from `site/config/`
- Both now at correct S3 paths — catalogs load on /challenges/ and /experiments/

### Dropdown Heading Visual Distinction
- `.nav__dropdown-heading` in base.css: `font-weight: 700`, `color: var(--accent-dim)`
- "What I Do" / "What I Tested" now clearly distinguishable from clickable items

### Home Page Day 1 vs Today Centering
- Section `text-align: center`, grid `margin: 0 auto`, CTA `justify-content: center`
- Grid interior stays `text-align: left`

### Stale Nav Labels Cleaned
- challenges/index.html pipeline nav: "Active Tests" → "Experiments"
- experiments/index.html CTA: "The Arena" → "Challenges"
- experiments/index.html reading-path: "The Arena" → "Challenges"
- challenges/index.html reading-path: "The Lab" → "Experiments"

---

## Deploy Sequence (Already Run)

```bash
# S3 catalog path fix
aws s3 cp seeds/challenges_catalog.json s3://matthew-life-platform/site/config/challenges_catalog.json
aws s3 cp config/experiment_library.json s3://matthew-life-platform/site/config/experiment_library.json

# Nav spacer sweep (ran deploy/nav_spacer_sweep.sh)
# → Pattern A: 37 files cleaned
# → Pattern B: ticker margin-top removed
# → Pattern C: reading progress kept

# Full site sync + invalidation
aws s3 sync site/ s3://matthew-life-platform/site/ --exclude '*.DS_Store' --exclude '.git/*'
aws cloudfront create-invalidation --distribution-id E3S424OXQZ8NBE --paths "/*"

# Git
git add -A && git commit -m "v3.9.40: ..." && git push
```

---

## Current State

- **Platform version**: v3.9.40
- **66 challenges** in catalog
- **71 experiments** in library
- **105 MCP tools, 52 Lambdas, 19 data sources**
- **37 pages** cleaned of per-page nav-height workarounds
- **Nav spacer** is now the single source of truth for fixed-nav clearance

---

## `/api/character_stats` 503

This is expected pre-April 1. The handler returns 503 when no character sheet record exists for today or yesterday in DynamoDB. Resolves automatically once the character sheet Lambda computes after Day 1.

---

## Before April 1 (Matthew)

1. ⬜ **Test subscribe in browser** — go to averagejoematt.com/subscribe/, enter real email, verify full flow
2. ⬜ **Spot-check pages** — /experiments/, /challenges/, /sleep/, /story/, /character/ (nav spacer spacing)
3. ⬜ **March 31 11:55 PM**: `bash deploy/warmup_lambdas.sh`
4. ⬜ **April 1 morning**: `bash deploy/capture_baseline.sh` (real Day 1 data)

---

## On the Horizon (from ACTION_PLAN_APRIL_LAUNCH.md)

### Post-Launch Week 1
- Challenge catalog brainstorm with board (even more entries)
- Experiment library expansion (more social, supplement timing)
- `/live/` page sparklines + count-up animations
- HP-12: elena_hero_line in public_stats

### Post-Launch Weeks 2-4
- Sleep + Glucose observatory visual overhaul (apply editorial design pattern)
- observatory.css consolidation
- HP-13: share card Lambda + dynamic OG image
- Phase B visual work (avatar, heroes, rich badges)
- Podcast scanner Lambda creation in AWS
- Challenge auto-completion trigger

### Strategic
- SIMP-1 Phase 2 + ADR-025 (~April 13)
- Interactive architecture SVG
- BL-01: Builders page expansion
- BL-02: Bloodwork/Labs observatory

---

## Session Closeout Remaining

1. ⬜ Prepend changelog: `cat docs/changelog_v3940.md docs/CHANGELOG.md > /tmp/cl.md && mv /tmp/cl.md docs/CHANGELOG.md && rm docs/changelog_v3940.md`
2. ⬜ Update `deploy/sync_doc_metadata.py` PLATFORM_FACTS if counts changed
3. ⬜ `git add -A && git commit -m "v3.9.40: Nav spacer architecture + bug sweep" && git push`

---

## Files Created/Modified This Session

### Created
- `deploy/nav_spacer_sweep.sh` — automated 3-pattern nav-height sweep script

### Modified
- `site/assets/js/components.js` — nav spacer div injection
- `site/assets/css/base.css` — .nav-spacer class, dropdown heading styling, breadcrumb revert
- `site/index.html` — Day 1 vs Today centering
- `site/experiments/index.html` — nav-height removed, stale labels fixed
- `site/challenges/index.html` — nav-height removed, stale labels fixed
- 35 additional page HTML files — nav-height clearance removed via sweep script
