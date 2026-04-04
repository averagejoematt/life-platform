# Life Platform — Dependency Graph

> Complete dependency map: which Lambdas depend on which DynamoDB partitions, which MCP tools depend on which data, which emails depend on which compute Lambdas.
> Last updated: 2026-03-30 (v4.5.0)

---

## Data Flow Overview

```
EXTERNAL APIs → INGESTION LAMBDAS → DDB PARTITIONS → COMPUTE LAMBDAS → COMPUTED PARTITIONS → DAILY BRIEF → S3 OUTPUTS → WEBSITE
                                                   ↘                                        ↗
                                                    → MCP TOOLS (read-only query layer) ──→ Claude
```

---

## 1. Ingestion Layer (External API → DynamoDB)

| External Source | Lambda | DDB Partition Written | Schedule (UTC) |
|----------------|--------|----------------------|----------------|
| Whoop API | `whoop_lambda` | `whoop` | 14:00 daily |
| Withings API | `withings_lambda` | `withings` | 14:15 daily |
| Strava API | `strava_lambda` | `strava` | 14:30 daily |
| Eight Sleep API | `eightsleep_lambda` | `eightsleep` | 15:00 daily |
| Garmin (garth) | `garmin_lambda` | `garmin` | 14:00 daily |
| Habitify API | `habitify_lambda` | `habitify`, `supplements` | 14:15 daily |
| Todoist API | `todoist_lambda` | `todoist` | 14:45 daily |
| Notion API | `notion_lambda` | `notion` | 14:00 daily |
| Apple Health webhook | `health_auto_export` | `apple_health`, `state_of_mind` | On webhook |
| Open-Meteo | `weather_handler` | `weather` | 13:45 daily |
| Dropbox → MacroFactor CSV | `dropbox_poll` | `macrofactor` | Every 30 min |
| Food delivery CSV | `food_delivery_lambda` | `food_delivery` | S3 trigger |

---

## 2. Compute Layer (DynamoDB → Computed Results)

Runs daily after ingestion completes. **Order matters** — see critical path below.

| Lambda | Schedule (PT) | Reads | Writes |
|--------|--------------|-------|--------|
| `anomaly_detector` | 09:05 AM | whoop, strava, apple_health, macrofactor, computed_metrics, withings, garmin, travel | `anomaly_detector` |
| `daily_metrics_compute` | 10:25 AM | whoop, strava, macrofactor, apple_health, garmin, withings, habitify, notion, food_delivery | `computed_metrics`, `day_grade`, `habit_scores` |
| `adaptive_mode` | 10:30 AM | notion, `habit_scores`, `day_grade` | `adaptive_mode` |
| `character_sheet` | 10:35 AM | whoop, strava, macrofactor, apple_health, withings, labs, habitify, notion, state_of_mind, food_delivery, `character_sheet` (prior day) | `character_sheet` |
| `daily_insight_compute` | 10:20 AM | `computed_metrics`, `habit_scores`, `day_grade`, platform_memory, whoop, garmin, macrofactor, apple_health, withings | `computed_insights`, `platform_memory` |
| `hypothesis_engine` | Sun 12:00 PM | ALL 9 ingestion sources + `hypotheses` (self) | `hypotheses`, `platform_memory` |

### Schedule Ordering Bug

`daily_insight_compute` runs at **10:20 AM** but reads `computed_metrics` written at **10:25 AM**. It reads yesterday's metrics, not today's. Fix: swap to `daily_metrics_compute` at 10:20, `daily_insight_compute` at 10:25.

---

## 3. Email/Output Layer (Computed Results → User-Facing Outputs)

