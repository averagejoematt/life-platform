# Life Platform — Session Handover: Correlation Tool Suite
**Date:** 2026-02-24  
**Versions:** v2.12.0 → v2.14.0 (3 deployments)  
**Session focus:** MCP tool development — lifestyle factor × sleep/recovery correlation engines  
**Status:** All 3 tools deployed and verified on Lambda

---

## Session Summary

Built and deployed 3 new MCP tools that form a **lifestyle correlation suite** — each analyzes how a modifiable behavior (exercise timing, training zones, alcohol intake) impacts sleep and recovery using the platform's multi-source data.

| Version | Tool | Sources Joined | Pattern |
|---------|------|----------------|---------|
| v2.12.0 | `get_exercise_sleep_correlation` | Strava + Eight Sleep | Timing × sleep quality |
| v2.13.0 | `get_zone2_breakdown` | Strava (HR) | Zone classification + weekly tracking |
| v2.14.0 | `get_alcohol_sleep_correlation` | MacroFactor + Eight Sleep + Whoop | Dose/timing × sleep + next-day recovery |

**Tool count: 55 → 58. All three "quick win" correlation items from backlog completed (#3, #4, #7).**

---

## Tool Details

### 1. get_exercise_sleep_correlation (v2.12.0)

**Question answered:** "Do late workouts hurt your sleep, and if so, after what cutoff time?"

- Computes last exercise end time per day from Strava `start_date_local` + `elapsed_time_seconds`
- 6 time-of-day buckets: Rest Day / Before Noon / Noon–3 PM / 3–6 PM / 6–8 PM / After 8 PM
- Exercise vs rest day comparison across 7 sleep metrics
- Intensity classification (low/moderate/high via avg HR % of max)
- **Intensity × timing interaction** — answers "does a hard evening workout hurt more than an easy one?"
- Pearson correlations for both timing and intensity effects
- Smart recommendation with 3pt degradation threshold

### 2. get_zone2_breakdown (v2.13.0)

**Question answered:** "Am I doing enough Zone 2 training?"

- Classifies every Strava activity into 5 HR zones based on avg HR % of max HR (183 bpm)
- Zone 2 range: **110-128 bpm** (60-70% of max)
- Weekly breakdown vs 150 min/week target (Attia/Huberman/WHO)
- Full 5-zone training distribution with time and % of total
- Sport type breakdown for Zone 2 activities
- Trend analysis (increasing/decreasing/stable)
- **Training polarization alert** — warns if Zone 3 > Zone 2 per Seiler's model

**Key finding during development:** Garmin HR zone data (`hr_zone_*_seconds`, `zone2_minutes`) is empty across all 1,356 backfilled records. The Garmin Connect API didn't return zone data for historical dates. Pivoted to Strava per-activity avg HR (2,636+ activities with HR data).

### 3. get_alcohol_sleep_correlation (v2.14.0)

**Question answered:** "Is alcohol affecting my sleep and recovery?"

- **First 3-source correlation tool** in the platform (MacroFactor + Eight Sleep + Whoop)
- Same-night sleep impact (Eight Sleep) + next-day recovery cost (Whoop)
- Dose buckets: None / Light (≤1 drink) / Moderate (1-2.5) / Heavy (3+), 1 drink = 14g
- 10 metrics: 7 sleep + 3 recovery (recovery score, HRV, RHR)
- Timing analysis from food_log per-entry alcohol_g + timestamps
- Drinking vs sober comparison across all metrics
- Severity assessment (HIGH/MODERATE/LOW/INSUFFICIENT_DATA)
- Science alerts: REM suppression, deep sleep sedation caveat, late drinking metabolism, frequency check
- **Data note:** Only ~6 days of MacroFactor data; tool returns insufficient_data initially, self-activates as logging continues

---

## Files Created This Session

| File | Purpose |
|------|---------|
| `patch_exercise_sleep_tool.py` | v2.12.0 patcher |
| `deploy_exercise_sleep_tool.sh` | v2.12.0 deploy script |
| `patch_zone2_tool.py` | v2.13.0 patcher |
| `deploy_zone2_tool.sh` | v2.13.0 deploy script |
| `patch_alcohol_sleep_tool.py` | v2.14.0 patcher |
| `deploy_alcohol_sleep_tool.sh` | v2.14.0 deploy script |
| `handovers/handover-2026-02-24-exercise-sleep-tool.md` | Per-tool handover |
| `handovers/handover-2026-02-24-zone2-tool.md` | Per-tool handover |
| `handovers/handover-2026-02-24-alcohol-sleep-tool.md` | Per-tool handover |
| `handovers/handover-2026-02-24-session-correlation-suite.md` | This file |

## Documentation Updated

| File | Changes |
|------|---------|
| `CHANGELOG.md` | v2.12.0, v2.13.0, v2.14.0 entries added |
| `PROJECT_PLAN.md` | Items #3, #4, #7 marked DONE; version table updated; last-update header updated |
| `ARCHITECTURE.md` | Tool count 55 → 58 in header, diagram, and project structure |

---

## Current Platform State

- **MCP Server:** v2.14.0, **58 tools**, deployed to Lambda `life-platform-mcp`
- **Data Sources:** 14 (11 automated + 3 manual)
- **DynamoDB:** ~8,000+ items
- **Lambda LastModified:** 2026-02-24T04:05:24Z
- **Cost:** Tracking under $25/month budget

---

## Backlog Status After This Session

### Quick Wins — Completed this session
- ~~#3 Exercise timing vs sleep~~ → v2.12.0
- ~~#4 Zone 2 training identifier~~ → v2.13.0
- ~~#7 Alcohol impact tool~~ → v2.14.0

### Quick Wins — Remaining
- **B. DynamoDB TTL smoke test** — single CLI command, 2 min
- **E. WAF rate limiting** — $5/mo, 1 hour
- **G. MCP API key rotation** — 90-day schedule

### Next High-Value Items
1. **#16 Data completeness alerting** — detect silent gaps across all sources before they corrupt trends
2. **#6 Weekly Digest v2** — now has Zone 2 data to include; add macro adherence, CTL/ATL/TSB, deltas, insight of the week
3. **#9 Notion Journal integration** — closes the "why" gap; Haiku extracts mood/energy/stress from unstructured entries
4. **#8 → superseded, but energy/stress** still missing from Habitify mood — Notion journal is the solution

### Verification Pending
- **v2.11.0 labs/genome tools (8 tools)** — deployed prior session, pending Claude Desktop verification
- **v2.12.0–v2.14.0 tools (3 tools)** — deployed this session, test after Claude Desktop restart

---

## Verification Commands (After Claude Desktop Restart)

```
# Exercise timing
"Do late workouts hurt my sleep?"
"Exercise vs rest day sleep comparison"

# Zone 2
"How much Zone 2 am I doing?"
"Show my training zone distribution"

# Alcohol (will likely say insufficient data)
"Is alcohol affecting my sleep?"
"Drinking vs sober sleep comparison"

# Also verify v2.11.0 labs tools from prior session
"Show me all my lab draws"
"How has my LDL trended over time?"
"What does my genome say about metabolism?"
"Give me my overall health risk profile"
```
