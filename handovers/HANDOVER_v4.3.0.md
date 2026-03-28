# Handover — v4.3.0 (2026-03-28)

## Session Summary
Major implementation session: reader engagement (4 phases), BL-02 labs page, OG image Lambda, privacy filters, architectural fixes, and UI polish. All deployed to production.

## What Was Built

### New Infrastructure
- **og-image-generator Lambda** — 6 PNG OG images daily via Pillow + TTF fonts. EventBridge 19:30 UTC. IAM role + Pillow layer created. Added to CDK operational stack.
- **`/api/labs`** — reads `dashboard/matthew/clinical.json` from S3
- **`/api/changes-since?ts=EPOCH`** — delta summary for returning visitors
- **`/api/observatory_week?domain=X`** — 7-day domain summaries (5 domains)

### New Pages
- **`/labs/`** — 74 biomarkers, 18 categories, accordion, flag badges, disclaimer
- **`/recap/`** — weekly recap from existing endpoints, vital signs + domain highlights

### Reader Engagement (engagement.js)
- Phase 1: freshness indicators, "This Week" cards, sparklines, reading paths
- Phase 2: guided path progress bar, dynamic observatory selection, enhanced CTA
- Phase 3: weekly recap page
- Phase 4: Pulse activity feed on homepage

### Privacy
- `public: false` challenge filtering (server + client)
- `isBlocked` keyword filter on mind page vice streaks
- Behavioral signals removed from status page

### HP-12/13
- `elena_hero_line` wired through daily brief → public_stats.json
- OG image generator with page-specific share cards

## What Changed (Architectural)
- CSS/JS cache reduced from 1-year to 1-day
- OG image Lambda added to CDK operational stack
- Site-api CDK env vars expanded (S3_BUCKET, S3_REGION, CORS_ORIGIN)
- `.gitignore` updated for CLAUDE_CODE_BRIEF files

## Known Issues / Deferred
- **Site API monolith** (4700+ lines, 60 routes) — defer split to post-launch
- **Site API endpoint tests** — zero tests for 60 endpoints, multi-session project
- **Dual public_stats.json writers** — output_writers + site_writer both called
- **Guided path** may need CSS tuning if still not visible on some devices

## Platform Stats
- 61 Lambdas, 110 MCP tools, 26 data sources, 7 CDK stacks
- Version: v4.3.0