| Lambda | Schedule (PT) | Reads (computed) | Reads (raw) | Outputs |
|--------|--------------|------------------|-------------|---------|
| `daily_brief` | 11:00 AM daily | computed_metrics, computed_insights, character_sheet, adaptive_mode, anomaly_detector, day_grade, habit_scores | whoop, eightsleep, garmin, strava, macrofactor, apple_health, withings, notion, todoist, state_of_mind, labs, food_delivery, platform_memory | S3: `public_stats.json`, `dashboard.json`, `clinical.json`, `buddy.json` + Email |
| `wednesday_chronicle` | Wed 8:00 AM | day_grade, habit_scores, character_sheet | whoop, eightsleep, garmin, strava, withings, macrofactor, apple_health, notion | DDB: `chronicle` + Email + S3: blog post (via approve) |
| `weekly_digest` | Sun 9:00 AM | day_grade, character_sheet, computed_metrics, habit_scores | all raw sources | Email |
| `monthly_digest` | 1st Mon 9:00 AM | character_sheet, day_grade, habit_scores | all raw sources + labs, dexa | Email |
| `nutrition_review` | Sat 10:00 AM | — | macrofactor, withings, strava, supplements, labs | Email |
| `monday_compass` | Mon 8:00 AM | day_grade | Todoist API, notion | Email |
| `weekly_plate` | Fri 7:00 PM | — | macrofactor, withings, platform_memory | Email |
| `og_image_generator` | 11:30 AM daily | — | S3: `public_stats.json` | S3: 12 OG images |

---

## 4. MCP Tool Layer (DynamoDB → Claude)

Read-only query layer. 115 tools across 26 modules.

| MCP Module | DDB Partitions Read |
|------------|-------------------|
| `tools_data` | **ANY source** (dynamic — accepts source parameter) |
| `tools_health` | whoop, strava, garmin, withings, apple_health, computed_metrics |
| `tools_training` | strava, whoop, garmin, eightsleep, macrofactor_workouts, computed_metrics |
| `tools_nutrition` | macrofactor, withings, eightsleep |
| `tools_sleep` | whoop |
| `tools_cgm` | apple_health, macrofactor |
| `tools_correlation` | whoop, strava, macrofactor |
| `tools_habits` | habitify, garmin, whoop |
| `tools_strength` | hevy, withings |
| `tools_journal` | notion, whoop, eightsleep, garmin |
| `tools_lifestyle` | apple_health, garmin, macrofactor, notion, strava, supplements, weather, whoop, withings |
| `tools_social` | state_of_mind, whoop |
| `tools_todoist` | todoist, habit_scores |
| `tools_character` | character_sheet |
| `tools_adaptive` | adaptive_mode |
| `tools_food_delivery` | food_delivery |
| `tools_measurements` | measurements |
| `tools_labs` | macrofactor |

**MCP tools that WRITE to DDB:** tools_lifestyle (insights, experiments, travel, supplements), tools_social (interactions, temptations), tools_todoist (Todoist API), tools_character (rewards, config), tools_challenges, tools_protocols, tools_decisions, tools_hypotheses, tools_memory, tools_sick_days.

---

## 5. Website Layer (S3 → Browser)

| S3 File | Written By | Read By | Update Frequency |
|---------|-----------|---------|-----------------|
| `public_stats.json` | daily_brief | Homepage, story, mission, observatory pages, OG image generator | Daily 11 AM |
| `dashboard.json` | daily_brief | dash.averagejoematt.com | Daily 11 AM |
| `clinical.json` | daily_brief | /labs/ page | Daily 11 AM |
| `buddy.json` | daily_brief | buddy.averagejoematt.com | Daily 11 AM |
| Site HTML/CSS/JS | Manual deploy (`sync_site_to_s3.sh`) | All 72 pages | On deploy |

**Site-api Lambda** (separate from daily brief) serves real-time endpoints: `/api/vitals`, `/api/ask`, `/api/board_ask`, etc. Reads directly from DDB, not from S3 files.

**Site-api-ai Lambda** (split from site-api) serves `/api/ask` and `/api/board_ask` only. Isolated concurrency.

**Observatory API endpoints** (v4.5.0 — site-api Lambda):

| Endpoint | DDB Partitions Read | Used By |
|----------|-------------------|---------|
| `/api/training_overview` | strava, whoop, hevy, garmin, apple_health | Training page |
| `/api/nutrition_overview` | macrofactor, strava | Nutrition page |
| `/api/weekly_physical_summary` | strava, garmin, apple_health | Training page |
| `/api/protein_sources` | macrofactor | Nutrition page |
| `/api/strength_deep_dive` | hevy | Training page |
| `/api/food_delivery_overview` | food_delivery | Nutrition page |

---

## 6. Single Points of Failure

