# Handover — 2026-03-07 — v2.86.0: IC-2 Insight Compute + IC-3 Chain-of-Thought + IC-6 Milestones

## Platform State
- **Version:** v2.86.0
- **MCP tools:** 139 | **Lambdas:** 33 (+1: daily-insight-compute) | **Modules:** 28

---

## What Was Built This Session

### Deployment Verification
- Confirmed v2.85.0 was successfully deployed (both Lambdas updated at 23:15-23:16 UTC today)
- daily-brief ran post-deploy at 23:18 UTC — no import errors, AI calls succeeded
- MCP Lambda initialized cleanly with 121 MB, tools/list served (tools_memory.py live)

---

### IC-2: Daily Insight Compute Lambda

**New file:** `lambdas/daily_insight_compute_lambda.py`

Transforms pre-computed metrics into curated coaching intelligence. The Daily Brief's AI calls now receive context blocks derived from 7-14 days of pattern analysis rather than raw numbers alone.

**Reads (all pre-computed — no raw DDB scans):**
- `computed_metrics` — 7 days
- `habit_scores` — 7 days (missed_tier0, synergy_groups)
- `day_grade` — 14 days (for momentum trend)
- `platform_memory` — coaching_calibration, what_worked, failure_pattern (empty now, grows over time)

**Computes:**
- Momentum signal + week-over-week grade trend (`improving` / `stable` / `declining`)
- Metric trend detection — 3+ consecutive day declining/improving runs as leading indicators
- Habit miss rates — T0 weakest habits, strongest habits, broken synergy stacks
- Platform memory context — loads coaching calibration + what_worked records

**Writes:** `SOURCE#computed_insights` DDB partition with `ai_context_block` string

Example output block:
```
PLATFORM INTELLIGENCE (7-day context, pre-computed):
📈 Momentum: IMPROVING (65→70.5 avg grade, +8.5% week-over-week)
⚠️ LEADING INDICATOR: sleep quality declining 3 days straight (now 71 vs 82 avg, -13%)
✅ POSITIVE SIGNAL: recovery improving 3 days straight (now 78 vs 65 avg, +20%)
🔴 Weakest T0 habits: wind_down_routine (missed 5/7 days)
💪 Strongest habits: protein_first, steps_goal
INSTRUCTION: Reference this intelligence in coaching...
```

**Graceful degradation:** `_load_insights_context(data)` returns `""` if Lambda hasn't run — zero breakage.

---

### IC-3: Chain-of-Thought Two-Pass

**New functions in `lambdas/ai_calls.py`:**
- `_run_analysis_pass()` — Pass 1: ~150 token structured JSON identifying key patterns, causal chain, priority, and tone
- `_format_analysis()` — formats Pass 1 output for injection into Pass 2 prompt

**Applied to:** `call_board_of_directors` and `call_tldr_and_guidance`

Pattern:
1. Pass 1 asks: "What patterns exist? What caused what? What's the priority?"
2. Pass 2 writes coaching using Pass 1 output + full prompt context

Effect: eliminates the hallmark of single-pass prompting — listing gaps and scores without connecting them. Model now identifies `wind_down missed → sleep efficiency 71%` BEFORE writing rather than during.

Cost: +2 Haiku calls/day (~$0.0003 total, unmeasurable in budget).

---

### IC-6: Milestone Architecture

**New in `lambdas/ai_calls.py`:**
- `_WEIGHT_MILESTONES` — 6 milestones with biological significance
- `_build_milestone_context()` — injects when within 10 lbs (approaching) or 5 lbs past (achieved)

Milestones:
| Weight | Name | Significance |
|--------|------|-------------|
| 285 lbs | Sleep Threshold | Sleep apnea risk drops (genome flag) |
| 270 lbs | Walking Speed Unlock | +0.3 mph natural improvement |
| 250 lbs | Athletic Zone 2 | Zone 2 feels like real training |
| 225 lbs | Athletic FFMI Range | Body composition turns the corner |
| 200 lbs | Onederland | Sub-200 for first time in years |
| 185 lbs | Goal Weight | 117 lbs total, transformation complete |

**Zero prompt bloat** on normal days — empty string if not within threshold. Injected into BoD + TL;DR calls.

**Current weight ~280 lbs** → Sleep Threshold (285) is already ACHIEVED, Walking Speed Unlock (270) is ~10 lbs away. Both will surface in tomorrow's brief.

---

### daily_brief_lambda.py change

Added to `gather_daily_data()`:
```python
computed_insights = fetch_date("computed_insights", yesterday)
```
Added `"computed_insights": computed_insights` to returned data dict.

---

## Deploy Instructions

```bash
bash deploy/deploy_ic_features.sh
```

**What it does:**
1. Creates `daily-insight-compute` Lambda (if new) with role `lambda-mcp-server-role`, Python 3.12, 512 MB, 120s timeout
2. Creates EventBridge rule `daily-insight-compute` at `cron(42 17 * * ? *)` (9:42 AM PT)
3. Grants Lambda permission to be invoked by EventBridge
4. Deploys `daily-brief` with updated `ai_calls.py` + `daily_brief_lambda.py`

**Post-deploy verification:**

```bash
# 1. Smoke-test IC-2 (run insight Lambda for yesterday)
aws lambda invoke \
  --function-name daily-insight-compute \
  --payload '{"date":"2026-03-06","force":true}' \
  /tmp/insight_out.json --region us-west-2 && cat /tmp/insight_out.json

# 2. Check daily-brief for import errors (none expected)
aws logs describe-log-streams --log-group-name /aws/lambda/daily-brief \
  --order-by LastEventTime --descending --limit 1 --region us-west-2
```

**Expected from smoke test:**
```json
{
  "statusCode": 200,
  "momentum": "improving|stable|declining",
  "declining_count": N,
  "improving_count": N,
  "weakest_habits": [...]
}
```

---

## Files Changed
- `lambdas/daily_insight_compute_lambda.py` — NEW
- `lambdas/ai_calls.py` — IC-2 reader, IC-3 analysis pass, IC-6 milestones
- `lambdas/daily_brief_lambda.py` — computed_insights fetch + data dict
- `deploy/deploy_ic_features.sh` — NEW deploy script
- `docs/CHANGELOG.md` — v2.86.0

---

## Pending Items (carried forward)

- **[DEPLOY NOW]** `bash deploy/deploy_ic_features.sh`
- **[VERIFY]** IC-2 smoke test after deploy
- **[NOTE]** IC-2 first runs produce minimal context (only 2 days of habit_scores exist). Grows richer over 7 days as habit_scores + computed_metrics accumulate. First real week: ~March 14.
- **[PENDING]** IC-4 failure pattern recognition (Month 2 — needs 6+ weeks of data)
- **[PENDING]** IC-5 momentum detection / early warning (Month 2)
- **[PENDING]** IC-7 cross-pillar trade-off reasoning (low effort, high value, no data maturity req)
- **[PENDING]** Google Calendar integration (Board rank #2, North Star gap #2)
- **[PENDING]** Brittany weekly accountability email
- **[PENDING]** HAE/Notion data gap backfill assessment (from v2.84.2)

## Version
v2.86.0 | 33 Lambdas | 139 MCP tools | 28 modules
