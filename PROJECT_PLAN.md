# Life Platform — Project Plan

> Living document. Update as work is completed or priorities shift.

---

## ✅ Completed

### Infrastructure
- DynamoDB table `life-platform` provisioned (us-west-2, account 205930651321)
- MCP server Lambda `life-platform-mcp` deployed with API Gateway + secret key auth
- MCP bridge (`mcp_bridge.py`) configured for local Claude Desktop integration

### Data Sources (live ingestion)
- **Whoop** — daily recovery, HRV, strain, sleep; Lambda + scheduler deployed
- **Withings** — daily weight/body composition; Lambda + scheduler deployed
- **Strava** — activities with full nested detail (name, sport_type, distance, elevation, HR, watts); backfill + live Lambda deployed
- **Todoist** — daily task completion; Lambda + scheduler deployed
- **Apple Health** — steps, active calories, resting HR, HRV, sleep; backfill + Lambda deployed

### MCP Server versions
| Version | Key changes |
|---------|-------------|
| 1.0.0 | Initial release — core 5 tools |
| 1.2.0 | Added `search_activities` tool |
| 1.3.0 | Added `get_field_stats`; improved `find_days` + `search_activities` descriptions to fix tool-selection bugs |
| 1.3.1 | `get_field_stats` enriched with top-5 highs/lows + trend direction; `search_activities` adds percentile rank + context flags; descriptions updated to prevent sport_type assumption on distance/achievement queries |

---

## 🔄 In Progress / Next Actions

### Deploy v1.3.1
```bash
cd /Users/matthewwalker/Documents/Claude/life-platform
zip /tmp/lp-deploy.zip mcp_server.py
aws lambda update-function-code \
  --function-name life-platform-mcp \
  --zip-file fileb:///tmp/lp-deploy.zip \
  --region us-west-2
```

---

## 📋 Backlog

### HIGH — Data Gaps

#### Hevy Strength Training Backfill
**Why:** Bench press, squat, deadlift, and all lifting history is not in the platform.
Apple Health receives workout summaries from Hevy but not individual exercise/set/rep data.
**Plan:**
1. Export full Hevy history (CSV or JSON export from the app)
2. Write a one-time backfill script (similar to `backfill_strava.py`) to load into DynamoDB under a new `hevy` source key
3. Schema should capture: date, exercise_name, set_number, weight_lbs, reps, estimated_1rm
4. Note: Matthew has since migrated workouts to **MacroFactor** — decide whether to also add MacroFactor as an ongoing workout source, or continue using Hevy for historical only
5. Add `hevy` to the SOURCES list in mcp_server.py and expose via existing tools

**Priority:** Medium-High — needed before strength journey questions can be answered accurately.

---

### MEDIUM — Platform Improvements

#### MacroFactor Integration (ongoing nutrition + workout source)
**Why:** MacroFactor is now the primary app for nutrition tracking and logging workouts. It has richer macro/calorie data than other sources.
**Plan:**
- Investigate MacroFactor export/API options
- If API available: build Lambda + scheduler (same pattern as Whoop/Withings)
- If export only: build a periodic manual-upload flow
- Fields of interest: daily calories, protein/carbs/fat, body weight, workout logs with exercises

#### Strava Activity Renaming
**Why:** Machu Picchu hike and Mailbox Peak hike are stored as generic "Morning Hike" — name-based search fails.
**Fix:** Rename them directly in the Strava app/website. No code change needed.
- They can currently be found via `search_activities(sort_by=total_elevation_gain_feet)` as the percentile rank will flag them as exceptional.

#### Weekly Insights Digest
**Why:** The original vision for the platform — a weekly summary email/notification aligned with Project40 pillars (health, fitness, work, etc.)
**Plan:**
- Build a scheduled Lambda (runs Sunday evening) that calls MCP tools internally
- Generates a structured digest: recovery trend, weight trend, biggest workout of the week, task completion rate
- Deliver via email (SES) or Notion page

---

### LOW — Future Sources

| Source | Data | Notes |
|--------|------|-------|
| MacroFactor | Nutrition macros, calories, meal logging | High value — investigate API |
| Garmin | GPS, sleep, HRV (overlaps Whoop) | Lower priority given Whoop coverage |
| Monarch Money | Spending, savings, net worth | Financial pillar of Project40 |
| Oura (if adopted) | Sleep stages, readiness | Only if replacing Whoop |

---

## 🐛 Known Issues / Limitations

- **Bench press PRs** — not in system; requires Hevy backfill (see above)
- **Machu Picchu / Mailbox Peak** — not name-searchable; workaround is elevation sort with percentile context
- **Apple Health workout data** — only summary-level (calories, duration); no exercise-by-exercise detail
- **Withings weight** — some early readings may be missing; coverage starts ~2019

---

## 💡 Architecture Notes

- All data stored in single DynamoDB table with PK `USER#matthew#SOURCE#<source>`, SK `DATE#YYYY-MM-DD`
- Strava activities stored nested under day record (not individual items) — `search_activities` flattens at query time
- MCP server is stateless Lambda — no caching; cold start ~1-2s
- API key stored in Secrets Manager (`life-platform/mcp-api-key`)
