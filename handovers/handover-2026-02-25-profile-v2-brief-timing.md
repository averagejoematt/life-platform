# Handover — 2026-02-25 — Profile v2 + Daily Brief Timing + Brief v2 Design

Detailed session handover. See HANDOVER_LATEST.md for current state summary.

## Key Decisions Made

1. **Daily brief timing:** 8:15 AM → 10:00 AM to solve stale Whoop recovery (was showing yesterday's recovery because Whoop hadn't calculated current morning's recovery by 8:15 AM)
2. **Whoop recovery refresh:** New 9:30 AM schedule using `date_override: today` — same Lambda, different EventBridge input
3. **Profile v2.0:** Expanded from ~15 fields to ~60+ fields covering full bio, targets, phases, MVP habits, health context, coaching context
4. **Weight loss phases:** Matthew chose aggressive: 3→2.5→2→1 lbs/week across 4 phases. Board approved with caveat to monitor RHR/HRV during Phase 1
5. **MVP habits (9):** Board recommended based on high-leverage health outcomes. Backwards-compatible — list stored in profile with version number, retrocompute-safe
6. **Day grade architecture:** Raw component scores stored separately from weighted grade. Two-level retrocompute: weight changes are instant, component formula changes require source data re-read
7. **Board of Directors:** Formally defined as expert panel for all coaching prompts. Stored in Claude memory.
8. **Mental health context:** Depression, shame, low confidence, social anxiety documented as primary obstacles. Coaching tone: direct + empathetic, Jocko discipline meets Brené Brown vulnerability

## Profile v2 Key Fields

```
Wake: 4:30 AM (window 4:15-4:45)
Bed: 9:00 PM
Calories: 1800 (±10% tolerance, >25% = penalty)
Macros: P190/F60/C125
Eating window: 11:30am-7:30pm
Caffeine: 2x coffee, 7am start, noon cutoff
Steps: 7,000
Water: 100oz (3L)
Training: Push/Pull/Legs, 5 days, 5-7am
Deficit: 1,500 kcal/day (Phase 1)
```

## Deploy Bug Note

`deploy_daily_brief_v2_timing.sh` had a bug: Step 1b's `cd /tmp` didn't return to working directory before Step 2 tried to copy `whoop_lambda.py`. Fixed in `deploy_daily_brief_v2_timing_step2.sh` using `$WORK_DIR` absolute paths. Future deploy scripts should always use absolute paths or `cd "$WORK_DIR"` after any temp directory operations.
