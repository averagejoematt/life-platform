# Life Platform — Handover: Zone 2 Training Tracker
**Date:** 2026-02-24  
**Version:** v2.13.0  
**Session:** MCP tool development — Zone 2 training identifier  
**Status:** Patch + deploy scripts ready; awaiting execution in terminal

---

## What Was Done

### 1 New MCP Tool (56 → 57 tools)

**`get_zone2_breakdown`** — Zone 2 training tracker and weekly breakdown

Classifies every Strava activity into 5 HR zones based on average heartrate as % of max HR (183 bpm from profile). Aggregates weekly Zone 2 minutes and compares to the 150 min/week target.

**Key features:**
- **5-zone distribution:** Full training zone breakdown (Zone 1 recovery through Zone 5 VO2 max) with time and % of total
- **Weekly breakdown:** Zone 2 minutes per week with target comparison, plus per-zone minutes and Zone 2 activity details
- **Sport type breakdown:** Which activities contribute most Zone 2 time (walks, hikes, runs, rides, etc.)
- **Trend analysis:** First-half vs second-half comparison to show if Zone 2 volume is increasing/decreasing
- **Training polarization alerts:** Warns if more time in Zone 3 "no man's land" than Zone 2 (per Seiler's polarized model)
- **Configurable:** Weekly target (default 150 min), minimum activity duration (default 10 min)
- **Zone 2 HR range:** 110-128 bpm (60-70% of max HR 183)

### Design Decisions

1. **Strava-based, not Garmin** — Garmin HR zone data (`hr_zone_*_seconds`) is not populated in any backfilled records. The Garmin API apparently didn't return zone data for historical dates. Strava's per-activity `average_heartrate` is the richest available HR source with 2,636+ activities.

2. **Average HR classification** — Each activity's average HR determines its zone. The full `moving_time_seconds` is attributed to that zone. This is an approximation (a long hike might cross zones) but the best available without per-second HR data. Methodology is transparently documented in the response.

3. **150 min/week target** — Per Attia, Huberman, and WHO guidelines for moderate-intensity aerobic activity. This is the minimum effective dose for cardiovascular longevity benefits. Configurable via `weekly_target_minutes` parameter.

4. **Polarization check** — The tool specifically warns about Zone 3 dominance. Per Seiler's research, elite endurance athletes train ~80% easy (Zone 1-2) / 20% hard (Zone 4-5). Zone 3 is metabolically expensive without proportionate adaptation gains.

5. **No Garmin fallback** — If Garmin resumes syncing and populates `zone2_minutes`, a future version could cross-reference. For now, Strava is the single source.

---

## Garmin HR Zone Data Investigation

Checked multiple date ranges in DynamoDB — no records contain `hr_zone_*_seconds`, `zone2_minutes`, or `intensity_minutes_*` fields despite the backfill script including extraction logic. The Garmin Connect API likely doesn't return historical HR zone data for dates where the watch wasn't actively tracking (or for older watch models). The daily Lambda will capture zones going forward if the Garmin resumes syncing.

---

## Files Created

| File | Purpose |
|------|---------|
| `patch_zone2_tool.py` | Idempotent patcher — inserts function + registry entry + version bump |
| `deploy_zone2_tool.sh` | Runs patcher, verifies, packages, deploys to Lambda |

---

## Deployment Instructions

```bash
cd ~/Documents/Claude/life-platform
chmod +x deploy_zone2_tool.sh
./deploy_zone2_tool.sh
```

Then restart Claude Desktop and test.

---

## Verification Tests

```
"How much Zone 2 am I doing?"                → get_zone2_breakdown
"Show my training zone distribution"          → get_zone2_breakdown
"Am I hitting my Zone 2 target?"              → get_zone2_breakdown
"Weekly Zone 2 minutes over the last 6 months" → get_zone2_breakdown (start_date 6 months ago)
"Zone 2 breakdown excluding walks"             → Not directly supported (would need exclude param — future enhancement)
```

---

## What's Next

Top priorities from backlog:
1. **Alcohol impact tool** (Quick Win #7) — MacroFactor alcohol → next-day HRV/recovery/sleep
2. **Data completeness alerting** (#16) — detect silent data gaps across sources
3. **Weekly Digest v2** (#6) — Zone 2 minutes, macro adherence, CTL/ATL/TSB, insight of the week
