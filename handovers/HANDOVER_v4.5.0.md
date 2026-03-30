# Handover — v4.5.0

**Date:** 2026-03-30
**Session:** Observatory Upgrade Phase 1+2 + Full Usability Study Remediation

---

## What Changed

### Observatory Upgrade (Phase 1 + 2)
- **Physical page**: 6 hero gauges (was 4), modality deep-dive cards replacing simple chips, walking & steps section, breathwork section, weekly physical volume 7-day heatmap, strength deep-dive, running teaser
- **Nutrition page**: protein source breakdown, weekday vs weekend comparison, eating window, caloric periodization, "What I Actually Eat" gallery, food delivery analysis, macro deep-dives (carbs/fats/fiber)
- **4 new API endpoints**: `/api/weekly_physical_summary`, `/api/protein_sources`, `/api/strength_deep_dive`, `/api/food_delivery_overview`
- **2 extended APIs**: `training_overview` (+modality_breakdown, walking, breathwork), `nutrition_overview` (+weekday_vs_weekend, eating_window, periodization)

### Usability Study (15 of 20 items implemented)
- Start Here modal (P0-1), Board transparency banners (P0-2), Homepage hero rewrite (P0-3), Labs observatory overhaul (P0-4)
- Builders meta-story + AI partnership (P1-1), Elena Voss attribution (P1-2), Methodology AI governance + evidence badges (P1-3), Share button (P1-5)
- PubMed links on protocols (P2-2), Community page (P2-3)
- Protocol/Experiment definitions (MISC-1), Mobile audit (MISC-2), Elena pull-quotes on observatories (MISC-3), Currently Testing card (MISC-4), Matt bio (MISC-6)

### Bug Fixes
- `_query_source` now returns `[]` when start_date > end_date (EXPERIMENT_START in future)
- Homepage hero flexbox layout replacing grid (eliminated vertical gap)

---

## What's Pending

### From Prior Sessions (not addressed this session)
- **Schedule ordering fix**: `daily_insight_compute` (10:20) runs before `daily_metrics_compute` (10:25) — swap cron schedules in CDK
- **Lambda concurrency quota**: needs AWS Support Console request, then uncomment ReservedConcurrentExecutions
- **OG image Lambda CDK import**: CLI-created, needs CDK resource import

### From Usability Brief (deferred)
- **P1-6**: Audience-specific landing pages (covered by Start Here modal)
- **P2-1**: What I Eat in a Day page (covered by nutrition gallery)
- **P2-4**: Data Export / API access page (endpoints exist, docs page deferred)

### From Observatory Spec (Phase 3)
- GPS route gallery with Strava polylines
- Interactive modality explorer
- Sub-macro breakdowns (complex vs simple carbs, sat vs unsat fat)
- Supplement × micronutrient gap overlap analysis

---

## Key Numbers

| Metric | Value |
|--------|-------|
| Site pages | 68 |
| Lambdas | 60 |
| MCP tools (registered) | 118 |
| MCP tool modules | 26 |
| CDK stacks | 8 |
| API endpoints (site-api) | 65+ |
| Data sources | 26 |
| Monthly cost | ~$13 |

---

## Deploy State
- Lambda `life-platform-site-api` deployed with all new endpoints
- Site synced to S3 with CloudFront invalidation
- All changes live at averagejoematt.com