| SPOF | Depends On It | Impact If Down |
|------|--------------|----------------|
| **`daily_brief_lambda`** | Writes all 4 S3 files powering the website + dashboard + buddy page + sends daily email | Entire website shows stale data; no daily email; no fallback writer |
| **`daily_metrics_compute`** | Writes `computed_metrics`, `day_grade`, `habit_scores` read by 6+ downstream Lambdas | All downstream compute + all emails show stale/missing grades |
| **`public_stats.json`** | Homepage, story, mission, all observatory pages, OG images | All 67 site pages show stale data |
| **Whoop partition** | Read by 8 Lambdas + 6 MCP modules | Sleep, HRV, recovery, readiness all missing; day grade drops |
| **MacroFactor partition** | Read by 7 Lambdas + 4 MCP modules | Nutrition scoring absent across platform |
| **Anthropic API** | 9 Lambdas + 2 site-api endpoints | All AI coaching returns `[AI_UNAVAILABLE]`; website Q&A returns 503 |
| **DynamoDB table** | Everything | Complete platform outage |
| **Secrets Manager** | All OAuth Lambdas + all AI Lambdas + MCP + site-api | All ingestion stops; all AI stops |

**Most dangerous SPOF:** `daily_brief_lambda` — the only Lambda that writes the 4 S3 files. No fallback writer exists.

---

## 7. Longest Critical Path

**From first data ingest to user-visible website update:**

```
06:45 AM PT  Weather ingestion (first Lambda of the day)
07:00 AM     Whoop, Garmin, Notion ingestion
07:15 AM     Withings, Habitify ingestion
07:30 AM     Strava ingestion
07:45 AM     Todoist ingestion
08:00 AM     Eight Sleep ingestion
09:00 AM     MacroFactor (via Dropbox poll)
             ─── INGESTION COMPLETE ───
09:05 AM     Anomaly detector
10:20 AM     Daily insight compute (reads computed_metrics from YESTERDAY — schedule bug)
10:25 AM     Daily metrics compute → writes computed_metrics, day_grade, habit_scores
10:30 AM     Adaptive mode compute → writes adaptive_mode
10:35 AM     Character sheet compute → writes character_sheet
             ─── COMPUTE COMPLETE ───
11:00 AM     Daily brief → reads ALL computed + raw → 4 AI calls → writes 4 S3 files + email
             ─── OUTPUT COMPLETE ───
11:01 AM     CloudFront serves updated public_stats.json to visitors
11:30 AM     OG image generator reads public_stats.json → generates 12 share images
```

**Wall clock:** 06:45 AM → 11:01 AM = **4 hours 16 minutes**
**Actual compute:** ~190 seconds (rest is schedule gaps)

---

## 8. Circular Dependencies

**None found.** The data flow is a clean DAG (Directed Acyclic Graph):

```
Ingestion (leaf nodes)
    ↓
Computed partitions (computed_metrics, day_grade, habit_scores, character_sheet, adaptive_mode)
    ↓
Computed insights (reads computed partitions)
    ↓
Daily brief (reads everything, writes S3)
    ↓
Website / Dashboard / Email
```

**Near-circular patterns (not actual cycles):**
- `platform_memory` is read AND written by `daily_insight_compute` and `hypothesis_engine`, but on different record keys (different sk patterns)
- `hypotheses` is read and written by `hypothesis_engine`, but as a state machine (read pending → evaluate → update status)
- `character_sheet` reads its own prior-day record for level continuity — this is a self-reference, not a cycle

---

## 9. Hottest DynamoDB Partitions

Partitions ranked by number of Lambda + MCP readers:

| Partition | Writers | Lambda Readers | MCP Tool Readers | Total Readers |
|-----------|---------|---------------|-----------------|--------------|
| `whoop` | 1 (whoop_lambda) | 8 (all compute + email) | 6 modules | **14** |
| `strava` | 1 (strava_lambda) | 6 | 5 modules | **11** |
| `macrofactor` | 1 (dropbox_poll) | 7 | 5 modules | **12** |
| `withings` | 1 (withings_lambda) | 6 | 5 modules | **11** |
| `apple_health` | 1 (health_auto_export) | 5 | 4 modules | **9** |
| `garmin` | 1 (garmin_lambda) | 5 | 5 modules | **10** |
| `computed_metrics` | 1 (daily_metrics) | 4 | 2 modules | **6** |
| `day_grade` | 1 (daily_metrics) | 5 | 0 modules | **5** |
| `character_sheet` | 1 (character_sheet) | 4 | 1 module | **5** |
| `habit_scores` | 1 (daily_metrics) | 4 | 1 module | **5** |
