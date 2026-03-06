# Handover — 2026-02-24 — Health Auto Export v1.1.0, MCP v2.15.0

## Session Summary

Major session: diagnosed and fixed Health Auto Export webhook metric processing, implemented three-tier source filtering, built 6 new MCP tools, and updated telemetry/schema/SOT.

## What Was Done

### 1. Webhook Diagnosis & Fix
- **Problem:** Webhook received 48 metrics but processed 0 (`other_metric_days: 0`)
- **Root cause:** App sends snake_case (`step_count`) but Lambda expected Title Case (`Step Count`)
- **Fix:** Updated METRIC_MAP to handle both formats
- **Deployed:** `deploy_health_auto_export_v2.sh` (Lambda code-only update)

### 2. Three-Tier Source Filtering (v1.1.0)
Apple HealthKit aggregates data from Whoop, Eight Sleep, MacroFactor, Withings — causing double-counting risk. Implemented:
- **Tier 1 (Apple-exclusive):** steps, flights, active/basal calories, distance, gait metrics (walking speed/step length/asymmetry/double support), headphone audio — all readings ingested
- **Tier 2 (Cross-device):** HR, RHR, HRV, respiratory rate, SpO2 — filtered to Apple Watch readings only via device name matching, stored with `_apple` suffix
- **Tier 3 (Skip):** 25+ nutrition metrics (MF SOT), sleep_analysis (ES SOT), body_mass/fat (Withings SOT)
- **Derived:** `total_calories_burned` = active + basal (Apple Watch TDEE)
- **Verified:** curl test confirmed all 3 tiers working (logs show filtering)
- **Deployed:** Same Lambda, same deploy script

### 3. Freshness Alerting v3
- apple_health threshold: 504h/720h → 12h/24h (was manual XML, now 4h webhook)
- Updated impacts list for gait, energy, CGM tools
- **Deployed:** `patch_freshness_v3.sh`

### 4. Schema & SOT Updates
- SCHEMA.md: added gait fields, energy fields, audio exposure, `_apple` cross-ref fields, updated SOT block
- DynamoDB profile: added `gait`, `energy_expenditure`, `cgm` SOT domains → all `apple_health`

### 5. MCP Server v2.15.0 — 6 New Tools (46→52)
- `get_gait_analysis` — composite gait score, clinical flags, trend analysis
- `get_energy_balance` — Apple Watch TDEE vs MacroFactor intake surplus/deficit
- `get_movement_score` — NEAT estimate, movement composite, sedentary day flags
- `get_cgm_dashboard` — glucose time-in-range, variability, fasting trend
- `get_glucose_sleep_correlation` — glucose buckets vs Eight Sleep
- `get_glucose_exercise_correlation` — exercise vs rest day glucose
- **Deployed:** `deploy_mcp_v2150.sh` (patch + package + Lambda update)

## Known Issue: App Manual Sync

The Health Auto Export app's "Sync" button gathers HealthKit data locally but does NOT fire the REST API POST. The webhook only fires on the app's background timer (~4h interval). The one successful 289KB payload at 10:53 AM PT was the timer, not manual.

**Workarounds tried:** v1 export format, v2 export format, manual sync button — none trigger HTTP POST.
**Next steps:**
- Wait for next automatic push (should arrive every 4 hours)
- Consider deleting and recreating the automation to force initial push
- Investigate if there's a per-automation "Run Now" button in newer app versions
- Fallback: build a local script that reads app exports and POSTs via curl

## Open Items / Roadmap

### Needs Webhook Data Flowing
- **Anomaly detector:** Add gait metrics (walking speed, asymmetry) after 2-3 weeks of baseline data
- **Daily brief:** Add gait composite score and glucose summary to morning email
- **Backfill:** Temporarily change automation to "Last 7 Days" to fill Feb 22-24 gap, then revert

### Needs S3 Access in MCP Lambda
- **get_glucose_meal_response** — Postprandial spike analysis per meal. Cross-reference 5-minute CGM readings in S3 with MacroFactor food_log timestamps to compute per-meal glucose spikes, time-to-peak, time-to-baseline. This is the "Levels-style" tool. Requires adding `s3:GetObject` to MCP Lambda IAM role.

### Needs Stelo CGM Flowing
- **Fasting glucose trend** — Compare daily CGM minimum (overnight nadir) against lab-drawn fasting glucose across 7 blood draws. Validates whether CGM is tracking metabolic trajectory.

### Workout Data
- Webhook receives workout data but Lambda only archives to S3 (not processed to DynamoDB). Add workout processing after metrics pipeline is confirmed stable.

## Files Modified/Created This Session

| File | Action |
|------|--------|
| `health_auto_export_lambda.py` | Modified — v1.1.0, tier filtering, expanded metrics |
| `deploy_health_auto_export_v2.sh` | Created — code-only deploy |
| `patch_freshness_v3.sh` | Created — freshness alerting update |
| `patch_mcp_v2150.py` | Created — MCP server patcher |
| `deploy_mcp_v2150.sh` | Created — MCP deploy script |
| `CHANGELOG.md` | Updated — v2.15.0 entry |
| `SCHEMA.md` | Updated — new fields, SOT block |
| `ARCHITECTURE.md` | Updated — tool count, version |

## Deploy Commands Run

```bash
bash deploy_health_auto_export_v2.sh  # Webhook Lambda v1.1.0
bash patch_freshness_v3.sh            # Freshness alerting v3
bash deploy_mcp_v2150.sh              # MCP server v2.15.0 (52 tools)
```

## Current State

- **MCP Server:** v2.15.0, 52 tools, deployed
- **Webhook Lambda:** v1.1.0, tier filtering, deployed & verified via curl
- **Freshness Checker:** v3, 12h/24h apple_health threshold, deployed
- **SOT Domains:** 14 (added gait, energy_expenditure, cgm)
- **Webhook data flow:** Waiting for app's automatic background push cycle
