# Handover — Observatory V2 Phase 1+ Chart Upgrades v4.6.0

**Date:** 2026-03-31
**Scope:** Data-first visual chart overhaul across 4 observatory pages

## What Changed

Introduced Chart.js 4.x via CDN across all observatory pages. Built 10 new chart sections spanning Phase 1, Phase 3, and Phase 4 of the Observatory V2 spec (`docs/OBSERVATORY_V2_SPEC.md`).

### New Page: Physical Observatory (`site/physical/index.html`)
- Hero: 4 gauge rings (current weight, total lost, weekly rate, progress %)
- Weight trajectory chart — daily points + 7-day moving average + start/goal reference lines
- Toggle: 30d / 90d / Full Journey views
- Key metrics row: Start → Current → Goal, total lost, rate/week, est. goal date
- Weight vs. calories dual-axis chart (weight MA left Y, daily calories bars right Y)
- Weight vs. training volume dual-axis chart (weight MA left Y, daily training min bars right Y)

### Nutrition Page — 30-Day Macro Stacked Bar + Donut
- Stacked bar: protein (green), carbs (amber), fat (rose) as calories with TDEE reference line
- Macro ratio donut with center text (avg cal/day)
- Auto-generated insight about protein % of calories

### Training Page — 3 New Charts
- Daily exercise minutes by modality — 8 color stacked bar, dynamic legend, 60-min target line
- Daily step count — 30-day bar chart with weekend distinction, <7500 red, 7-day MA, reference lines
- Strength volume trend — 12-week bar chart from `/api/strength_deep_dive`

### Mind Page — State of Mind + Meditation
- State of Mind sparkline (30d valence) + distribution donut (Good/Neutral/Low/Untracked)
- Meditation calendar (current month grid, proportional dots) + metrics row

### API Changes (`lambdas/site_api_lambda.py`)
- `training_overview`: `daily_steps_trend` expanded 14→30 days, added `is_weekend`
- `training_overview`: added `daily_modality_minutes_30d[]` (8 modalities × 30 days)
- `mind_overview`: added `meditation` field (Apple Health breathwork data)

### Navigation
- `/physical/` added to nav menu, bottom nav, badge map, reading path chain

## Files Modified
- `site/physical/index.html` — **new file**
- `site/nutrition/index.html` — Chart.js CDN + macro stacked bar + donut
- `site/training/index.html` — Chart.js CDN + modality + steps + volume charts
- `site/mind/index.html` — Chart.js CDN + state of mind + meditation sections
- `site/assets/js/components.js` — Physical in nav menu
- `site/assets/js/nav.js` — Physical in bottom nav + badge map + reading paths
- `lambdas/site_api_lambda.py` — API extensions

## Deploy Status
- Lambda deployed: `life-platform-site-api`
- Site synced to S3 (both prefixes)
- CloudFront invalidated (both distributions)

## Not Done (Blocked)
- **P1 Item 3**: Journal theme heatmap — no theme extraction / sentiment API
- **P1 Item 8**: Sentiment trend line 90d — no sentiment data
- **P2**: AI expert voice sections — needs new AI analysis Lambda endpoints
- **P3**: DEXA / tape measurements — no data source
- **P3**: Vice streak timeline — needs historical streak data
- **P4**: Breathwork x HRV correlation — needs cross-source correlation compute

## BL-04: Field Notes — Phase 0 Complete
- `tool_get_field_notes` + `tool_log_field_note_response` added to `mcp/tools_lifestyle.py`
- DynamoDB: `USER#matthew#SOURCE#field_notes`, SK `WEEK#YYYY-WNN`
- `update_item` pattern ensures Matthew's response never overwrites AI-generated fields
- Test record seeded at `WEEK#2026-W01` for Claude Desktop verification
- **Phase 1 (generate Lambda) not started — awaiting confirmation**

## BL-03: The Ledger — Phase 0 Complete
- `config/ledger.json` uploaded to S3 (placeholder causes — update before launch)
- `tool_log_ledger_entry` added to `mcp/tools_lifestyle.py`
- DynamoDB: `USER#matthew#SOURCE#ledger`, SK `LEDGER#<ts>` + `TOTALS#current`
- Auto-resolves bounty/punishment amounts and cause from source records or config defaults
- Tested: $50 bounty → Northwest Harvest logged + totals updated correctly
- **Phase 1 (API endpoint) not started — awaiting confirmation**

## MCP Tool Count
115 tools registered (was 112, added 3: get_field_notes, log_field_note_response, log_ledger_entry)

## Data Note
Most charts show empty/zero data until April 1 (Day 1) due to EXPERIMENT_START clamp. Physical weight chart works now (33 Withings readings). All charts auto-populate once ingestion begins.
