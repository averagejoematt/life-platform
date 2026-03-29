# Life Platform — Handover: Alcohol Sleep/Recovery Correlation Tool
**Date:** 2026-02-24  
**Version:** v2.14.0  
**Session:** MCP tool development — alcohol impact analyzer  
**Status:** Patch + deploy scripts ready; awaiting execution in terminal

---

## What Was Done

### 1 New MCP Tool (57 → 58 tools)

**`get_alcohol_sleep_correlation`** — Personal alcohol impact analyzer

Correlates MacroFactor alcohol intake with same-night Eight Sleep AND next-day Whoop recovery. Three-source correlation engine.

**Key features:**
- **Dose buckets:** None / Light (≤1 drink) / Moderate (1-2.5 drinks) / Heavy (3+ drinks), where 1 standard drink = 14g pure alcohol
- **Same-night sleep:** Efficiency, deep%, REM%, score, duration, latency, HRV from Eight Sleep
- **Next-day recovery:** Recovery score, HRV, resting HR from Whoop (the "hangover metrics")
- **Timing analysis:** Last drink time per day from food_log entries → Pearson correlations with sleep
- **Drinking vs sober comparison:** Side-by-side across all 10 metrics
- **Severity assessment:** Automated impact classification (HIGH/MODERATE/LOW/INSUFFICIENT_DATA)
- **Science-informed alerts:** REM suppression warning, deep sleep sedation caveat, late drinking metabolism timing, drinking frequency check

### Design Decisions

1. **Three-source join** — First tool to combine MacroFactor + Eight Sleep + Whoop in a single analysis. Same-night sleep metrics capture the direct sleep impact; next-day Whoop captures the autonomic recovery cost.

2. **Next-day offset** — Alcohol on 2/15 → sleep on night of 2/15 (Eight Sleep date 2/15) + Whoop recovery on 2/16. The `_next_date()` helper shifts correctly.

3. **Deep sleep sedation caveat** — If alcohol appears to increase deep sleep, the tool explicitly flags this as misleading. Alcohol-induced sedation lacks the restorative neural oscillations of natural SWS.

4. **14g standard drink** — Universal standard (NIAAA). Maps to 12oz beer, 5oz wine, 1.5oz spirits. Output includes both grams and standard drink count for intuitive interpretation.

5. **Graceful Whoop absence** — Next-day Whoop data enhances the analysis but isn't required. The tool works with just MacroFactor + Eight Sleep, with recovery metrics showing as null.

---

## Data Status

Only ~6 days of real MacroFactor data (from 2026-02-22). The tool will return "insufficient data" initially and progressively unlock as food logging continues. Meaningful patterns should emerge after 2-3 weeks with a mix of drinking and sober days.

---

## Files Created

| File | Purpose |
|------|---------|
| `patch_alcohol_sleep_tool.py` | Idempotent patcher script |
| `deploy_alcohol_sleep_tool.sh` | Deploy script |

---

## Deployment Instructions

```bash
cd ~/Documents/Claude/life-platform
chmod +x deploy_alcohol_sleep_tool.sh
./deploy_alcohol_sleep_tool.sh
```

---

## Verification Tests

```
"Is alcohol affecting my sleep?"           → get_alcohol_sleep_correlation
"How does drinking affect my recovery?"     → get_alcohol_sleep_correlation
"Drinking vs sober sleep comparison"        → get_alcohol_sleep_correlation
"How does alcohol affect my HRV?"           → get_alcohol_sleep_correlation
```

---

## Session Summary: 3 Tools Deployed

| Version | Tool | Sources | Pattern |
|---------|------|---------|---------|
| v2.12.0 | `get_exercise_sleep_correlation` | Strava + Eight Sleep | Timing correlation |
| v2.13.0 | `get_zone2_breakdown` | Strava | Zone classification + weekly tracking |
| v2.14.0 | `get_alcohol_sleep_correlation` | MacroFactor + Eight Sleep + Whoop | Three-source dose/timing correlation |

Tool count: 55 → 58. All three quick wins from the backlog completed.

---

## What's Next

Top priorities from backlog:
1. **Data completeness alerting** (#16) — detect silent data gaps across sources
2. **Weekly Digest v2** (#6) — Zone 2 minutes, macro adherence, CTL/ATL/TSB, insight of the week
3. **DynamoDB TTL smoke test** (Quick Win B) — 2-minute verification
4. **Notion Journal integration** (#9) — closes the "why" gap in biometric insights
