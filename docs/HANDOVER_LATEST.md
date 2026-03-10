# Life Platform — Handover
**Date:** 2026-03-09
**Version:** v3.4.1 — Sick Day System
**Session type:** Feature build (sick day flagging + full platform suppression)

---

## What Was Built

Matthew was sick March 8–9. The platform was penalizing him — Character Sheet EMA dragging down, anomaly alerts firing, freshness checker alerting, buddy page showing red beacons. This session built a complete sick day system.

### New DDB partition
`pk=USER#matthew#SOURCE#sick_days`, `sk=DATE#YYYY-MM-DD`
Both March 8 and March 9 have already been written to DDB directly.

### New files (already written to disk)
- `lambdas/sick_day_checker.py` — shared Layer utility: `check_sick_day()`, `get_sick_days_range()`, `write_sick_day()`, `delete_sick_day()`. Safe import (returns None on ImportError).
- `mcp/tools_sick_days.py` — 3 MCP tools: `tool_log_sick_day`, `tool_get_sick_days`, `tool_clear_sick_day`

### Lambda patches (NOT yet deployed — apply_sick_day_patches.py applies them)
| Lambda | Change |
|---|---|
| `character_sheet_lambda.py` | v1.1.0: freeze EMA on sick day — copy prev record, `sick_day=True`, `frozen_from` |
| `daily_metrics_compute_lambda.py` | v1.1.0: `day_grade_letter="sick"`, streaks preserved from prior day |
| `anomaly_detector_lambda.py` | v2.2.0: `sick_suppressed` severity, alert email suppressed |
| `freshness_checker_lambda.py` | suppresses SNS stale-source alerts on sick days |
| `daily_brief_lambda.py` | sends recovery brief (sleep/recovery/HRV only, purple banner) |

### Deploy artifacts (written to disk)
- `deploy/apply_sick_day_patches.py` — programmatic patch script for all 5 Lambdas + registry.py
- `deploy/sick_days_retroactive.sh` — Lambda re-invocation commands for Mar 8-9
- `deploy/bump_version_341.py` — fixes CHANGELOG + PROJECT_PLAN version bump
- `deploy/build_layer.sh` — already has `sick_day_checker.py` in MODULES array

---

## State of Key Files

| File | State |
|---|---|
| `lambdas/sick_day_checker.py` | ✅ Written, ready |
| `mcp/tools_sick_days.py` | ✅ Written, ready |
| `lambdas/character_sheet_lambda.py` | ✅ Written (v1.1.0 with sick day) |
| `lambdas/daily_metrics_compute_lambda.py` | ⚠️ NEEDS PATCH — run apply_sick_day_patches.py |
| `lambdas/anomaly_detector_lambda.py` | ⚠️ NEEDS PATCH — run apply_sick_day_patches.py |
| `lambdas/freshness_checker_lambda.py` | ⚠️ NEEDS PATCH — run apply_sick_day_patches.py |
| `lambdas/daily_brief_lambda.py` | ⚠️ NEEDS PATCH — run apply_sick_day_patches.py |
| `mcp/registry.py` | ⚠️ NEEDS PATCH — run apply_sick_day_patches.py (restores from git + adds tools) |
| `docs/CHANGELOG.md` | ⚠️ Overwritten with "placeholder" — fix with bump_version_341.py |
| `docs/PROJECT_PLAN.md` | ⚠️ Still on v3.4.0 — fix with bump_version_341.py |
| DDB sick_days records | ✅ 2026-03-08 + 2026-03-09 written |

---

## Deploy Sequence

Run these in order from `~/Documents/Claude/life-platform`:

```bash
# Step 1: Apply Lambda patches + fix registry.py
python3 deploy/apply_sick_day_patches.py

# Step 2: Fix CHANGELOG + PROJECT_PLAN version bump
python3 deploy/bump_version_341.py

# Step 3: Verify patches look right (spot check)
head -10 lambdas/daily_metrics_compute_lambda.py
grep -n "sick_day" lambdas/anomaly_detector_lambda.py | head -5
grep -n "sick_day" mcp/registry.py | head -3

# Step 4: Build Lambda Layer (sick_day_checker.py is already in MODULES)
bash deploy/build_layer.sh

# Step 5: Deploy all CDK stacks
cd cdk
cdk deploy LifePlatformCore --require-approval never
cdk deploy LifePlatformIngestion LifePlatformCompute LifePlatformEmail LifePlatformOperational LifePlatformMcp --require-approval never
cd ..

# Step 6: Recompute Mar 8-9 records (now that sick day flags exist + code handles them)
aws lambda invoke --function-name character-sheet-compute \
    --payload '{"date": "2026-03-08", "force": true}' \
    --cli-binary-format raw-in-base64-out /tmp/cs_08.json && cat /tmp/cs_08.json

aws lambda invoke --function-name character-sheet-compute \
    --payload '{"date": "2026-03-09", "force": true}' \
    --cli-binary-format raw-in-base64-out /tmp/cs_09.json && cat /tmp/cs_09.json

aws lambda invoke --function-name daily-metrics-compute \
    --payload '{"date": "2026-03-08", "force": true}' \
    --cli-binary-format raw-in-base64-out /tmp/dm_08.json && cat /tmp/dm_08.json

aws lambda invoke --function-name daily-metrics-compute \
    --payload '{"date": "2026-03-09", "force": true}' \
    --cli-binary-format raw-in-base64-out /tmp/dm_09.json && cat /tmp/dm_09.json

# Step 7: Git commit
git add -A && git commit -m "v3.4.1: sick day system — freeze EMA, suppress anomalies/freshness, recovery brief" && git push
```

---

## Verification After Deploy

Expected results from re-invocations:
- `character-sheet-compute` for Mar 8+9: `"sick_day": true`, `"frozen_from": "2026-03-07"` (or 08), no level change
- `daily-metrics-compute` for Mar 8+9: `"day_grade_letter": "sick"`, streaks preserved

Use MCP tool to verify:
```
get_sick_days(start_date="2026-03-07", end_date="2026-03-10")
```

---

## Next Session

1. **Brittany weekly email** — next major feature. Lambda slot + source file exist, no blockers.
2. **Architecture Review #4** — scheduled ~2026-04-08
3. **SIMP-1** — MCP tool usage audit after 30 days of CloudWatch EMF data (~2026-04-08)

### Roadmap (unstarted, prioritized)
- Monarch Money (#1) — financial stress pillar
- Google Calendar (#2) — demand-side context (cognitive load)
- Light exposure tracking (#31) — Habitify habit + correlation tool (~2-3 hr)
- Grip strength (#16) — $15 dynamometer, ~2 hr build

---

## Platform State (v3.4.1)
- MCP tools: 147 (added log_sick_day, get_sick_days, clear_sick_day)
- Lambdas: 41 (unchanged)
- CDK stacks: 8 (unchanged)
- Modules: 31 (added tools_sick_days.py)
- Cost: ~$25/month
- DDB sick_days: 2026-03-08, 2026-03-09 ✅
