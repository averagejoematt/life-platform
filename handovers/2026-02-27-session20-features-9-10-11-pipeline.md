# Session 20 — Features #9, #10, #11 + Pipeline Integration + Hotfix

**Date:** 2026-02-27  
**Version:** v2.36.0  
**Duration:** ~1 session  

---

## What Was Done

### Features #9, #10, #11 (MCP tools)
- **#9 Supplement & Medication Log** — 3 MCP tools: `log_supplement`, `get_supplement_log`, `get_supplement_correlation`. New DynamoDB partition `USER#matthew#SOURCE#supplements`. Supports name, dose, unit, timing, category, notes. Correlation tool compares supplement-on vs supplement-off days across 11 health metrics.
- **#10 Weather & Seasonal Correlation** — 1 MCP tool: `get_weather_correlation`. Fetches Seattle weather from Open-Meteo (free, no auth), caches in DynamoDB `USER#matthew#SOURCE#weather`. Correlates 7 weather variables (temp, humidity, precip, daylight, sunshine, pressure, UV) with health + journal metrics. Added `import urllib.request` to MCP server.
- **#11 Training Periodization Planner** — 1 MCP tool: `get_training_periodization`. Weekly training analysis from Strava + MacroFactor workouts. Classifies weeks as base/build/peak/deload. Detects deload need (4+ consecutive loading weeks), checks training polarization (Seiler 80/20), tracks progressive overload, Zone 2 adherence.

### Hotfix — Misplaced Tool Functions
- 8 tool functions (from v2.34.0 sessions) were defined AFTER the TOOLS dict, causing `NameError: name 'tool_get_day_type_analysis' is not defined` at Lambda import. **MCP server was completely down.**
- Fix: `deploy/hotfix_move_functions.sh` relocated all 8 functions before the TOOLS dict.
- Affected functions: `tool_get_glucose_meal_response`, `tool_get_day_type_analysis`, `tool_get_fasting_glucose_validation`, `tool_create_experiment`, `tool_list_experiments`, `tool_get_experiment_results`, `tool_end_experiment`, `tool_get_health_trajectory`.
- **Root cause:** Prior session deploy scripts inserted tool functions at the end of the file rather than before the TOOLS dict. Future deploy scripts must always insert before `TOOLS = {`.

### Pipeline Integration
- **New Lambda:** `weather-data-ingestion` (128 MB, 30s timeout, Python 3.12)
  - IAM role: `lambda-weather-role` (DynamoDB write + S3 write + SQS DLQ + CloudWatch)
  - EventBridge: `weather-daily-ingestion` at 5:45 AM PT (cron 13:45 UTC) — runs before all other ingestion
  - Fetches yesterday + today from Open-Meteo, writes to DynamoDB, backs up raw to S3
  - DLQ attached to `life-platform-ingestion-dlq`
- **Daily Brief v2.4:** 15 → 17 sections
  - 💊 Supplements section (after habits, before CGM): today's logged supplements + 7-day adherence chips
  - 🌤 Weather Context section (after gait, before weight phase): temp, daylight, precip, pressure grid with Huberman/Attia coaching nudges
  - Both sections conditional — only render when data exists
  - **Important:** Daily Brief handler is `lambda_function.lambda_handler` — zip must contain `lambda_function.py`, not `daily_brief_lambda.py`

### Documentation
- CHANGELOG.md: v2.36.0 entry with all features + pipeline integration
- PROJECT_PLAN.md: version bump, roadmap items #9/#10/#11 struck through, Daily Brief v2.4
- SCHEMA.md: added `supplements` and `weather` source schemas, updated source list and SOT block
- ARCHITECTURE.md: added weather Lambda/EventBridge/IAM, updated tool counts, diagram, Daily Brief description

---

## Current State

- **Version:** v2.36.0
- **MCP Tools:** 85 (was 80)
- **Lambdas:** 21 (was 20)
- **Data Sources:** 18 (was 16)
- **EventBridge Rules:** 20 (was 19)
- **Daily Brief:** v2.4, 17 sections
- **Cost:** ~$5/month (weather Lambda adds negligible cost)

---

## Deployment Order Used

1. `deploy/deploy_feature9_supplement_log.sh` → MCP: +3 tools
2. `deploy/deploy_feature10_weather.sh` → MCP: +1 tool
3. `deploy/deploy_feature11_periodization.sh` → MCP: +1 tool (hit ResourceConflictException, re-ran manually)
4. `deploy/hotfix_move_functions.sh` → Fixed 8 misplaced functions, restored MCP server
5. `deploy/deploy_weather_lambda.sh` → New Lambda + IAM + EventBridge
6. `deploy/deploy_brief_supplements_weather.sh` → Daily Brief patch (required handler filename fix)

---

## Important Notes

- **Deploy script convention:** Tool functions MUST be inserted BEFORE `TOOLS = {` in mcp_server.py. Inserting after causes NameError at import.
- **Daily Brief zip convention:** Handler expects `lambda_function.py` inside the zip, not `daily_brief_lambda.py`. Local source stays as `daily_brief_lambda.py` but must be copied to `lambda_function.py` when packaging.
- **Weather data:** 2 days already in DynamoDB (Feb 26-27) from smoke test. Lambda will auto-populate going forward at 5:45 AM PT.
- **Supplement data:** Empty until Matthew starts logging via `log_supplement` in Claude Desktop.
- **Lambda ResourceConflictException:** When deploying multiple MCP updates in sequence, wait ~10s between deploys for Lambda to finish updating.

---

## Roadmap Status

**Completed (11 of 27):** #3, #4, #5, #6, #7, #8, #9, #10, #11
**Tier 1 remaining (2):** #1 Monarch Money, #2 Google Calendar
**Tier 2 remaining (14):** #12-#25
**Polish (2):** #26-#27

---

## Next Session Suggestions

1. **#12 Social Connection Scoring** — Haiku-enriched journal entries with social interaction quality. Low effort, high impact for Seligman PERMA wellbeing model.
2. **#13 Annual Health Report** — Year-in-review email. Good candidate for March 1st monthly digest enhancement.
3. **Weather backfill** — Run weather Lambda with `{"start_date": "2023-07-23", "end_date": "2026-02-25"}` to populate historical weather for correlation analysis.
4. **CloudWatch alarm** for weather Lambda (currently no alarm configured).
5. **Freshness checker** — Add `weather` source to freshness thresholds.
