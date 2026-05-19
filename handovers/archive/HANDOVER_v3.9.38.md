# Handover v3.9.38 — Visual Asset System + Site Integration

**Date**: 2026-03-26
**Session focus**: Product Board visual strategy session → 65 SVG asset generation → wiring into 3 site pages → S3 deploy

---

## What Shipped

### Product Board Visual Strategy Session
Full 8-persona Product Board convened to evaluate the site's visual identity gap. Board consensus: site has strong design system (tokens, Signal Doctrine) but zero custom illustrations, badges are emoji, icons are inline SVG or emoji, no avatar exists. Board defined a 5-phase visual execution plan with immediate Phase A (geometric SVGs) and roadmapped Phase B (rich illustrated via Recraft/Midjourney).

### Creative Direction Document
`docs/VISUAL_ASSET_BRIEF.md` — Comprehensive brief defining every visual asset needed across 6 categories: 40 achievement badges, 25+ custom icons, avatar in 5-8 data-responsive states, 8 page hero illustrations, board member portraits, and OG image templates. Includes exact color palette constraints from tokens.css, AI prompt templates for each generation tool, and integration specifications. Designed to be handed directly to Recraft/Midjourney/Kittl.

### 65 SVG Assets Generated
- **26 custom icons** in `site/assets/icons/custom/` — geometric, 24×24, stroke-only, `currentColor` adaptable. Covers all 7 pillars, 8 live page glyphs, plus streak/experiment/discovery/supplement/CGM/blood/steps/zone2/level-up/tier/alert/calendar/trend icons.
- **39 achievement badges** in `site/assets/img/badges/` — geometric Phase A style (military insignia meets data terminal). Categories: streaks (5), levels (6), weight milestones (8), data consistency (4), experiments (4), challenges (5), vice streaks (4), running (3).
- **SVG icon sprite** at `site/assets/icons/custom/sprite.svg` for `<use>` reference pattern.
- **Generator script** at `deploy/generate_visual_assets.py` — regenerates entire set from source definitions.

### Decisions Logged
`docs/VISUAL_DECISIONS.md`:
1. Avatar style: **editorial illustration** (NYT magazine profile)
2. Badge approach: **Phase A geometric now** (Claude-generated), Phase B rich illustrated roadmapped
3. Photo reference: Matthew will provide for avatar generation
4. Light mode: **YES** — all assets must work on both dark (#080c0a) and light (#f5f5f0)
5. Tool budget: Approved (~$25-55/mo for Recraft + Midjourney sprint)

### Site Integration — 3 Pages Updated
**Milestones page** (`site/achievements/index.html`):
- `BADGE_ICONS` emoji dict → `badgeSvgPath()` function loading SVG files
- `renderBadge()` renders `<img src="/assets/img/badges/badge_{id}.svg">` instead of emoji
- `CATEGORY_META` emoji → custom icon `<img>` tags
- Locked state: existing CSS `grayscale(1) opacity(0.5)` filter works on `<img>` elements

**Live page** (`site/live/index.html`):
- 60-line `GLYPH_ICONS` inline SVG functions → 10-line CSS mask-image system
- `GLYPH_ICON_MAP` maps glyph keys to icon file names
- `glyphIcon()` renders `<div class="glyph__icn">` with CSS `mask-image: url(...)` 
- State coloring via `.glyph__ring--{state} .glyph__icn { background-color: ... }`

**Character page** (`site/character/index.html`):
- All 13 hardcoded badge emoji in HTML → `<img>` tags referencing badge SVGs
- Added `.badge-card__icon img` CSS for proper sizing (48×48)

### Deploy Script
`deploy/deploy_visual_assets.sh` — S3 sync for icons + badges + updated HTML pages, plus CloudFront invalidation. Sets proper `content-type: image/svg+xml` and caching headers.

---

## Deploy Sequence (Already Run)

```bash
# 1. Generate assets
python3 deploy/generate_visual_assets.py

# 2. Copy edited pages (downloaded from Claude outputs)
cp ~/Downloads/achievements_index.html site/achievements/index.html
cp ~/Downloads/live_index.html site/live/index.html
cp ~/Downloads/character_index.html site/character/index.html

# 3. Deploy to S3 + CloudFront
bash deploy/deploy_visual_assets.sh

# 4. Commit
git add -A && git commit -m "feat: wire custom SVG badges + icons into milestones, live, and character pages" && git push
```

---

## Current State

- **Platform version**: v3.9.38
- **65 SVG assets** live on CloudFront
- **3 pages** using custom visual assets (milestones, live, character)
- **Creative brief** ready for Phase B rich illustration generation
- All prior v3.9.37 items still apply (April 1 go-live prep, warmup script, subscribe flow test)

---

## On the Horizon

### Visual System Phase B (next visual session)
- Matthew provides photo reference → avatar generation via Midjourney/Recraft
- Rich illustrated badge upgrade using `docs/VISUAL_ASSET_BRIEF.md` prompts
- Page hero illustrations (Home, Story, Character, Live, Chronicle, Milestones, Data Explorer)
- Board member portraits (Product Board 8 personas first)
- OG image templates (page-specific social sharing cards)

### Existing Carry-Forwards
- **SIMP-1 Phase 2 + ADR-025 cleanup** (~April 13 target) — reducing MCP tools to ≤80
- **DISC-7 annotation testing/seeding** — behavioral response annotations on timeline cards
- **observatory.css consolidation** — shared stylesheet exists but needs explicit S3 sync
- **Sleep and Glucose observatory visual overhaul** — apply editorial design pattern
- **get_nutrition MCP tool positional args bug** — carry-forward fix
- **HP-12 backend caller** — `daily_brief_lambda.py` must pass `elena_hero_line` to `write_public_stats()`
- **HP-13** — share card Lambda + dynamic OG image
- **BL-01** — For Builders page (Product Board unanimous #1 backlog pick)
- **BL-02** — Bloodwork/Labs page

---

## Files Created/Modified This Session

### Created
- `docs/VISUAL_ASSET_BRIEF.md` — creative direction document
- `docs/VISUAL_DECISIONS.md` — Matthew's style decisions
- `deploy/generate_visual_assets.py` — SVG asset generator
- `deploy/deploy_visual_assets.sh` — S3/CloudFront deploy script
- `site/assets/icons/custom/*.svg` — 26 icon files + sprite.svg
- `site/assets/img/badges/*.svg` — 39 badge files

### Modified
- `site/achievements/index.html` — badge SVGs + category icons
- `site/live/index.html` — mask-image glyph icons
- `site/character/index.html` — badge SVG images
