# Handover — 2026-03-07 — v2.85.0: Prompt Intelligence (P1–P5) + IC-1 Platform Memory

## Platform State
- **Version:** v2.85.0
- **MCP tools:** 139 (+4) | **Lambdas:** 32 | **Modules:** 28 (+1: tools_memory.py)

---

## What Was Built This Session

### 1. `deploy/deploy_lambda.sh` — Multi-Module Fix

Added `--extra-files` flag. daily-brief now deploys correctly every time:

```bash
bash deploy/deploy_lambda.sh daily-brief lambdas/daily_brief_lambda.py \
    --extra-files lambdas/ai_calls.py lambdas/html_builder.py \
    lambdas/output_writers.py lambdas/board_loader.py
```

Old behavior: every daily-brief deploy silently dropped the 4 imported modules.
New behavior: validates all files exist, bundles them, verifies handler entry present.

---

### 2. `lambdas/ai_calls.py` — Prompt Intelligence Fixes

**P2 — Journey context (`_build_journey_context`):**
- Computes week number from `profile.journey_start_date` (default: 2026-02-22)
- Stages: Foundation (wk 1-4), Momentum (wk 5-12), Building (wk 13-26), Advanced (wk 26+)
- Stage-specific coaching principles injected into all 4 AI calls
- Profile field: add `journey_start_date: "2026-02-22"` if not already there (uses default otherwise)

**P3 — Walk coaching rewrite:**
- Old: "For casual walks, just a brief NEAT acknowledgment"
- New: Walks are PRIMARY training at Foundation stage. 45-min walk at 300+ lbs = real cardiovascular load.
- Training prompt now explicitly instructs: evaluate pace, duration, HR, bodyweight-adjusted progress.

**P4 — Habit→outcome connector (`_build_habit_outcome_context`):**
- 7-day T0/T1 completion trend passed to BoD + TL;DR AI calls
- Known causal mappings (wind-down → sleep_score, etc.) included as context
- Explicit instruction: "trace the causal chain — don't just list the gap"

**P5 — TDEE context (`_build_tdee_context`):**
- Checks MacroFactor for `tdee_kcal` or `estimated_tdee_kcal`
- Falls back to `calorie_target + phase_deficit` (derives ~3300 kcal in Phase 1)
- Shows: planned deficit, actual deficit, % of TDEE
- Flags >25% below target as possible logging gap
- Injected into training+nutrition coach AND TL;DR+guidance prompts

---

### 3. `lambdas/weekly_plate_lambda.py` — P1 Plate Memory

**Load (before AI call):**
- Queries `platform_memory` DDB partition for last 4 `MEMORY#weekly_plate#*` records
- Formats as anti-repeat block: "Wildcard was X ← DO NOT REPEAT THIS"
- Prepended to user_message before Sonnet call

**Store (after AI response):**
- Extracts plate summary from HTML: top foods, wildcard, recipe names (regex)
- Writes to `pk=USER#matthew#SOURCE#platform_memory`, `sk=MEMORY#weekly_plate#<date>`
- Non-fatal try/except — plate still sends if storage fails

**Effect:** Week 1 stores summary. Week 2 loads Week 1's context. By Week 4, full 4-week rolling memory prevents any repeat wildcards or recipes.

---

### 4. `mcp/tools_memory.py` — IC-1 Platform Memory

New module (28th), 4 tools (136–139):

| Tool | Description |
|------|-------------|
| `write_platform_memory(category, content, date, overwrite)` | Store a memory record |
| `read_platform_memory(category, days, limit)` | Read recent records by category |
| `list_memory_categories(days)` | List all categories with counts |
| `delete_platform_memory(category, date)` | Delete a record |

**Valid categories:** `weekly_plate`, `failure_pattern`, `what_worked`, `coaching_calibration`, `personal_curves`, `journey_milestone`, `insight`, `experiment_result`

**Why this matters:** Every Tier 7 IC feature (IC-4 through IC-14) writes and reads from this partition. This is the compounding substrate. Without it, every AI call starts from zero. With it, the platform accumulates intelligence over time.

---

## Deploy Instructions

```bash
bash deploy/deploy_prompt_intelligence.sh
```

Order: daily-brief → 10s → weekly-plate-schedule → 10s → life-platform-mcp

**Post-deploy verification:**
1. `aws lambda invoke --function-name daily-brief --payload '{"demo_mode":true}' /tmp/out.json` → check CloudWatch for ImportError
2. MCP: `list_memory_categories` → `{categories: [], total_records: 0}` (empty is correct — no data yet)
3. MCP: `write_platform_memory` with `category="insight"`, `content={"note":"deploy test"}` → `{status: "stored"}`
4. MCP: `read_platform_memory` with `category="insight"` → should return the record
5. Tomorrow's daily brief: check training section — walks should get real coaching not "brief NEAT acknowledgment"
6. Next Friday's Weekly Plate: will store first plate summary. The following Friday will load it.

---

## Files Changed
- `deploy/deploy_lambda.sh` — multi-module `--extra-files` flag
- `lambdas/ai_calls.py` — P2+P3+P4+P5 (complete rewrite with journey context, walk coaching, habit-outcome, TDEE)
- `lambdas/weekly_plate_lambda.py` — P1 (plate memory load + store)
- `mcp/tools_memory.py` — NEW: IC-1 platform_memory module
- `mcp/registry.py` — import tools_memory + tools 136-139
- `deploy/deploy_prompt_intelligence.sh` — NEW: deploy script
- `docs/CHANGELOG.md` — v2.85.0
- `docs/PROJECT_PLAN.md` — needs version bump (v2.85.0, 139 tools, 28 modules)

---

## Pending Items (carried forward)

- **[DEPLOY TODAY]** `bash deploy/deploy_prompt_intelligence.sh`
- **[VERIFY]** daily-metrics-compute-errors alarm should now be self-cleared (stale secret fixed last session)
- **[PENDING]** `docs/PROJECT_PLAN.md` version bump to v2.85.0, 139 tools, 28 modules
- **[PENDING]** HAE Apple Health data gap since v2.75.0 — manual HAE sync + Notion backfill (from last session)
- **[NEXT]** IC-2 `daily-insight-compute` Lambda (pre-compute insight pass at 9:42 AM) — enables IC-3 chain-of-thought
- **[NEXT]** IC-3 chain-of-thought two-pass for BoD + TL;DR
- **[NEXT]** IC-6 milestone architecture (weight milestone waypoints stored in profile)
- **[NEXT]** Google Calendar integration — Board rank #2, North Star gap #2
- **[PENDING]** Brittany weekly accountability email
- **[PENDING]** Reward seeding → Character Sheet Phase 4

## Version
v2.85.0 | 32 Lambdas | 139 MCP tools | 28 modules
