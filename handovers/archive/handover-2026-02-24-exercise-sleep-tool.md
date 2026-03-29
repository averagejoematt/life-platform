# Life Platform — Handover: Exercise Sleep Correlation Tool
**Date:** 2026-02-24  
**Version:** v2.12.0  
**Session:** MCP tool development — exercise timing vs sleep quality  
**Status:** Patch + deploy scripts ready; awaiting execution in terminal

---

## What Was Done

### 1 New MCP Tool (55 → 56 tools)

**`get_exercise_sleep_correlation`** — Personal exercise timing cutoff finder

Extracts last exercise end time per day from Strava (`start_date_local` + `elapsed_time_seconds`), correlates with same-night Eight Sleep metrics. Answers: "do late workouts hurt your sleep, and if so, after what cutoff time?"

**Key features:**
- **Time-of-day buckets:** Rest Day / Before Noon / Noon–3 PM / 3–6 PM / 6–8 PM / After 8 PM (finer evening granularity than caffeine tool since that's where the signal lives)
- **Exercise vs rest day comparison:** Side-by-side sleep metrics for active vs rest days
- **Intensity analysis:** Classifies each day's exercise as low/moderate/high based on avg HR as % of max HR
- **Intensity × timing interaction:** Compares early vs late for each intensity level — does a hard evening workout hurt more than an easy one?
- **Duration-weighted HR:** When multiple activities occur on the same day, HR is weighted by moving time
- **Pearson correlations:** Both timing (end time vs sleep) and intensity (avg HR vs sleep)
- **Smart recommendation:** Bucket-based cutoff detection (3pt degradation threshold), falls through to correlation-based, handles the "evening exercise is fine for you" case
- **Configurable filters:** `min_duration_minutes` (default 15), `exclude_sport_types` (comma-separated)
- **7 sleep metrics:** Efficiency, deep%, REM%, score, duration, latency, HRV (one more than caffeine tool)

### Design Decisions

1. **180-day default window** (vs 90 for caffeine) — exercise patterns need more data since frequency is lower than daily caffeine intake
2. **Rest days as explicit bucket** — unlike caffeine where "no caffeine" is a minority, rest days are common and serve as the natural baseline
3. **3pt degradation threshold** (vs 2pt for caffeine) — exercise data is noisier due to confounders (type, duration, intensity all vary)
4. **Intensity × timing matrix** — the literature suggests high-intensity evening exercise is the main culprit, not exercise per se. This data structure lets Claude surface nuanced advice like "evening walks are fine but evening HIIT isn't"
5. **Uses `elapsed_time_seconds`** not `moving_time_seconds` for end time — captures the actual time you left the gym/trail, not just moving segments

---

## Files Created

| File | Purpose |
|------|---------|
| `patch_exercise_sleep_tool.py` | Idempotent patcher — inserts function + registry entry + version bump |
| `deploy_exercise_sleep_tool.sh` | Runs patcher, verifies, packages, deploys to Lambda |

---

## Deployment Instructions

```bash
cd ~/Documents/Claude/life-platform
chmod +x deploy_exercise_sleep_tool.sh
./deploy_exercise_sleep_tool.sh
```

Then restart Claude Desktop and test.

---

## Verification Tests

```
"Do late workouts hurt my sleep?"                    → get_exercise_sleep_correlation
"What is my exercise timing cutoff?"                 → get_exercise_sleep_correlation
"Exercise vs rest day sleep comparison"              → get_exercise_sleep_correlation
"Does evening exercise affect my deep sleep?"        → get_exercise_sleep_correlation
"Show exercise timing correlation excluding walks"   → get_exercise_sleep_correlation (exclude_sport_types: "Walk")
```

---

## What's Next

Top priorities from backlog:
1. **Zone 2 training identifier** (Quick Win #4) — Garmin HR zone data already ingested; `get_zone2_breakdown` tool
2. **Alcohol impact tool** (Quick Win #7) — MacroFactor alcohol → next-day HRV/recovery/sleep
3. **Data completeness alerting** (#16) — detect silent data gaps across sources
4. **Weekly Digest v2** (#6) — Zone 2 minutes, macro adherence, CTL/ATL/TSB, insight of the week
